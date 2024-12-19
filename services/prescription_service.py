import json
from sqlalchemy import desc, nullsfirst, func, and_, or_, text
from datetime import date, datetime

from models.main import db, redis_client, User
from models.prescription import (
    Prescription,
    Patient,
    Department,
    PrescriptionDrug,
    PrescriptionAudit,
    PatientAudit,
)
from models.enums import (
    FeatureEnum,
    PrescriptionAuditTypeEnum,
    AppFeatureFlagEnum,
    PatientAuditTypeEnum,
)
from exception.validation_error import ValidationError
from services import (
    memory_service,
    feature_service,
    data_authorization_service,
    clinical_notes_queries_service,
    exams_service,
    patient_service,
)
from decorators.has_permission_decorator import has_permission, Permission
from utils import status, prescriptionutils, dateutils


@has_permission(Permission.READ_PRESCRIPTION, Permission.READ_DISCHARGE_SUMMARY)
def search(search_key):
    if search_key == None:
        raise ValidationError(
            "Parâmetro inválido",
            "errors.invalidParam",
            status.HTTP_400_BAD_REQUEST,
        )

    q_presc_admission = (
        db.session.query(
            Prescription,
            Patient.birthdate.label("birthdate"),
            Patient.gender.label("gender"),
            Department.name.label("department"),
            Patient.admissionDate.label("admission_date"),
            func.row_number().over(order_by=desc(Prescription.date)).label("priority"),
        )
        .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)
        .outerjoin(
            Department,
            and_(
                Department.id == Prescription.idDepartment,
                Department.idHospital == Prescription.idHospital,
            ),
        )
        .filter(
            or_(
                Prescription.id == search_key,
                and_(
                    Prescription.admissionNumber == search_key,
                    func.date(Prescription.date) <= date.today(),
                    Prescription.agg != None,
                ),
            )
        )
        .order_by(desc(Prescription.date))
        .limit(5)
    )

    q_concilia = (
        db.session.query(
            Prescription,
            Patient.birthdate.label("birthdate"),
            Patient.gender.label("gender"),
            Department.name.label("department"),
            Patient.admissionDate.label("admission_date"),
            func.row_number().over(order_by=desc(Prescription.date)).label("priority"),
        )
        .outerjoin(Patient, Patient.admissionNumber == Prescription.admissionNumber)
        .outerjoin(
            Department,
            and_(
                Department.id == Prescription.idDepartment,
                Department.idHospital == Prescription.idHospital,
            ),
        )
        .filter(
            and_(
                Prescription.admissionNumber == search_key,
                Prescription.concilia != None,
            ),
        )
        .order_by(desc(Prescription.date))
        .limit(1)
    )

    results = (
        q_presc_admission.union_all(q_concilia)
        .order_by("priority", nullsfirst(Prescription.concilia))
        .all()
    )

    list = []

    for p in results:
        list.append(
            {
                "idPrescription": str(p[0].id),
                "admissionNumber": p[0].admissionNumber,
                "date": p[0].date.isoformat() if p[0].date else None,
                "status": p[0].status,
                "agg": p[0].agg,
                "concilia": p[0].concilia,
                "birthdate": p[1].isoformat() if p[1] else None,
                "gender": p[2],
                "department": p[3],
                "admissionDate": p[4].isoformat() if p[4] else None,
            }
        )

    return list


