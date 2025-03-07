from datetime import datetime
from sqlalchemy import desc, func, text, asc
from sqlalchemy.orm import undefer
from sqlalchemy.dialects.postgresql import INTERVAL
from typing import List

from models.main import db, User, Allergy, Substance, Drug
from models.prescription import (
    Prescription,
    Patient,
    PatientAudit,
)
from models.notes import ClinicalNotes
from models.appendix import Tag
from models.enums import PatientAuditTypeEnum, FeatureEnum, TagTypeEnum
from utils.dateutils import to_iso
from services import memory_service
from services.admin import admin_tag_service
from decorators.has_permission_decorator import has_permission, Permission
from exception.validation_error import ValidationError
from utils import status


@has_permission(Permission.READ_PRESCRIPTION)
def get_patients(
    id_segment,
    id_department_list,
    next_appointment_start_date,
    next_appointment_end_date,
    scheduled_by_list,
    attended_by_list,
    appointment=None,
):
    if not memory_service.has_feature(FeatureEnum.PRIMARY_CARE.value):
        raise ValidationError(
            "Funcionalidade não está habilitada",
            "errors.invalidRequest",
            status.HTTP_400_BAD_REQUEST,
        )

    Pmax = db.aliased(Prescription)

    sq_appointment = (
        db.session.query(func.max(func.date(ClinicalNotes.date)))
        .select_from(ClinicalNotes)
        .filter(ClinicalNotes.admissionNumber == Prescription.admissionNumber)
        .filter(ClinicalNotes.position == "Agendamento")
        .label("appointment")
    )

    query = (
        db.session.query(Patient, Prescription, sq_appointment)
        .select_from(Patient)
        .join(
            Prescription,
            Prescription.id
            == db.session.query(func.max(Pmax.id))
            .select_from(Pmax)
            .filter(Pmax.idPatient == Patient.idPatient)
            .filter(Pmax.admissionNumber == Patient.admissionNumber)
            .filter(Pmax.idHospital == Patient.idHospital)
            .filter(Pmax.agg == True),
        )
        .order_by(desc("appointment"))
        .options(undefer(Patient.observation))
    )

    if id_segment:
        query = query.filter(Prescription.idSegment == id_segment)

    if id_department_list:
        query = query.filter(Prescription.idDepartment.in_(id_department_list))

    if next_appointment_start_date:
        query = query.filter(sq_appointment >= next_appointment_start_date)

    if next_appointment_end_date:
        query = query.filter(sq_appointment <= next_appointment_end_date)

    if appointment == "scheduled":
        query = query.filter(sq_appointment != None)

    if appointment == "not-scheduled":
        query = query.filter(sq_appointment == None)

    if scheduled_by_list:
        scheduled_by_query = (
            db.session.query(func.count())
            .select_from(ClinicalNotes)
            .filter(ClinicalNotes.admissionNumber == Prescription.admissionNumber)
            .filter(ClinicalNotes.position == "Agendamento")
            .filter(ClinicalNotes.user.in_(scheduled_by_list))
        )

        query = query.filter(scheduled_by_query.exists())

    if attended_by_list:
        attended_by_query = (
            db.session.query(func.count())
            .select_from(ClinicalNotes)
            .filter(ClinicalNotes.admissionNumber == Prescription.admissionNumber)
            .filter(ClinicalNotes.position != "Agendamento")
            .filter(ClinicalNotes.user.in_(attended_by_list))
        )

        query = query.filter(attended_by_query.exists())

    return query.limit(1500).all()


def get_patient_allergies(id_patient):
    return (
        db.session.query(
            Allergy.createdAt, func.coalesce(Substance.name, Allergy.drugName)
        )
        .distinct(func.coalesce(Substance.name, Allergy.drugName))
        .outerjoin(Drug, Allergy.idDrug == Drug.id)
        .outerjoin(Substance, Drug.sctid == Substance.id)
        .filter(Allergy.idPatient == id_patient)
        .filter(Allergy.active == True)
        .order_by(func.coalesce(Substance.name, Allergy.drugName))
        .limit(100)
        .all()
    )


def get_patient_weight(id_patient):
    return (
        db.session.query(Patient.weight, Patient.weightDate, Patient.height)
        .filter(Patient.idPatient == id_patient)
        .filter(Patient.weight != None)
        .filter(Patient.weightDate > func.now() - func.cast("1 month", INTERVAL))
        .order_by(desc(Patient.weightDate))
        .first()
    )


