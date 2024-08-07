import os, copy
from utils import status
from sqlalchemy import text
from models.main import *
from models.appendix import *
from models.segment import *
from models.prescription import *
from models.notes import ClinicalNotes
from flask import Blueprint, request
from markupsafe import escape as escape_html
from flask_jwt_extended import (
    create_access_token,
    create_refresh_token,
    jwt_required,
    get_jwt_identity,
)
from .utils import *
from datetime import datetime
from services import patient_service
from converter import patient_converter
from models.enums import RoleEnum

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

    examsText = ClinicalNotes.getExamsIfExists(admissionNumber)
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
    data = request.get_json()
    os.environ["TZ"] = "America/Sao_Paulo"
    roles = user.config["roles"] if user.config and "roles" in user.config else []

    p = Patient.findByAdmission(admissionNumber)
    if p is None:
        first_prescription = (
            db.session.query(Prescription)
            .filter(Prescription.admissionNumber == admissionNumber)
            .filter(Prescription.agg == None)
            .filter(Prescription.concilia == None)
            .filter(Prescription.idSegment != None)
            .order_by(asc(Prescription.date))
            .first()
        )

        if first_prescription == None:
            return {
                "status": "error",
                "message": "Paciente Inexistente!",
            }, status.HTTP_400_BAD_REQUEST

        p = Patient()
        p.admissionNumber = admissionNumber
        p.admissionDate = first_prescription.date
        p.idHospital = first_prescription.idHospital
        p.idPatient = first_prescription.idPatient
        db.session.add(p)

    updateWeight = False

    if RoleEnum.READONLY.value in roles and not (
        RoleEnum.ADMIN.value in roles or RoleEnum.TRAINING.value in roles
    ):
        return {
            "status": "error",
            "message": "Permissão inválida",
        }, status.HTTP_401_UNAUTHORIZED

    if RoleEnum.SUPPORT.value not in roles and RoleEnum.READONLY.value not in roles:
        if "weight" in data.keys():
            weight = data.get("weight", None)

            if weight != p.weight:
                p.weightDate = datetime.today()
                p.weight = weight
                updateWeight = True

        alertExpire = data.get("alertExpire", None)
        if alertExpire and alertExpire != p.alertExpire:
            p.alert = data.get("alert", None)
            p.alertExpire = alertExpire
            p.alertDate = datetime.today()
            p.alertBy = user.id

        if "height" in data.keys():
            p.height = data.get("height", None)
        if "dialysis" in data.keys():
            p.dialysis = data.get("dialysis", None)
        if "lactating" in data.keys():
            p.lactating = data.get("lactating", None)
        if "pregnant" in data.keys():
            p.pregnant = data.get("pregnant", None)
        if "observation" in data.keys():
            p.observation = data.get("observation", None)
        if "skinColor" in data.keys():
            p.skinColor = data.get("skinColor", None)
        if "gender" in data.keys():
            p.gender = data.get("gender", None)
        if "birthdate" in data.keys():
            p.birthdate = data.get("birthdate", None)

    if RoleEnum.ADMIN.value in roles or RoleEnum.TRAINING.value in roles:
        if "dischargeDate" in data.keys():
            p.dischargeDate = data.get("dischargeDate", None)

    p.update = datetime.today()
    p.user = user.id

    if "idPrescription" in data.keys() and updateWeight:
        idPrescription = data.get("idPrescription")

        query = text(
            "INSERT INTO "
            + user.schema
            + ".presmed \
                    SELECT *\
                    FROM "
            + user.schema
            + ".presmed\
                    WHERE fkprescricao = :idPrescription ;"
        )

        db.session.execute(query, {"idPrescription": idPrescription})

    return tryCommit(db, escape_html(admissionNumber))


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

    patients = patient_service.get_patients(
        id_segment=id_segment,
        id_department_list=id_department_list,
        next_appointment_start_date=next_appointment_start_date,
        next_appointment_end_date=next_appointment_end_date,
        scheduled_by_list=scheduled_by_list,
        attended_by_list=attended_by_list,
        appointment=appointment,
    )

    return {
        "status": "success",
        "data": patient_converter.list_to_dto(patients),
    }, status.HTTP_200_OK
