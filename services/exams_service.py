"""Service: exams related operations"""

import copy
import json
import logging
from datetime import datetime, timedelta, date
from sqlalchemy import text, desc, and_

from models.main import db, redis_client, User
from models.prescription import Patient
from models.segment import Exams, SegmentExam
from models.notes import ClinicalNotes
from repository import exams_repository
from services import memory_service, cache_service
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status, examutils, stringutils, dateutils, numberutils


def create_exam(
    admission_number, id_prescription, id_patient, type_exam, value, unit, user
):
    if not memory_service.has_feature("PRIMARYCARE"):
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    exam = Exams()
    exam.idExame = get_next_id(user.schema)
    exam.idPatient = id_patient
    exam.idPrescription = id_prescription
    exam.admissionNumber = admission_number
    exam.date = datetime.today()
    exam.typeExam = type_exam
    exam.value = value
    exam.unit = unit

    db.session.add(exam)
    db.session.flush()


def get_next_id(schema):
    result = db.session.execute(
        text("SELECT NEXTVAL('" + schema + ".exame_fkexame_seq')")
    )

    return ([row[0] for row in result])[0]


def _get_textual_exams(admission_number: int = None, id_patient: int = None):
    admission_number_array = []

    if admission_number != None:
        admission_number_array.append(admission_number)
    else:
        admissions = (
            db.session.query(Patient)
            .filter(Patient.idPatient == id_patient)
            .order_by(desc(Patient.admissionDate))
            .limit(5)
            .all()
        )

        for a in admissions:
            admission_number_array.append(a.admissionNumber)

    if len(admission_number_array) == 0:
        return []

    return (
        ClinicalNotes.query.filter(
            ClinicalNotes.admissionNumber.in_(admission_number_array)
        )
        .filter(ClinicalNotes.isExam == True)
        .filter(ClinicalNotes.text != None)
        .filter(ClinicalNotes.date > (datetime.today() - timedelta(days=90)))
        .order_by(desc(ClinicalNotes.date))
        .all()
    )


@has_permission(Permission.READ_PRESCRIPTION, Permission.READ_REGULATION)
def get_exams_by_admission(admission_number: int, id_segment: int):
    """Get exams by admission number"""
    # TODO: refactor
    patient = Patient.findByAdmission(admissionNumber=admission_number)
    if patient is None:
        raise ValidationError(
            "Registro inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    # TODO: refactor
    examsList = exams_repository.get_exams_by_patient(patient.idPatient, days=90)
    segExam = SegmentExam.refDict(idSegment=id_segment)

    perc = {
        "h_conleuc": {
            "total": 1,
            "relation": [
                "h_conlinfoc",
                "h_conmono",
                "h_coneos",
                "h_conbaso",
                "h_consegm",
            ],
        }
    }

    bufferList = {}
    typeExams = []
    for e in examsList:
        if not e.typeExam.lower() in typeExams and e.typeExam.lower() in segExam:
            key = e.typeExam.lower()
            item = examutils.formatExam(
                value=e.value,
                typeExam=key,
                unit=e.unit,
                date=e.date.isoformat(),
                segExam=segExam,
            )
            item["name"] = segExam[key].name
            item["perc"] = None
            item["history"] = _history_exam(e.typeExam, examsList, segExam)
            item["text"] = False
            bufferList[key] = item
            typeExams.append(key)
            if key in perc:
                perc[key]["total"] = float(e.value)

            if segExam[key].initials.lower() == "creatinina":
                for keyCalc in ["mdrd", "ckd", "ckd21", "cg", "swrtz2", "swrtz1"]:
                    if keyCalc in segExam and patient:
                        if keyCalc == "mdrd":
                            itemCalc = examutils.mdrd_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.skinColor,
                            )
                        elif keyCalc == "cg":
                            itemCalc = examutils.cg_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.weight,
                            )
                        elif keyCalc == "ckd":
                            itemCalc = examutils.ckd_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.skinColor,
                                patient.height,
                                patient.weight,
                            )
                        elif keyCalc == "ckd21":
                            itemCalc = examutils.ckd_calc_21(
                                e.value, patient.birthdate, patient.gender
                            )
                        elif keyCalc == "swrtz2":
                            itemCalc = examutils.schwartz2_calc(e.value, patient.height)
                        elif keyCalc == "swrtz1":
                            itemCalc = examutils.schwartz1_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.height,
                            )

                        # set custom exams config
                        itemCalc = _fill_custom_exams(
                            exam_type=keyCalc, custom_exam=itemCalc, seg_exam=segExam
                        )

                        if itemCalc["value"]:
                            itemCalc["name"] = segExam[keyCalc].name
                            itemCalc["perc"] = None
                            itemCalc["date"] = item["date"]
                            itemCalc["history"] = _history_calc(
                                keyCalc, item["history"], patient, segExam
                            )
                            bufferList[keyCalc] = itemCalc

    for p in perc:
        total = perc[p]["total"]
        for r in perc[p]["relation"]:
            if r in bufferList:
                val = bufferList[r]["value"]
                bufferList[r]["perc"] = round((val * 100) / total, 1)

    results = copy.deepcopy(segExam)
    for e in segExam:
        if e in bufferList:
            results[e] = bufferList[e]
        else:
            del results[e]

    examsText = _get_textual_exams(id_patient=patient.idPatient)
    resultsText = {}
    for e in examsText:
        slugExam = stringutils.slugify(e.prescriber)
        if not slugExam in resultsText.keys():
            resultsText[slugExam] = {
                "name": e.prescriber,
                "text": True,
                "date": e.date.isoformat(),
                "ref": e.text[:20],
                "history": [],
            }

        item = {}
        item["date"] = e.date.isoformat()
        item["value"] = e.text
        resultsText[slugExam]["history"].append(item)
        resultsText[slugExam]["date"] = e.date.isoformat()

    return dict(results, **resultsText)


