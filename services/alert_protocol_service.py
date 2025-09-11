"""Service: protocol alerts"""

from datetime import datetime

from models.main import User
from models.prescription import Prescription, Patient
from models.enums import ProtocolTypeEnum
from services import feature_service
from utils.alert_protocol import AlertProtocol
from decorators.has_permission_decorator import has_permission, Permission
from repository import protocol_repository


@has_permission(Permission.READ_PRESCRIPTION)
def find_protocols(
    drug_list: dict,
    exams: dict,
    prescription: Prescription,
    patient: Patient,
    cn_stats: dict,
    user_context: User = None,
):
    """Gets all prescription protocols and test against a prescription"""

    protocol_types: list[ProtocolTypeEnum] = [ProtocolTypeEnum.PRESCRIPTION_ALL]
    if prescription.agg:
        protocol_types.append(ProtocolTypeEnum.PRESCRIPTION_AGG)
    else:
        protocol_types.append(ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL)

    protocols = protocol_repository.get_active_protocols(
        schema=user_context.schema, protocol_type_list=protocol_types
    )

    if not protocols:
        return {}

    results = {}
    summary = set()

    drugs_by_expire_date = _split_drugs_by_date(
        drug_list=drug_list, prescription=prescription
    )

    # protocols must be applied inside each date group
    for expire_date, drugs in drugs_by_expire_date.items():
        results[expire_date] = []
        alert_protocol = AlertProtocol(
            drugs=drugs,
            exams=exams,
            prescription=prescription,
            patient=patient,
            cn_stats=cn_stats,
        )

        for protocol in protocols:
            alert = alert_protocol.get_protocol_alerts(protocol=protocol.config)
            if alert:
                alert["id"] = protocol.id
                results[expire_date].append(alert)
                summary.add(protocol.id)

    results["summary"] = list(summary)

    return results


def _split_drugs_by_date(drug_list: dict, prescription: Prescription):
    expire_dates = {}

    # TODO: CPOE REMOVE
    if feature_service.is_cpoe() or not prescription.agg:
        expire_dates[prescription.date.isoformat()[:10]] = drug_list

        return expire_dates

    for item in drug_list:
        prescription_date = item[13].date()
        prescription_expire_date: datetime = (
            item[10].date() if item[10] else prescription_date
        )
        group_key = prescription_expire_date.isoformat()[:10]

        if expire_dates.get(group_key, None):
            expire_dates[group_key].append(item)
        else:
            expire_dates[group_key] = [item]

    return expire_dates
