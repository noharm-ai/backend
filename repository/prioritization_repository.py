import re
from datetime import date, datetime, timedelta

from sqlalchemy import BigInteger, Integer, and_, cast, desc, func, or_
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import undefer

from exception.validation_error import ValidationError
from models.appendix import Department
from models.enums import PatientConciliationStatusEnum, PrescriptionReviewTypeEnum
from models.main import db
from models.prescription import Patient, Prescription
from models.requests.prioritization_request import PrioritizationRequest
from models.segment import Segment
from utils import status

ICD_GROUPS = {
    "ONCO": [f"C{i:02}" for i in range(98)] + [f"D{i}" for i in range(37, 49)]
}


def get_prioritization_list(request: PrioritizationRequest):
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

    currentDepartment = request.currentDepartment and (len(request.idDept) > 0)

    if request.idSegment is not None:
        q = q.filter(Prescription.idSegment == request.idSegment)

    if len(request.idSegmentList) > 0:
        # refactor
        segments = []
        for s in request.idSegmentList:
            if s is not None and s != "null":
                segments.append(s)

        if len(segments) > 0:
            q = q.filter(Prescription.idSegment.in_(segments))
    else:
        q = q.filter(Prescription.idSegment != None)

    if len(request.idDept) > 0:
        idDept = list(map(int, request.idDept))
        if currentDepartment or request.concilia:
            q = q.filter(Prescription.idDepartment.in_(idDept))
        else:
            q = q.filter(postgresql.array(idDept).overlap(Prescription.aggDeps))

    if len(request.idDrug) > 0:
        idDrug = list(map(int, request.idDrug))
        if request.allDrugs:
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

    if request.pending:
        q = q.filter(Prescription.status == "0")

    if request.patientStatus == "DISCHARGED":
        q = q.filter(Patient.dischargeDate != None)

    if request.patientStatus == "ACTIVE":
        q = q.filter(Patient.dischargeDate == None)

    if request.agg and request.patientReviewType is not None:
        if int(request.patientReviewType) == PrescriptionReviewTypeEnum.PENDING.value:
            q = q.filter(
                Prescription.reviewType == PrescriptionReviewTypeEnum.PENDING.value
            )

        if int(request.patientReviewType) == PrescriptionReviewTypeEnum.REVIEWED.value:
            q = q.filter(
                Prescription.reviewType == PrescriptionReviewTypeEnum.REVIEWED.value
            )

    if request.agg:
        q = q.filter(Prescription.agg == True)

        q = q.filter(
            Prescription.date <= func.coalesce(Patient.dischargeDate, Prescription.date)
        )
    else:
        q = q.filter(Prescription.agg == None)

        if not request.concilia:
            q = q.filter(Segment.cpoe == False)

    if request.concilia:
        q = q.filter(Prescription.concilia != None)
    else:
        q = q.filter(Prescription.concilia == None)

    if request.insurance is not None and len(request.insurance.strip()) > 0:
        q = q.filter(Prescription.insurance.ilike("%" + str(request.insurance) + "%"))

    if len(request.indicators) > 0:
        ind_filters = []
        for i in request.indicators:
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

    if len(request.drugAttributes) > 0:
        attr_filters = []
        for a in request.drugAttributes:
            attr_filters.append(
                Prescription.features["drugAttributes"][a].as_integer() > 0
            )

        q = q.filter(or_(*attr_filters))

    if len(request.frequencies) > 0:
        q = q.filter(
            cast(Prescription.features["frequencies"], db.String).op("~*")(
                "|".join(map(re.escape, request.frequencies))
            )
        )

    if len(request.substances) > 0:
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
                cast(request.substances, postgresql.ARRAY(BigInteger))
            )
        )

    if len(request.substanceClasses) > 0:
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
                request.substanceClasses
            )
        )

    if len(request.idPatient) > 0:
        try:
            q = q.filter(
                Prescription.idPatient.in_([int(i) for i in request.idPatient])
            )
        except ValueError:
            q = q.filter(Prescription.idPatient == None)

    if request.id_patient_by_name_list and len(request.id_patient_by_name_list) > 0:
        try:
            q = q.filter(
                Prescription.idPatient.in_(
                    [int(i) for i in request.id_patient_by_name_list]
                )
            )
        except ValueError:
            pass

    if request.id_icd_list and len(request.id_icd_list) > 0:
        q = q.filter(Patient.id_icd.in_(request.id_icd_list))

    if request.id_icd_group_list and len(request.id_icd_group_list) > 0:
        query_icds = []
        for group in request.id_icd_group_list:
            icds = ICD_GROUPS.get(group, None)

            if icds:
                query_icds += icds

        if query_icds:
            q = q.filter(Patient.id_icd.in_(query_icds))

    if len(request.intervals) > 0:
        q = q.filter(
            cast(Prescription.features["intervals"], db.String).op("~*")(
                "|".join(map(re.escape, request.intervals))
            )
        )

    if request.diff is not None:
        if request.diff:
            q = q.filter(Prescription.features["diff"].astext.cast(Integer) > 0)
        else:
            q = q.filter(Prescription.features["diff"].astext.cast(Integer) == 0)

    if request.alert_level is not None:
        q = q.filter(Prescription.features["alertLevel"].astext == request.alert_level)

    if request.has_conciliation is not None:
        if request.has_conciliation:
            q = q.filter(
                Patient.st_conciliation == PatientConciliationStatusEnum.CREATED.value
            )
        else:
            q = q.filter(
                Patient.st_conciliation == PatientConciliationStatusEnum.PENDING.value
            )

    if request.has_clinical_notes is not None:
        if request.has_clinical_notes:
            q = q.filter(Prescription.notes != None)
        else:
            q = q.filter(Prescription.notes == None)

    if request.pending_interventions is not None:
        if request.pending_interventions:
            q = q.filter(
                Prescription.features["interventions"].astext.cast(Integer) > 0
            )
        else:
            q = q.filter(
                Prescription.features["interventions"].astext.cast(Integer) == 0
            )

    if request.global_score_min is not None:
        q = q.filter(
            (Prescription.features["globalScore"].astext.cast(Integer))
            >= request.global_score_min
        )

    if request.global_score_max is not None:
        q = q.filter(
            (Prescription.features["globalScore"].astext.cast(Integer))
            <= request.global_score_max
        )

    if request.age_min is not None:
        q = q.filter(
            Patient.birthdate
            <= (date.today() - timedelta(days=365 * int(request.age_min)))
        )

    if request.age_max is not None:
        q = q.filter(
            Patient.birthdate
            >= (date.today() - timedelta(days=365 * int(request.age_max)))
        )

    if request.prescriber is not None:
        q = q.filter(Prescription.prescriber.ilike(f"%{request.prescriber}%"))

    if request.tags:
        q = q.filter(
            cast(request.tags, postgresql.ARRAY(db.String)).overlap(Patient.tags)
        )

    if request.protocols:
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
                cast(request.protocols, postgresql.ARRAY(Integer))
            )
        )

    if request.city is not None and len(request.city.strip()) > 0:
        q = q.filter(Patient.city.ilike(f"%{request.city}%"))

    if request.medical_record is not None and len(request.medical_record.strip()) > 0:
        q = q.filter(Prescription.record == request.medical_record)

    if request.bed is not None and len(request.bed.strip()) > 0:
        q = q.filter(Prescription.bed.ilike(f"%{request.bed}%"))

    if request.endDate is None:
        endDate = request.startDate
    else:
        endDate = request.endDate

    start = datetime.combine(request.startDate, datetime.min.time())
    end = datetime.combine(endDate, datetime.min.time()) + timedelta(
        hours=23, minutes=59
    )
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

    q = q.order_by(desc("globalScore"))

    q = q.options(undefer(Patient.observation))

    return q.limit(500).all()