def _history_exam(typeExam, examsList, segExam):
    results = []
    for e in examsList:
        if e.typeExam == typeExam:
            item = examutils.formatExam(
                value=e.value,
                typeExam=e.typeExam.lower(),
                unit=e.unit,
                date=e.date.isoformat(),
                segExam=segExam,
            )
            if "ref" in item:
                del item["ref"]
            results.append(item)
    return results


def _history_calc(typeExam, examsList, patient, segExam):
    custom_exams = [
        "mdrd",
        "ckd",
        "ckd21",
        "cg",
        "swrtz2",
        "swrtz1",
    ]
    results = []

    for e in examsList:
        item = {}
        if typeExam == "mdrd":
            item = examutils.mdrd_calc(
                e["value"], patient.birthdate, patient.gender, patient.skinColor
            )
        elif typeExam == "cg":
            item = examutils.cg_calc(
                e["value"], patient.birthdate, patient.gender, patient.weight
            )
        elif typeExam == "ckd":
            item = examutils.ckd_calc(
                e["value"],
                patient.birthdate,
                patient.gender,
                patient.skinColor,
                patient.height,
                patient.weight,
            )
        elif typeExam == "ckd21":
            item = examutils.ckd_calc_21(e["value"], patient.birthdate, patient.gender)
        elif typeExam == "swrtz2":
            item = examutils.schwartz2_calc(e["value"], patient.height)
        elif typeExam == "swrtz1":
            item = examutils.schwartz1_calc(
                e["value"],
                patient.birthdate,
                patient.gender,
                patient.height,
            )

        if typeExam in custom_exams:
            item = _fill_custom_exams(
                exam_type=typeExam, custom_exam=item, seg_exam=segExam
            )

        item["date"] = e["date"]
        results.append(item)
    return results


@has_permission(Permission.ADMIN_EXAMS)
def get_exams_default_refs():
    query = text(
        """
        select 
            s.nome as segment,
            se.tpexame as type_exam,
            se.nome as name,
            se.abrev as initials,
            se.referencia as ref,
            se.min,
            se.max,
            se.posicao as order
        from 
            hsc_test.segmentoexame se
            inner join hsc_test.segmento s on (se.idsegmento = s.idsegmento)
        where 
            se.idsegmento in (1, 3)
        order by 
            s.idsegmento, se.nome 
    """
    )

    refs = db.session.execute(query).all()

    results = []
    for r in refs:
        results.append(
            {
                "segment": r.segment,
                "type": r.type_exam,
                "name": r.name,
                "initials": r.initials,
                "ref": r.ref,
                "min": r.min,
                "max": r.max,
                "order": r.order,
            }
        )

    return results


