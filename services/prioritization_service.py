"""Service: prescription prioritization operations"""

from datetime import datetime

from decorators.has_permission_decorator import Permission, has_permission
from models.enums import FeatureEnum
from models.prescription import Patient
from models.requests.prioritization_request import PrioritizationRequest
from repository import prioritization_repository
from services import feature_service, prescription_service
from utils import numberutils, prescriptionutils
from utils.tagutils import filter_nav_tags


def _get_first_administration_hour(intervals):
    """Extract the first administration hour (0-23) from a sorted intervals list, or None if unavailable/invalid"""
    if not intervals:
        return None

    first_interval = intervals[0]
    if not isinstance(first_interval, str) or not first_interval.isdigit():
        return None

    hour = int(first_interval)
    if hour < 0 or hour > 23:
        return None

    return hour


def _parse_prescription_date(value) -> datetime | None:
    """Parse an ISO prescription date stored in features; None when invalid"""
    if not isinstance(value, str) or not value:
        return None

    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None

    # features store naive local (America/Sao_Paulo) datetimes; drop tzinfo
    # so the comparison with datetime.now() never mixes aware and naive values
    return parsed.replace(tzinfo=None)


def _get_prescription_dates_summary(prescription_dates, now: datetime = None):
    """Summarize the inner prescription dates of an agg prescription.

    Returns the sorted list of valid ISO dates, the most recent one
    (lastPrescriptionDate) and the first one at or after `now`
    (nextPrescriptionDate), which is the next prescription to be reviewed
    relative to the current date.
    """
    if now is None:
        now = datetime.now()

    parsed_dates = []
    for value in prescription_dates or []:
        parsed = _parse_prescription_date(value)
        if parsed is not None:
            parsed_dates.append(parsed)

    parsed_dates = sorted(set(parsed_dates))

    next_date = None
    for d in parsed_dates:
        if d >= now:
            next_date = d
            break

    return {
        "prescriptionDates": [d.isoformat() for d in parsed_dates],
        "lastPrescriptionDate": (
            parsed_dates[-1].isoformat() if parsed_dates else None
        ),
        "nextPrescriptionDate": next_date.isoformat() if next_date else None,
    }


@has_permission(Permission.READ_PRESCRIPTION)
def get_prioritization_list(request: PrioritizationRequest):
    """List prescription prioritization results"""
    prioritization_results, total_records = (
        prioritization_repository.get_prioritization_list(
            request=request, run_count=False
        )
    )

    results = []
    hide_names = feature_service.has_user_feature(FeatureEnum.HIDE_NAMES)
    now = datetime.now()
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

            features["firstAdministrationHour"] = _get_first_administration_hour(
                p[0].features.get("intervals", [])
            )

            features.update(
                _get_prescription_dates_summary(
                    p[0].features.get("prescriptionDates", []), now=now
                )
            )

        else:
            features["processed"] = False
            features["globalScore"] = 0
            features["scoreVariation"] = 0
            features["class"] = "blue"
            features["firstAdministrationHour"] = None
            features["prescriptionDates"] = []
            features["lastPrescriptionDate"] = None
            features["nextPrescriptionDate"] = None

        # p.observation is truncated to 301 chars in SQL (func.left); a length
        # over 300 means the original text overflows and gets an ellipsis
        observation = None
        if p.observation:
            observation = (
                p.observation[:300] + "..." if len(p.observation) > 300 else p.observation
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
                    "lengthStay": prescriptionutils.lenghStay(
                        patient.admissionDate, patient.dischargeDate
                    ),
                    "dischargeDate": (
                        patient.dischargeDate.isoformat()
                        if patient.dischargeDate
                        else None
                    ),
                    "dischargeReason": patient.dischargeReason,
                    "date": p[0].date.isoformat(),
                    "department": "***" if hide_names else str(p[2]),
                    "insurance": p[0].insurance if not hide_names else "***",
                    "bed": p[0].bed,
                    "status": p[0].status,
                    "isBeingEvaluated": prescription_service.is_being_evaluated(
                        p[0].features
                    ),
                    "reviewType": p[0].reviewType,
                    "observation": observation,
                    "totalRecords": total_records,
                    "agg": p[0].agg,
                    "prescriptionAggId": prescriptionutils.gen_agg_id(
                        admission_number=p[0].admissionNumber,
                        id_segment=p[0].idSegment,
                        pdate=p[0].date,
                    ),
                    "patientTags": filter_nav_tags(patient.tags),
                    "city": patient.city,
                    "id_icd": patient.id_icd,
                },
            )
        )

    return results
