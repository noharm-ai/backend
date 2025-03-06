"""Service: protocol alerts"""

from datetime import datetime

from models.main import db
from models.prescription import Prescription
from models.appendix import Protocol
from models.enums import ProtocolTypeEnum
from services import feature_service
from utils.alert_protocol import AlertProtocol


def find_protocols(drug_list: dict, exams: dict, prescription: Prescription):
    """Gets all protocols and test against a prescription"""

    protocols = (
        db.session.query(Protocol)
        .filter(
            Protocol.protocol_type == ProtocolTypeEnum.PRESCRIPTION.value,
            Protocol.active == True,
        )
        .all()
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
        alert_protocol = AlertProtocol(drugs=drugs, exams=exams)

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

    if feature_service.is_cpoe() or not prescription.agg:
        expire_dates[prescription.date.date().isoformat()[:10]] = drug_list

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