def _get_exams_previous_results(id_patient: int):
    examLatest = (
        db.session.query(Exams.typeExam.label("typeExam"), Exams.date.label("date"))
        .select_from(Exams)
        .distinct(Exams.typeExam)
        .filter(Exams.idPatient == id_patient)
        .filter(Exams.date >= (date.today() - timedelta(days=90)))
        .order_by(Exams.typeExam, Exams.date.desc())
        .subquery()
    )

    el = db.aliased(examLatest)

    resultsPrev = (
        Exams.query.distinct(Exams.typeExam)
        .join(el, and_(Exams.typeExam == el.c.typeExam, Exams.date < el.c.date))
        .filter(Exams.idPatient == id_patient)
        .filter(Exams.date >= (date.today() - timedelta(days=90)))
        .order_by(Exams.typeExam, Exams.date.desc())
    )

    previous_exams = {}

    for e in resultsPrev:
        previous_exams[e.typeExam.lower()] = e.value

    return previous_exams


def _get_exams_current_results_hybrid(id_patient: int, schema: str):
    MIN_DATE = date.today() - timedelta(days=5)
    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")

    results = (
        Exams.query.distinct(Exams.typeExam)
        .filter(Exams.idPatient == id_patient)
        .filter(Exams.date >= MIN_DATE)
        .order_by(Exams.typeExam, Exams.date.desc())
        .all()
    )

    cache_key = f"{schema}:{id_patient}:exames"
    cache_result = cache_service.get_hgetall(key=cache_key)
    cache_exams = {}
    if cache_result:
        cache_exams = {}
        for exam_type, exam_object in cache_result.items():
            cache_exams[exam_type.lower()] = exam_object

    exams = {}
    for e in results:
        prev_value = cache_exams.get(e.typeExam.lower())

        if not prev_value:
            logger.warning(f"CACHE_MISS: {cache_key} - type: {e.typeExam.lower()}")

        exams[e.typeExam.lower()] = {
            "value": e.value,
            "unit": e.unit,
            "date": e.date.isoformat(),
            "prev": prev_value.get("prev", None) if prev_value else None,
        }

    return exams


def _get_exams_current_results(
    id_patient: int, add_previous_exams: bool, cache: bool, schema: str, lower_key=True
):
    MIN_DATE = date.today() - timedelta(days=5)

    if cache:
        cache_result = cache_service.get_hgetall(key=f"{schema}:{id_patient}:exames")
        if cache_result:
            exams = {}
            for exam_type, exam_object in cache_result.items():
                exam_date = exam_object.get("date", None)
                if exam_date != None and exam_date >= MIN_DATE.isoformat():
                    exams[exam_type.lower()] = exam_object

            return exams

    previous_exams = {}
    if add_previous_exams:
        previous_exams = _get_exams_previous_results(id_patient=id_patient)

    results = (
        Exams.query.distinct(Exams.typeExam)
        .filter(Exams.idPatient == id_patient)
        .filter(Exams.date >= MIN_DATE)
        .order_by(Exams.typeExam, Exams.date.desc())
        .all()
    )

    exams = {}
    for e in results:
        exams[e.typeExam.lower() if lower_key else e.typeExam] = {
            "value": e.value,
            "unit": e.unit,
            "date": e.date.isoformat(),
            "prev": previous_exams.get(e.typeExam.lower(), None),
        }

    return exams


