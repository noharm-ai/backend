from flask import Blueprint, request

from decorators.api_endpoint_decorator import api_endpoint
from services import exams_service, patient_service

app_pat = Blueprint("app_pat", __name__)


@app_pat.route("/exams/<int:admissionNumber>", methods=["GET"])
@api_endpoint()
def getExamsbyAdmission(admissionNumber):
    return exams_service.get_exams_by_admission(
        admission_number=admissionNumber, id_segment=request.args.get("idSegment", 1)
    )


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
    id_segment = request.args.get("idSegment", None)
    id_department_list = request.args.getlist("idDepartment[]", None)
    next_appointment_start_date = request.args.get("nextAppointmentStartDate", None)
    next_appointment_end_date = request.args.get("nextAppointmentEndDate", None)
    appointment = request.args.get("appointment", None)
    scheduled_by_list = request.args.getlist("scheduledBy[]", None)
    attended_by_list = request.args.getlist("attendedBy[]", None)

    patients = patient_service.get_patients(
        id_segment=id_segment,
        id_department_list=id_department_list,
        next_appointment_start_date=next_appointment_start_date,
        next_appointment_end_date=next_appointment_end_date,
        scheduled_by_list=scheduled_by_list,
        attended_by_list=attended_by_list,
        appointment=appointment,
    )

    list = []

    for p in patients:
        list.append(
            {
                "idPatient": p[0].idPatient,
                "admissionNumber": p[0].admissionNumber,
                "admissionDate": (
                    p[0].admissionDate.isoformat() if p[0].admissionDate else None
                ),
                "birthdate": p[0].birthdate.isoformat() if p[0].birthdate else None,
                "idPrescription": p[1].id,
                "observation": p[0].observation,
                "refDate": p[2].isoformat() if p[2] else None,
            }
        )

    return list
