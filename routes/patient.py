import os, copy
from flask import Blueprint, request
from markupsafe import escape as escape_html
from flask_jwt_extended import (
    jwt_required,
    get_jwt_identity,
)

from utils import status
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from .utils import *
from services import patient_service, exams_service
from exception.validation_error import ValidationError

app_pat = Blueprint("app_pat", __name__)


def historyExam(typeExam, examsList, segExam):
    results = []
    for e in examsList:
        if e.typeExam == typeExam:
            item = formatExam(e, e.typeExam.lower(), segExam)
            del item["ref"]
            results.append(item)
    return results


def historyCalc(typeExam, examsList, patient):
    results = []
    for e in examsList:
        item = {}
        if typeExam == "mdrd":
            item = mdrd_calc(
                e["value"], patient.birthdate, patient.gender, patient.skinColor
            )
        elif typeExam == "cg":
            item = cg_calc(
                e["value"], patient.birthdate, patient.gender, patient.weight
            )
        elif typeExam == "ckd":
            item = ckd_calc(
                e["value"],
                patient.birthdate,
                patient.gender,
                patient.skinColor,
                patient.height,
                patient.weight,
            )
        elif typeExam == "ckd21":
            item = ckd_calc_21(e["value"], patient.birthdate, patient.gender)
        elif typeExam == "swrtz2":
            item = schwartz2_calc(e["value"], patient.height)
        elif typeExam == "swrtz1":
            item = schwartz1_calc(
                e["value"],
                patient.birthdate,
                patient.gender,
                patient.height,
            )

        item["date"] = e["date"]
        results.append(item)
    return results


@app_pat.route("/exams/<int:admissionNumber>", methods=["GET"])
@jwt_required()
def getExamsbyAdmission(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    idSegment = request.args.get("idSegment", 1)
    patient = Patient.findByAdmission(admissionNumber)
    if patient is None:
        return {
            "status": "error",
            "message": "Paciente Inexistente!",
        }, status.HTTP_400_BAD_REQUEST

    examsList = Exams.findByPatient(patient.idPatient)
    segExam = SegmentExam.refDict(idSegment)

    perc = {
        "h_conleuc": {
            "total": 1,
            "relation": [
                "h_conlinfoc",
                "h_conmono",
                "h_coneos",
                "h_conbaso",
                "h_consegm",
            ],
        }
    }

    bufferList = {}
    typeExams = []
    for e in examsList:
        if not e.typeExam.lower() in typeExams and e.typeExam.lower() in segExam:
            key = e.typeExam.lower()
            item = formatExam(e, key, segExam)
            item["name"] = segExam[key].name
            item["perc"] = None
            item["history"] = historyExam(e.typeExam, examsList, segExam)
            item["text"] = False
            bufferList[key] = item
            typeExams.append(key)
            if key in perc:
                perc[key]["total"] = float(e.value)

            if segExam[key].initials.lower() == "creatinina":
                for keyCalc in ["mdrd", "ckd", "ckd21", "cg", "swrtz2", "swrtz1"]:
                    if keyCalc in segExam and patient:
                        if keyCalc == "mdrd":
                            itemCalc = mdrd_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.skinColor,
                            )
                        elif keyCalc == "cg":
                            itemCalc = cg_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.weight,
                            )
                        elif keyCalc == "ckd":
                            itemCalc = ckd_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.skinColor,
                                patient.height,
                                patient.weight,
                            )
                        elif keyCalc == "ckd21":
                            itemCalc = ckd_calc_21(
                                e.value, patient.birthdate, patient.gender
                            )
                        elif keyCalc == "swrtz2":
                            itemCalc = schwartz2_calc(e.value, patient.height)
                        elif keyCalc == "swrtz1":
                            itemCalc = schwartz1_calc(
                                e.value,
                                patient.birthdate,
                                patient.gender,
                                patient.height,
                            )

                        if itemCalc["value"]:
                            itemCalc["name"] = segExam[keyCalc].name
                            itemCalc["perc"] = None
                            itemCalc["date"] = item["date"]
                            itemCalc["history"] = historyCalc(
                                keyCalc, item["history"], patient
                            )
                            bufferList[keyCalc] = itemCalc

    for p in perc:
        total = perc[p]["total"]
        for r in perc[p]["relation"]:
            if r in bufferList:
                val = bufferList[r]["value"]
                bufferList[r]["perc"] = round((val * 100) / total, 1)

    results = copy.deepcopy(segExam)
    for e in segExam:
        if e in bufferList:
            results[e] = bufferList[e]
        else:
            del results[e]

    examsText = exams_service.get_textual_exams(id_patient=patient.idPatient)
    resultsText = {}
    for e in examsText:
        slugExam = slugify(e.prescriber)
        if not slugExam in resultsText.keys():
            resultsText[slugExam] = {
                "name": e.prescriber,
                "text": True,
                "date": e.date.isoformat(),
                "ref": e.text[:20],
                "history": [],
            }

        item = {}
        item["date"] = e.date.isoformat()
        item["value"] = e.text
        resultsText[slugExam]["history"].append(item)
        resultsText[slugExam]["date"] = e.date.isoformat()

    return {
        "status": "success",
        "data": dict(results, **resultsText),
    }, status.HTTP_200_OK


@app_pat.route("/patient/<int:admissionNumber>", methods=["POST"])
@jwt_required()
def setPatientData(admissionNumber):
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)
    os.environ["TZ"] = "America/Sao_Paulo"

    try:
        result = patient_service.save_patient(
            request_data=request.get_json(), admission_number=admissionNumber, user=user
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

    return tryCommit(db, escape_html(result.admissionNumber))


@app_pat.route("/patient", methods=["GET"])
@jwt_required()
def list_patients():
    user = User.find(get_jwt_identity())
    dbSession.setSchema(user.schema)

    id_segment = request.args.get("idSegment", None)
    id_department_list = request.args.getlist("idDepartment[]", None)
    next_appointment_start_date = request.args.get("nextAppointmentStartDate", None)
    next_appointment_end_date = request.args.get("nextAppointmentEndDate", None)
    appointment = request.args.get("appointment", None)
    scheduled_by_list = request.args.getlist("scheduledBy[]", None)
    attended_by_list = request.args.getlist("attendedBy[]", None)

    try:
        patients = patient_service.get_patients(
            id_segment=id_segment,
            id_department_list=id_department_list,
            next_appointment_start_date=next_appointment_start_date,
            next_appointment_end_date=next_appointment_end_date,
            scheduled_by_list=scheduled_by_list,
            attended_by_list=attended_by_list,
            appointment=appointment,
        )
    except ValidationError as e:
        return {"status": "error", "message": str(e), "code": e.code}, e.httpStatus

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

    return {
        "status": "success",
        "data": list,
    }, status.HTTP_200_OK