@has_permission(Permission.READ_PRESCRIPTION)
def find_latest_exams(
    patient: Patient,
    idSegment: int,
    schema: str,
    add_previous_exams=False,
    cache=True,
    cache_hybrid=True,
    is_complete=True,
):
    """
    Get the latest exams for a patient
    """
    if is_complete and cache_hybrid:
        # hybrid approach (cache and db)
        # test better performance ensuring most recent results
        current_exams = _get_exams_current_results_hybrid(
            id_patient=patient.idPatient, schema=schema
        )
    else:
        current_exams = _get_exams_current_results(
            id_patient=patient.idPatient,
            add_previous_exams=add_previous_exams,
            cache=False,  # disable cache for prescalc
            schema=schema,
        )

    segExam = SegmentExam.refDict(idSegment)
    age = dateutils.data2age(
        patient.birthdate.isoformat() if patient.birthdate else date.today().isoformat()
    )

    exams = {}
    for e in segExam:
        examEmpty = {
            "value": None,
            "alert": False,
            "ref": None,
            "name": None,
            "unit": None,
            "delta": None,
        }
        examEmpty["date"] = None
        examEmpty["min"] = segExam[e].min
        examEmpty["max"] = segExam[e].max
        examEmpty["name"] = segExam[e].name
        examEmpty["initials"] = segExam[e].initials
        if segExam[e].initials.lower().strip() == "creatinina":
            exams["cr"] = examEmpty
        else:
            exams[e.lower()] = examEmpty

    custom_exams = [
        "mdrd",
        "ckd",
        "ckd21",
        "cg",
        "swrtz2",
        "swrtz1",
    ]
    examsExtra = {}
    for exam_type, exam_object in current_exams.items():
        if exam_type not in custom_exams:
            exams[exam_type] = examutils.formatExam(
                value=exam_object.get("value", None),
                typeExam=exam_type,
                unit=exam_object.get("unit", None),
                date=exam_object.get("date", None),
                segExam=segExam,
                prevValue=exam_object.get("prev", None),
            )

        if exam_type in segExam:
            if (
                segExam[exam_type].initials.lower().strip() == "creatinina"
                and "cr" in exams
                and exams["cr"]["value"] == None
            ):
                exams["cr"] = examutils.formatExam(
                    value=exam_object.get("value", None),
                    typeExam=exam_type,
                    unit=exam_object.get("unit", None),
                    date=exam_object.get("date", None),
                    segExam=segExam,
                    prevValue=exam_object.get("prev", None),
                )

            extra_config = [
                {"exam_key": "tgo", "extra_key": "tgo"},
                {"exam_key": "tgp", "extra_key": "tgp"},
                {"exam_key": "plaquetas", "extra_key": "plqt"},
            ]
            for ec in extra_config:
                if segExam[exam_type].initials.lower().strip() == ec.get("exam_key"):
                    examsExtra[ec.get("extra_key")] = examutils.formatExam(
                        value=exam_object.get("value", None),
                        typeExam=exam_type,
                        unit=exam_object.get("unit", None),
                        date=exam_object.get("date", None),
                        segExam=segExam,
                        prevValue=exam_object.get("prev", None),
                    )

    if "cr" in exams:
        if age > 17:
            if "mdrd" in exams:
                exams["mdrd"] = examutils.mdrd_calc(
                    exams["cr"]["value"],
                    patient.birthdate,
                    patient.gender,
                    patient.skinColor,
                )
            if "cg" in exams:
                exams["cg"] = examutils.cg_calc(
                    exams["cr"]["value"],
                    patient.birthdate,
                    patient.gender,
                    patient.weight,
                )
            if "ckd" in exams:
                exams["ckd"] = examutils.ckd_calc(
                    exams["cr"]["value"],
                    patient.birthdate,
                    patient.gender,
                    patient.skinColor,
                    patient.height,
                    patient.weight,
                )
            if "ckd21" in exams:
                exams["ckd21"] = examutils.ckd_calc_21(
                    exams["cr"]["value"], patient.birthdate, patient.gender
                )
        else:
            if "swrtz2" in exams:
                exams["swrtz2"] = examutils.schwartz2_calc(
                    exams["cr"]["value"], patient.height
                )

            if "swrtz1" in exams:
                exams["swrtz1"] = examutils.schwartz1_calc(
                    exams["cr"]["value"],
                    patient.birthdate,
                    patient.gender,
                    patient.height,
                )

    # set custom exams config
    for ce in custom_exams:
        if ce in exams:
            exams[ce] = _fill_custom_exams(
                exam_type=ce, custom_exam=exams[ce], seg_exam=segExam
            )

    return dict(exams, **examsExtra)


def _fill_custom_exams(exam_type: str, custom_exam: dict, seg_exam: dict):
    if exam_type in seg_exam:
        ref = seg_exam[exam_type]
        if custom_exam["value"]:
            alert = not (
                custom_exam["value"] >= numberutils.none2zero(ref.min)
                and custom_exam["value"] <= numberutils.none2zero(ref.max)
            )
        else:
            alert = False

        return custom_exam | {
            "ref": ref.ref,
            "initials": ref.initials,
            "min": ref.min,
            "max": ref.max,
            "name": ref.name,
            "alert": alert,
        }

    return custom_exam


@has_permission(Permission.WRITE_PRESCRIPTION, Permission.MAINTAINER)
def refresh_exams_cache(id_patient: int, user_context: User):
    """get current exams and save in cache"""
    exams = _get_exams_current_results(
        id_patient=id_patient,
        add_previous_exams=True,
        cache=False,
        schema=user_context.schema,
        lower_key=False,
    )

    key = f"{user_context.schema}:{id_patient}:exames"
    for type_exam, exam in exams.items():
        redis_client.hset(key, type_exam, json.dumps(exam))
