"""Service for navigation-related operations."""

import json

import boto3

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import User, db
from models.requests.navigation_request import NavCopyPatientRequest
from repository import prescription_view_repository
from services import prescription_agg_service, segment_service
from utils import cryptutils, lambdautils, logger, status, stringutils


@has_permission(Permission.NAV_COPY_PATIENT)
def copy_patient(request_data: NavCopyPatientRequest, user_context: User):
    agg_prescription = prescription_agg_service.get_last_agg_prescription(
        admission_number=request_data.admission_number
    )

    if not agg_prescription:
        raise ValidationError(
            "Não há prescrição para este atendimento",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    user = db.session.query(User).filter(User.id == user_context.id).first()

    if not user:
        raise ValidationError(
            "Usuário inválido",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    is_cpoe = segment_service.is_cpoe(id_segment=agg_prescription.idSegment)
    ignored_segments = segment_service.get_ignored_segments(is_cpoe_flag=is_cpoe)

    drug_list = prescription_view_repository.find_drugs_by_prescription(
        idPrescription=agg_prescription.id,
        admissionNumber=agg_prescription.admissionNumber,
        aggDate=agg_prescription.date,
        idSegment=agg_prescription.idSegment,
        is_cpoe=is_cpoe,
        is_pmc=False,
        ignore_segments=ignored_segments,
    )

    copy_drug_list = []

    if is_cpoe:
        for drug in drug_list:
            copy_drug_list.append(drug.PrescriptionDrug.id)
    else:
        expire_dates = {}
        last_group_key = None
        for item in drug_list:
            prescription_date = item[13].date()
            prescription_expire_date = (
                item[10].date() if item[10] else prescription_date
            )
            group_key = prescription_expire_date.isoformat()[:10]
            if last_group_key is None or last_group_key < group_key:
                last_group_key = group_key

            if expire_dates.get(group_key, None):
                expire_dates[group_key].append(item)
            else:
                expire_dates[group_key] = [item]

        if last_group_key:
            for drug in expire_dates[last_group_key]:
                copy_drug_list.append(drug.PrescriptionDrug.id)

    encrypted_patient_name = cryptutils.encrypt_data(
        stringutils.truncate(request_data.name, 250)
    )
    encrypted_patient_phone = cryptutils.encrypt_data(
        stringutils.truncate(request_data.phone, 250)
    )
    encrypted_clinical_notes = _encrypt_clinical_notes(request_data.clinical_notes)

    payload = {
        "command": "lambda_navigation.copy_patient_prescription",
        "from_schema": user_context.schema,
        "to_schema": user.schema,
        "from_admission_number": agg_prescription.admissionNumber,
        "drug_list": copy_drug_list,
        "clinical_notes": encrypted_clinical_notes,
        "patient_name": encrypted_patient_name if encrypted_patient_name else None,
        "patient_phone": encrypted_patient_phone if encrypted_patient_phone else None,
        "encrypted": True,
    }

    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(payload),
    )

    response_json = lambdautils.response_to_json(response)

    if "error" in response_json:
        logger.backend_logger.error(
            "Error copying patient prescription: %s", response_json["message"]
        )

        raise ValidationError(
            "Ocorreu um erro ao copiar a prescrição do paciente. Consulte o administrador do sistema.",
            "errors.businessRules",
            status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    return response_json


def _encrypt_clinical_notes(clinical_notes: dict) -> dict:
    """
    Process clinical notes dictionary: truncate and encrypt each text value.

    Args:
        clinical_notes: Dictionary with clinical notes where each key has a text value

    Returns:
        Dictionary with truncated and encrypted text values
    """
    if not clinical_notes or not isinstance(clinical_notes, dict):
        return {}

    processed_notes = {}

    for key, value in clinical_notes.items():
        if value and isinstance(value, str):
            # Truncate to 5000 characters
            truncated_text = stringutils.truncate(
                value, 5000, ellipsis="... [truncado]", word_boundary=True
            )
            # Encrypt the truncated text
            encrypted_text = cryptutils.encrypt_data(truncated_text)
            processed_notes[key] = encrypted_text if encrypted_text else None
        else:
            # Keep non-string values as-is (or set to None)
            processed_notes[key] = None

    return processed_notes if processed_notes else {}
