"""Service: protocol alerts"""

from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from models.enums import ProtocolTypeEnum
from models.main import User
from models.prescription import Patient, Prescription
from repository import protocol_repository
from services import segment_service
from utils.alert_protocol import AlertProtocol, ProtocolExtraInfo


@has_permission(Permission.READ_PRESCRIPTION)
def find_protocols(
    drug_list: dict,
    exams: dict,
    prescription: Prescription,
    patient: Patient,
    cn_stats: dict,
    protocol_extra_info: ProtocolExtraInfo,
    user_context: User = None,
):
    """Gets all prescription protocols and test against a prescription"""

    protocol_types: list[ProtocolTypeEnum] = [
        ProtocolTypeEnum.PRESCRIPTION_ALL,
        ProtocolTypeEnum.PRESCRIPTION_ITEM,
    ]
    if prescription.agg:
        protocol_types.append(ProtocolTypeEnum.PRESCRIPTION_AGG)
    else:
        protocol_types.append(ProtocolTypeEnum.PRESCRIPTION_INDIVIDUAL)

    protocols = protocol_repository.get_active_protocols(
        schema=user_context.schema, protocol_type_list=protocol_types
    )

    if not protocols:
        return {}

    results = {"items": []}
    summary = set()

    drugs_by_expire_date = split_drugs_by_date(
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
            protocol_extra_info=protocol_extra_info,
        )

        for protocol in protocols:
            alert = alert_protocol.get_protocol_alerts(protocol=protocol.config)
            if alert:
                alert["id"] = protocol.id
                if protocol.protocol_type == ProtocolTypeEnum.PRESCRIPTION_ITEM.value:
                    results["items"].append(alert)
                    # an item alert belongs to the items that matched it, so the
                    # summary decision looks at those items alone
                    summary_drugs = get_related_drugs(drugs=drugs, alert=alert)
                else:
                    results[expire_date].append(alert)
                    summary_drugs = drugs

                if counts_to_summary(
                    config=protocol.config,
                    drugs=summary_drugs,
                    prescription=prescription,
                ):
                    summary.add(protocol.id)

    results["summary"] = list(summary)
    
    return results


def counts_to_summary(config: dict, drugs: list, prescription: Prescription) -> bool:
    """Tells if an alert raised on these drugs must be counted in the summary.

    Every protocol is tested against every date group, but a protocol flagged
    with onlyLatestExpireDate only reaches the summary (which feeds the
    prescription alert count) when it fires on drugs prescribed on the current
    prescription date. Each drug row carries the date of the prescription it
    came from, and an aggregated prescription also carries drugs prescribed on
    previous days."""

    if not is_summary_restricted(config=config):
        return True

    prescription_date = prescription.date.date()

    return any(d[13] is not None and d[13].date() == prescription_date for d in drugs)


def get_related_drugs(drugs: list, alert: dict) -> list:
    """Drug rows an item alert points at.

    An item protocol always carries a combination variable, so its alert reports
    the items that matched it. When it reports none (a trigger activated by the
    absence of a match), the alert cannot be attributed to an item and the whole
    group answers for it."""

    related_items = alert.get("related_items") or []

    if not related_items:
        return drugs

    return [d for d in drugs if d[0].id in related_items]


def is_summary_restricted(config: dict) -> bool:
    """Tells if a protocol config asks to reach the summary only when it fires
    on drugs of the current prescription date. Stored as onlyLatestExpireDate;
    configs saved before the field existed do not have the key and always reach
    the summary."""

    if not config:
        return False

    return bool(config.get("onlyLatestExpireDate", False))


def split_drugs_by_date(drug_list: dict, prescription: Prescription):
    """Groups prescription drugs by expire date (protocols run per date group)"""
    expire_dates = {}
    is_cpoe = segment_service.is_cpoe(id_segment=prescription.idSegment)

    if is_cpoe or not prescription.agg:
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
