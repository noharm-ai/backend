import re
from datetime import date, timedelta
from sqlalchemy import func, Integer, and_, cast, BigInteger, or_, desc
from sqlalchemy.orm import undefer
from sqlalchemy.dialects import postgresql

from models.main import db
from models.enums import PrescriptionReviewTypeEnum, PatientConciliationStatusEnum
from models.prescription import Prescription, Patient
from models.appendix import Department
from models.segment import Segment
from decorators.has_permission_decorator import has_permission, Permission
from utils import dateutils, numberutils, prescriptionutils, status
from services import prescription_service
from exception.validation_error import ValidationError


@has_permission(Permission.READ_PRESCRIPTION)
def get_prioritization_list(
    idSegment=None,
    idSegmentList=[],
    idDept=[],
    idDrug=[],
    startDate=date.today(),
    endDate=None,
    pending=False,
    agg=False,
    currentDepartment=False,
    concilia=False,
    allDrugs=False,
    insurance=None,
    indicators=[],
    frequencies=[],
    patientStatus=None,
    substances=[],
    substanceClasses=[],
    patientReviewType=None,
    drugAttributes=[],
    idPatient=[],
    intervals=[],
    prescriber=None,
    diff=None,
    global_score_min=None,
    global_score_max=None,
    pending_interventions=None,
    has_conciliation=None,
    alert_level=None,
    tags=None,
    has_clinical_notes=None,
    protocols=None,
    age_min=None,
    age_max=None,
    id_patient_by_name_list=None,
):

    q = (
        db.session.query(
            Prescription,
            Patient,
            Department.name.label("department"),
            func.count().over(),
            (Prescription.features["globalScore"].astext.cast(Integer)).label(
                "globalScore"
            ),
        )
        .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)
        .outerjoin(
            Department,
            and_(
                Department.id == Prescription.idDepartment,
                Department.idHospital == Prescription.idHospital,
            ),
        )
        .outerjoin(Segment, Prescription.idSegment == Segment.id)
    )

    currentDepartment = bool(int(numberutils.none2zero(currentDepartment))) and (
        len(idDept) > 0
    )

    if idSegment != None:
        q = q.filter(Prescription.idSegment == idSegment)

    if len(idSegmentList) > 0:
        # refactor
        segments = []
        for s in idSegmentList:
            if s != None and s != "null":
                segments.append(s)

        if len(segments) > 0:
            q = q.filter(Prescription.idSegment.in_(idSegmentList))
    else:
        q = q.filter(Prescription.idSegment != None)

    if len(idDept) > 0:
        idDept = list(map(int, idDept))
        if currentDepartment or bool(int(numberutils.none2zero(concilia))) == True:
            q = q.filter(Prescription.idDepartment.in_(idDept))
        else:
            q = q.filter(postgresql.array(idDept).overlap(Prescription.aggDeps))

    if len(idDrug) > 0:
        idDrug = list(map(int, idDrug))
        if bool(int(numberutils.none2zero(allDrugs))):
            q = q.filter(
                cast(idDrug, postgresql.ARRAY(BigInteger)).contained_by(
                    Prescription.aggDrugs
                )
            )
        else:
            q = q.filter(
                cast(idDrug, postgresql.ARRAY(BigInteger)).overlap(
                    Prescription.aggDrugs
                )
            )

    if bool(int(numberutils.none2zero(pending))):
        q = q.filter(Prescription.status == "0")

    if patientStatus == "DISCHARGED":
        q = q.filter(Patient.dischargeDate != None)

    if patientStatus == "ACTIVE":
        q = q.filter(Patient.dischargeDate == None)

    if bool(int(numberutils.none2zero(agg))) and patientReviewType != None:
        if int(patientReviewType) == PrescriptionReviewTypeEnum.PENDING.value:
            q = q.filter(
                Prescription.reviewType == PrescriptionReviewTypeEnum.PENDING.value
            )

        if int(patientReviewType) == PrescriptionReviewTypeEnum.REVIEWED.value:
            q = q.filter(
                Prescription.reviewType == PrescriptionReviewTypeEnum.REVIEWED.value
            )

    if bool(int(numberutils.none2zero(agg))):
        q = q.filter(Prescription.agg == True)

        q = q.filter(
            Prescription.date <= func.coalesce(Patient.dischargeDate, Prescription.date)
        )
    else:
        q = q.filter(Prescription.agg == None)

        if not bool(int(numberutils.none2zero(concilia))):
            q = q.filter(Segment.cpoe == False)

    if bool(int(numberutils.none2zero(concilia))):
        q = q.filter(Prescription.concilia != None)
    else:
        q = q.filter(Prescription.concilia == None)

    if insurance != None and len(insurance.strip()) > 0:
        q = q.filter(Prescription.insurance.ilike("%" + str(insurance) + "%"))

    if len(indicators) > 0:
        ind_filters = []
        for i in indicators:
            interactions = ["it", "dt", "dm", "iy", "sl", "rx"]
            if i in interactions:
                ind_filters.append(
                    Prescription.features["alertStats"]["interactions"][i].as_integer()
                    > 0
                )
            else:
                ind_filters.append(
                    Prescription.features["alertStats"][i].as_integer() > 0
                )

        q = q.filter(or_(*ind_filters))

    if len(drugAttributes) > 0:
        attr_filters = []
        for a in drugAttributes:
            attr_filters.append(
                Prescription.features["drugAttributes"][a].as_integer() > 0
            )

        q = q.filter(or_(*attr_filters))

    if len(frequencies) > 0:
        q = q.filter(
            cast(Prescription.features["frequencies"], db.String).op("~*")(
                "|".join(map(re.escape, frequencies))
            )
        )

    if len(substances) > 0:
        elm = db.Column("elm", type_=postgresql.JSONB)
        subs_query = (
            db.session.query(elm.cast(postgresql.TEXT))
            .select_from(
                func.json_array_elements(Prescription.features["substanceIDs"]).alias(
                    "elm"
                )
            )
            .as_scalar()
        )

        q = q.filter(
            cast(func.array(subs_query), postgresql.ARRAY(BigInteger)).overlap(
                cast(substances, postgresql.ARRAY(BigInteger))
            )
        )

    if len(substanceClasses) > 0:
        elm_substance_class = db.Column("elmSubstanceClass", type_=postgresql.JSONB)
        subs_query = (
            db.session.query(elm_substance_class.cast(postgresql.TEXT))
            .select_from(
                func.json_array_elements_text(
                    Prescription.features["substanceClassIDs"]
                ).alias("elmSubstanceClass")
            )
            .as_scalar()
        )

        q = q.filter(
            cast(func.array(subs_query), postgresql.ARRAY(postgresql.TEXT)).overlap(
                substanceClasses
            )
        )

    if len(idPatient) > 0:
        try:
            q = q.filter(Prescription.idPatient.in_([int(i) for i in idPatient]))
        except ValueError:
            q = q.filter(Prescription.idPatient == None)

    if id_patient_by_name_list and len(id_patient_by_name_list) > 0:
        try:
            q = q.filter(
                Prescription.idPatient.in_([int(i) for i in id_patient_by_name_list])
            )
        except ValueError:
            pass

    if len(intervals) > 0:
        q = q.filter(
            cast(Prescription.features["intervals"], db.String).op("~*")(
                "|".join(map(re.escape, intervals))
            )
        )

    if diff != None:
        if bool(int(diff)):
            q = q.filter(Prescription.features["diff"].astext.cast(Integer) > 0)
        else:
            q = q.filter(Prescription.features["diff"].astext.cast(Integer) == 0)

    if alert_level != None:
        q = q.filter(Prescription.features["alertLevel"].astext == alert_level)

    if has_conciliation != None:
        if bool(int(has_conciliation)):
            q = q.filter(
                Patient.st_conciliation == PatientConciliationStatusEnum.CREATED.value
            )
        else:
            q = q.filter(
                Patient.st_conciliation == PatientConciliationStatusEnum.PENDING.value
            )

    if has_clinical_notes != None:
        if bool(int(has_clinical_notes)):
            q = q.filter(Prescription.notes != None)
        else:
            q = q.filter(Prescription.notes == None)

    if pending_interventions != None:
        if bool(int(pending_interventions)):
            q = q.filter(
                Prescription.features["interventions"].astext.cast(Integer) > 0
            )
        else:
            q = q.filter(
                Prescription.features["interventions"].astext.cast(Integer) == 0
            )

    if global_score_min != None:
        q = q.filter(
            (Prescription.features["globalScore"].astext.cast(Integer))
            >= global_score_min
        )

    if global_score_max != None:
        q = q.filter(
            (Prescription.features["globalScore"].astext.cast(Integer))
            <= global_score_max
        )

    if age_min is not None:
        q = q.filter(
            Patient.birthdate <= (date.today() - timedelta(days=365 * int(age_min)))
        )

    if age_max is not None:
        q = q.filter(
            Patient.birthdate >= (date.today() - timedelta(days=365 * int(age_max)))
        )

    if prescriber != None:
        q = q.filter(Prescription.prescriber.ilike(f"%{prescriber}%"))

    if tags:
        q = q.filter(cast(tags, postgresql.ARRAY(db.String)).overlap(Patient.tags))

    if protocols:
        elm = db.Column("elm", type_=postgresql.JSONB)
        protocols_query = (
            db.session.query(elm.cast(postgresql.TEXT))
            .select_from(
                func.json_array_elements(Prescription.features["protocolAlerts"]).alias(
                    "elm"
                )
            )
            .as_scalar()
        )

        q = q.filter(
            cast(func.array(protocols_query), postgresql.ARRAY(Integer)).overlap(
                cast(protocols, postgresql.ARRAY(Integer))
            )
        )

    if endDate is None:
        endDate = startDate

    start = dateutils.parse_date_or_today(startDate)
    end = dateutils.parse_date_or_today(endDate) + timedelta(hours=23, minutes=59)
    days_between = (end - start).days
    max_days = 120

    if days_between > max_days:
        raise ValidationError(
            "O intervalo de datas não pode ser maior que 120 dias",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    q = q.filter(Prescription.date >= start)
    q = q.filter(Prescription.date <= end)

    if agg:
        q = q.order_by(desc("globalScore"))
    else:
        q = q.order_by(desc(Prescription.date))

    q = q.options(undefer(Patient.observation))

    prioritization_results = q.limit(500).all()

    results = []
    for p in prioritization_results:
        patient = p[1]
        if patient is None:
            patient = Patient()
            patient.idPatient = p[0].idPatient
            patient.admissionNumber = p[0].admissionNumber

        featuresNames = [
            "alerts",
            "prescriptionScore",
            "scoreOne",
            "scoreTwo",
            "scoreThree",
            "am",
            "av",
            "controlled",
            "np",
            "tube",
            "diff",
            "alertExams",
            "interventions",
            "complication",
            "alertLevel",
        ]

        features = {"processed": True}
        if p[0].features:
            for f in featuresNames:
                features[f] = p[0].features[f] if f in p[0].features else 0

            features["globalScore"] = numberutils.none2zero(p.globalScore)

            if features["globalScore"] > 90:
                features["class"] = "red"
            elif features["globalScore"] > 60:
                features["class"] = "orange"
            elif features["globalScore"] > 10:
                features["class"] = "yellow"
            else:
                features["class"] = "green"

            features["alertStats"] = (
                p[0].features["alertStats"] if "alertStats" in p[0].features else None
            )

            if "scoreVariation" in p[0].features:
                features["scoreVariation"] = (
                    p[0].features.get("scoreVariation").get("variation")
                )
            else:
                features["scoreVariation"] = 0

        else:
            features["processed"] = False
            features["globalScore"] = 0
            features["scoreVariation"] = 0
            features["class"] = "blue"

        observation = None
        if p[1] and p[1].observation != None and p[1].observation != "":
            observation = (
                p[1].observation[:300] + "..."
                if len(p[1].observation) > 300
                else p[1].observation
            )

        results.append(
            dict(
                features,
                **{
                    "idPrescription": str(p[0].id),
                    "idPatient": str(p[0].idPatient),
                    "name": patient.admissionNumber,
                    "admissionNumber": patient.admissionNumber,
                    "idSegment": p[0].idSegment,
                    "birthdate": (
                        patient.birthdate.isoformat() if patient.birthdate else None
                    ),
                    "gender": patient.gender,
                    "weight": patient.weight,
                    "skinColor": patient.skinColor,
                    "lengthStay": prescriptionutils.lenghStay(patient.admissionDate),
                    "dischargeDate": (
                        patient.dischargeDate.isoformat()
                        if patient.dischargeDate
                        else None
                    ),
                    "dischargeReason": patient.dischargeReason,
                    "date": p[0].date.isoformat(),
                    "department": str(p[2]),
                    "insurance": p[0].insurance,
                    "bed": p[0].bed,
                    "status": p[0].status,
                    "isBeingEvaluated": prescription_service.is_being_evaluated(
                        p[0].features
                    ),
                    "reviewType": p[0].reviewType,
                    "observation": observation,
                    "totalRecords": p[3],
                    "agg": p[0].agg,
                    "prescriptionAggId": prescriptionutils.gen_agg_id(
                        admission_number=p[0].admissionNumber,
                        id_segment=p[0].idSegment,
                        pdate=p[0].date,
                    ),
                    "patientTags": patient.tags,
                },
            )
        )

    return results
