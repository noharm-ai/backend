"""Service: prescription prioritization operations"""

from decorators.has_permission_decorator import Permission, has_permission
from models.prescription import Patient
from models.requests.prioritization_request import PrioritizationRequest
from repository import prioritization_repository
from services import prescription_service
from utils import numberutils, prescriptionutils


@has_permission(Permission.READ_PRESCRIPTION)
def get_prioritization_list(request: PrioritizationRequest):
    """List prescription prioritization results"""
    prioritization_results = prioritization_repository.get_prioritization_list(request)

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
