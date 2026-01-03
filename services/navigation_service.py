"""Service for navigation-related operations."""

import json

import boto3

from config import Config
from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.main import User
from models.requests.navigation_request import NavCopyPatientRequest
from repository import prescription_view_repository
from services import prescription_agg_service, segment_service
from utils import status


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

    lambda_client = boto3.client("lambda", region_name=Config.NIFI_SQS_QUEUE_REGION)
    response = lambda_client.invoke(
        FunctionName=Config.BACKEND_FUNCTION_NAME,
        InvocationType="RequestResponse",
        Payload=json.dumps(
            {
                "command": "lambda_navigation.copy_patient_prescription",
                "from_schema": user_context.schema,
                "to_schema": "--",
                "from_admission_number": agg_prescription.admissionNumber,
                "drug_list": copy_drug_list,
            }
        ),
    )

    return json.loads(response["Payload"].read().decode("utf-8"))