@has_permission(Permission.WRITE_PRESCRIPTION)
def start_evaluation(id_prescription, user_context: User):
    p = (
        db.session.query(Prescription)
        .filter(Prescription.id == id_prescription)
        .first()
    )
    if p is None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    if p.features == None:
        raise ValidationError(
            "Esta prescrição ainda não possui indicadores.",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    if is_being_evaluated(p.features):
        return p.features["evaluation"] if "evaluation" in p.features else None
    else:
        current_user = db.session.query(User).filter(User.id == user_context.id).first()
        evaluation_object = {
            "userId": user_context.id,
            "userName": current_user.name,
            "startDate": datetime.today().isoformat(),
        }

        p.features = dict(p.features, **{"evaluation": evaluation_object})

        db.session.flush()

        return evaluation_object


def is_being_evaluated(features):
    max_evaluation_minutes = 5

    if (
        features != None
        and "evaluation" in features
        and "startDate" in features["evaluation"]
    ):
        evaluation_date = features["evaluation"]["startDate"]
        current_evaluation_minutes = (
            datetime.today() - datetime.fromisoformat(evaluation_date)
        ).total_seconds() / 60

        return current_evaluation_minutes <= max_evaluation_minutes

    return False


@has_permission(Permission.WRITE_PRESCRIPTION, Permission.WRITE_DRUG_SCORE)
def recalculate_prescription(id_prescription: int, user_context: User):
    p = (
        db.session.query(Prescription)
        .filter(Prescription.id == id_prescription)
        .first()
    )

    if p is None:
        raise ValidationError(
            "Prescrição inexistente.",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    _update_patient_weight(
        admission_number=p.admissionNumber, user_context=user_context
    )

    if p.agg:
        if feature_service.is_cpoe():
            prescription_results = get_query_prescriptions_by_agg(
                agg_prescription=p, is_cpoe=feature_service.is_cpoe(), only_id=True
            ).all()

            prescription_ids = []
            for item in prescription_results:
                prescription_ids.append(item.id)

            db.session.query(Prescription).filter(
                Prescription.id.in_(prescription_ids)
            ).filter(Prescription.idSegment == None).update(
                {
                    "idHospital": p.idHospital,
                    "idDepartment": p.idDepartment,
                    "idSegment": p.idSegment,
                },
                synchronize_session="fetch",
            )

            db.session.flush()

            query = text(
                f"""INSERT INTO {user_context.schema}.presmed
                    SELECT
                        pm.*
                    FROM
                        {user_context.schema}.presmed pm
                    WHERE 
                        fkprescricao = ANY(:prescriptionIds)
                """
            )

            db.session.execute(query, {"prescriptionIds": prescription_ids})
        else:
            query = text(
                "INSERT INTO "
                + user_context.schema
                + ".presmed \
                    SELECT pm.*\
                    FROM "
                + user_context.schema
                + ".presmed pm\
                    WHERE fkprescricao IN (\
                        SELECT fkprescricao\
                        FROM "
                + user_context.schema
                + ".prescricao p\
                        WHERE p.nratendimento = :admissionNumber"
                + "\
                        AND p.idsegmento IS NOT NULL \
                        AND (\
                            p.dtprescricao::date = "
                + "date(:prescDate) OR\
                            p.dtvigencia::date = "
                + "date(:prescDate)\
                        )\
                    );"
            )

            db.session.execute(
                query, {"admissionNumber": p.admissionNumber, "prescDate": p.date}
            )
    else:
        query = text(
            "INSERT INTO "
            + user_context.schema
            + ".presmed \
                    SELECT *\
                    FROM "
            + user_context.schema
            + ".presmed\
                    WHERE fkprescricao = :idPrescription"
            + ";"
        )

        db.session.execute(query, {"idPrescription": p.id})

    # refresh cache
    if feature_service.has_feature_flag(flag=AppFeatureFlagEnum.REDIS_CACHE):
        _refresh_clinical_notes_stats(
            admission_number=p.admissionNumber, user_context=user_context
        )
        _refresh_exams(id_patient=p.idPatient, user_context=user_context)


def get_query_prescriptions_by_agg(
    agg_prescription: Prescription, is_cpoe=False, only_id=False
):
    is_pmc = memory_service.has_feature_nouser(FeatureEnum.PRIMARY_CARE.value)

    q = (
        db.session.query(Prescription.id if only_id else Prescription)
        .filter(Prescription.admissionNumber == agg_prescription.admissionNumber)
        .filter(Prescription.concilia == None)
        .filter(Prescription.agg == None)
    )

    q = prescriptionutils.get_period_filter(
        q, Prescription, agg_prescription.date, is_pmc, is_cpoe
    )

    if not is_cpoe:
        q = q.filter(Prescription.idSegment == agg_prescription.idSegment)
    else:
        # discard all suspended
        active_count = (
            db.session.query(func.count().label("count"))
            .filter(PrescriptionDrug.idPrescription == Prescription.id)
            .filter(
                or_(
                    PrescriptionDrug.suspendedDate == None,
                    func.date(PrescriptionDrug.suspendedDate) >= agg_prescription.date,
                )
            )
            .as_scalar()
        )
        q = q.filter(active_count > 0)

    return q


@has_permission(Permission.WRITE_PRESCRIPTION)
def update_prescription_data(id_prescription: int, data: dict, user_context: User):
    p = (
        db.session.query(Prescription)
        .filter(Prescription.id == id_prescription)
        .first()
    )
    if p is None:
        raise ValidationError(
            "Prescrição inexistente.",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    if not data_authorization_service.has_segment_authorization(
        id_segment=p.idSegment, user=user_context
    ):
        return {
            "status": "error",
            "message": "Usuário não autorizado neste segmento",
        }, status.HTTP_401_UNAUTHORIZED

    if "notes" in data.keys():
        p.notes = data.get("notes", None)
        p.notes_at = datetime.today()

        audit = PrescriptionAudit()
        audit.auditType = PrescriptionAuditTypeEnum.UPSERT_CLINICAL_NOTES.value
        audit.admissionNumber = p.admissionNumber
        audit.idPrescription = p.id
        audit.prescriptionDate = p.date
        audit.idDepartment = p.idDepartment
        audit.idSegment = p.idSegment
        audit.totalItens = 0
        audit.agg = p.agg
        audit.concilia = p.concilia
        audit.bed = p.bed
        audit.extra = {"text": data.get("notes", None)}
        audit.createdAt = datetime.today()
        audit.createdBy = user_context.id
        db.session.add(audit)

    if "concilia" in data.keys():
        concilia = data.get("concilia", "s")
        p.concilia = str(concilia)[:1]

    p.user = user_context.id

    return p


def _refresh_clinical_notes_stats(admission_number: int, user_context: User):
    def _add_cache(key: str, data: dict, expire_in: int):
        if data.get("data", None) != None:
            cache_data = {
                "dtevolucao": data.get("date", None),
                "fkevolucao": data.get("id", None),
                "lista": [data.get("data", None)],
            }

            redis_client.json().set(key, "$", cache_data)
            redis_client.expire(key, expire_in)

    # signs (expires in 60 days)
    signs = clinical_notes_queries_service.get_signs(
        admission_number=admission_number, user_context=user_context, cache=False
    )
    key = f"{user_context.schema}:{admission_number}:sinais"
    _add_cache(key=key, data=signs, expire_in=5184000)

    # infos (expires in 60 days)
    infos = clinical_notes_queries_service.get_infos(
        admission_number=admission_number, user_context=user_context, cache=False
    )
    key = f"{user_context.schema}:{admission_number}:dados"
    _add_cache(key=key, data=infos, expire_in=5184000)


def _refresh_exams(id_patient: int, user_context: User):
    exams = exams_service.get_exams_current_results(
        id_patient=id_patient,
        add_previous_exams=True,
        cache=False,
        schema=user_context.schema,
        lower_key=False,
    )

    key = f"{user_context.schema}:{id_patient}:exames"
    for type_exam, exam in exams.items():
        redis_client.hset(key, type_exam, json.dumps(exam))


def _update_patient_weight(admission_number: int, user_context: User):
    patient = (
        db.session.query(Patient)
        .filter(Patient.admissionNumber == admission_number)
        .first()
    )
    if patient and not patient.weight and not patient.weightDate:
        # try to update patient weight based on previous admissions
        patient_previous_data = patient_service.get_patient_weight(patient.idPatient)
        if patient_previous_data != None:
            patient.weight = (
                patient_previous_data.weight if patient_previous_data.weight else None
            )
            patient.weightDate = (
                patient_previous_data.weightDate
                if patient_previous_data.weightDate
                else None
            )
            db.session.flush()

            audit = PatientAudit()
            audit.admissionNumber = patient.admissionNumber
            audit.auditType = PatientAuditTypeEnum.UPSERT.value
            audit.extra = {
                "weight": patient.weight,
                "weightDate": dateutils.to_iso(patient.weightDate),
                "source": "recalculate_prescription",
            }
            audit.createdAt = datetime.today()
            audit.createdBy = user_context.id
            db.session.add(audit)
