from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from models.requests.patient_request import PatientListRequest
from services import patient_service

app_pat = Blueprint("app_pat", __name__)


@app_pat.route("/patient/<int:admissionNumber>", methods=["POST"])
@api_endpoint()
def setPatientData(admissionNumber):
    return patient_service.save_patient(
        request_data=request.get_json(), admission_number=admissionNumber
    )


@app_pat.route("/patient/<int:admission_number>/observation-history", methods=["GET"])
@api_endpoint()
def get_observation_history(admission_number: int):
    return patient_service.get_patient_observation_history(
        admission_number=admission_number
    )


@app_pat.route("/patient", methods=["GET"])
@api_endpoint()
def list_patients():
    """List patients (primary care) — legacy GET endpoint."""
    return patient_service.get_patients(
        request_data=PatientListRequest(
            idSegment=request.args.get("idSegment"),
            idDepartmentList=request.args.getlist("idDepartment[]") or None,
            nextAppointmentStartDate=request.args.get("nextAppointmentStartDate"),
            nextAppointmentEndDate=request.args.get("nextAppointmentEndDate"),
            appointment=request.args.get("appointment"),
            scheduledByList=request.args.getlist("scheduledBy[]") or None,
            attendedByList=request.args.getlist("attendedBy[]") or None,
            dischargeDateStart=request.args.get("dischargeDateStart"),
            dischargeDateEnd=request.args.get("dischargeDateEnd"),
        )
    )


@app_pat.route("/patient/list", methods=["POST"])
@api_endpoint()
def list_patients_post():
    """List patients (primary care) — POST endpoint with JSON body."""
    return patient_service.get_patients(
        request_data=PatientListRequest(**request.get_json())
    )
