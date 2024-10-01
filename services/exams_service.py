import copy
from sqlalchemy import text, desc
from datetime import datetime, timedelta

from models.main import db
from models.prescription import Patient
from models.segment import Exams, SegmentExam
from models.notes import ClinicalNotes
from services import memory_service
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status
from routes.utils import (
    formatExam,
    mdrd_calc,
    cg_calc,
    ckd_calc,
    ckd_calc_21,
    schwartz1_calc,
    schwartz2_calc,
    slugify,
)


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


@has_permission(Permission.READ_PRESCRIPTION)
def get_exams_by_admission(admission_number: int, id_segment: int):
    # TODO: refactor
    patient = Patient.findByAdmission(admissionNumber=admission_number)
    if patient is None:
        raise ValidationError(
            "Registro inexistente",
            "errors.invalidRecord",
            status.HTTP_400_BAD_REQUEST,
        )

    # TODO: refactor
    examsList = Exams.findByPatient(patient.idPatient)
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
            item = formatExam(e, key, segExam)
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
                            itemCalc = mdrd_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.skinColor,
                            )
                        elif keyCalc == "cg":
                            itemCalc = cg_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.weight,
                            )
                        elif keyCalc == "ckd":
                            itemCalc = ckd_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.skinColor,
                                patient.height,
                                patient.weight,
                            )
                        elif keyCalc == "ckd21":
                            itemCalc = ckd_calc_21(
                                e.value, patient.birthdate, patient.gender
                            )
                        elif keyCalc == "swrtz2":
                            itemCalc = schwartz2_calc(e.value, patient.height)
                        elif keyCalc == "swrtz1":
                            itemCalc = schwartz1_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.height,
                            )

                        if itemCalc["value"]:
                            itemCalc["name"] = segExam[keyCalc].name
                            itemCalc["perc"] = None
                            itemCalc["date"] = item["date"]
                            itemCalc["history"] = _history_calc(
                                keyCalc, item["history"], patient
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
        slugExam = slugify(e.prescriber)
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

    return (dict(results, **resultsText),)


def _history_exam(typeExam, examsList, segExam):
    results = []
    for e in examsList:
        if e.typeExam == typeExam:
            item = formatExam(e, e.typeExam.lower(), segExam)
            del item["ref"]
            results.append(item)
    return results


def _history_calc(typeExam, examsList, patient):
    results = []
    for e in examsList:
        item = {}
        if typeExam == "mdrd":
            item = mdrd_calc(
                e["value"], patient.birthdate, patient.gender, patient.skinColor
            )
        elif typeExam == "cg":
            item = cg_calc(
                e["value"], patient.birthdate, patient.gender, patient.weight
            )
        elif typeExam == "ckd":
            item = ckd_calc(
                e["value"],
                patient.birthdate,
                patient.gender,
                patient.skinColor,
                patient.height,
                patient.weight,
            )
        elif typeExam == "ckd21":
            item = ckd_calc_21(e["value"], patient.birthdate, patient.gender)
        elif typeExam == "swrtz2":
            item = schwartz2_calc(e["value"], patient.height)
        elif typeExam == "swrtz1":
            item = schwartz1_calc(
                e["value"],
                patient.birthdate,
                patient.gender,
                patient.height,
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