@has_permission(Permission.WRITE_PRESCRIPTION, Permission.ADMIN_PATIENT)
def save_patient(
    request_data: dict,
    admission_number: int,
    user_context: User,
    user_permissions: List[Permission],
):
    # TODO: refactor
    p = Patient.findByAdmission(admission_number)
    if p is None:
        first_prescription = (
            db.session.query(Prescription)
            .filter(Prescription.admissionNumber == admission_number)
            .filter(Prescription.agg == None)
            .filter(Prescription.concilia == None)
            .filter(Prescription.idSegment != None)
            .order_by(asc(Prescription.date))
            .first()
        )

        if first_prescription == None:
            raise ValidationError(
                "Paciente inexistente",
                "errors.invalidParams",
                status.HTTP_400_BAD_REQUEST,
            )

        p = Patient()
        p.admissionNumber = admission_number
        p.admissionDate = first_prescription.date
        p.idHospital = first_prescription.idHospital
        p.idPatient = first_prescription.idPatient
        db.session.add(p)

    update_prescription = False
    if Permission.WRITE_PRESCRIPTION in user_permissions:
        if "weight" in request_data.keys():
            weight = request_data.get("weight", None)

            if weight != p.weight:
                p.weightDate = datetime.today()
                p.weight = weight
                update_prescription = True

        alertExpire = request_data.get("alertExpire", None)
        if alertExpire and alertExpire != p.alertExpire:
            p.alert = request_data.get("alert", None)
            p.alertExpire = alertExpire
            p.alertDate = datetime.today()
            p.alertBy = user_context.id

        if "height" in request_data.keys():
            p.height = request_data.get("height", None)
        if "dialysis" in request_data.keys():
            p.dialysis = request_data.get("dialysis", None)
        if "lactating" in request_data.keys():
            p.lactating = request_data.get("lactating", None)
        if "pregnant" in request_data.keys():
            p.pregnant = request_data.get("pregnant", None)
        if "observation" in request_data.keys():
            p.observation = request_data.get("observation", None)
        if "skinColor" in request_data.keys():
            p.skinColor = request_data.get("skinColor", None)
        if "gender" in request_data.keys():
            p.gender = request_data.get("gender", None)
        if "birthdate" in request_data.keys():
            p.birthdate = request_data.get("birthdate", None)
        if "tags" in request_data.keys():
            tags = request_data.get("tags", None)

            MAX_TAGS = 10
            if tags and len(tags) > MAX_TAGS:
                raise ValidationError(
                    f"Número máximo de tags ultrapassado ({MAX_TAGS})",
                    "errors.businessRules",
                    status.HTTP_400_BAD_REQUEST,
                )

            p.tags = _get_tags(tags=tags, user_context=user_context)

    if Permission.ADMIN_PATIENT in user_permissions:
        if "dischargeDate" in request_data.keys():
            p.dischargeDate = request_data.get("dischargeDate", None)

    p.update = datetime.today()
    p.user = user_context.id

    _audit(patient=p, audit_type=PatientAuditTypeEnum.UPSERT, user=user_context)

    return {
        "updatePrescription": update_prescription,
        "admissionNumber": int(admission_number),
    }


def _audit(patient: Patient, audit_type: PatientAuditTypeEnum, user: User):
    audit = PatientAudit()
    audit.admissionNumber = patient.admissionNumber
    audit.auditType = audit_type.value
    audit.extra = _to_dict(patient=patient)
    audit.createdAt = datetime.today()
    audit.createdBy = user.id

    db.session.add(audit)


def _to_dict(patient: Patient):
    return {
        "idPatient": patient.idPatient,
        "admissionDate": to_iso(patient.admissionDate),
        "birthdate": to_iso(patient.birthdate),
        "gender": patient.gender,
        "weight": patient.weight,
        "height": patient.height,
        "observation": patient.observation,
        "skinColor": patient.skinColor,
        "dischargeReason": patient.dischargeReason,
        "dischargeDate": to_iso(patient.dischargeDate),
        "dialysis": patient.dialysis,
        "lactating": patient.lactating,
        "pregnant": patient.pregnant,
        "tags": patient.tags,
    }


def _get_tags(tags: list[str], user_context: User):
    if not tags:
        return None

    tags_uppercase = [t.upper() for t in tags]

    MAX_TAGS = 10
    if len(tags_uppercase) > MAX_TAGS:
        raise ValidationError(
            f"Limite de marcadores atingido ({MAX_TAGS})",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    current_tags = (
        db.session.query(Tag)
        .filter(Tag.name.in_(tags_uppercase), Tag.tag_type == TagTypeEnum.PATIENT.value)
        .all()
    )

    found_tags = []
    if current_tags:
        found_tags = [t.name for t in current_tags]

    MAX_CHARS = admin_tag_service.MAX_TAG_CHARS
    for tag in tags_uppercase:
        if tag not in found_tags:
            if len(tag) > MAX_CHARS:
                raise ValidationError(
                    f"Marcador: Limite de caracteres atingido ({MAX_CHARS})",
                    "errors.businessRules",
                    status.HTTP_400_BAD_REQUEST,
                )

            new_tag = Tag()
            new_tag.name = tag
            new_tag.tag_type = TagTypeEnum.PATIENT.value
            new_tag.active = True
            new_tag.created_at = datetime.today()
            new_tag.created_by = user_context.id

            db.session.add(new_tag)

    return tags_uppercase
