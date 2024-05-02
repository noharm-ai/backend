from utils import status
from sqlalchemy import distinct, text

from models.main import db
from models.appendix import *
from models.prescription import *

from exception.validation_error import ValidationError


def getNextId(idPrescription, schema):
    result = db.session.execute(
        text(
            "SELECT\
        CONCAT(p.fkprescricao, LPAD(COUNT(*)::VARCHAR, 3, '0'))\
      FROM "
            + schema
            + ".presmed p\
      WHERE\
        p.fkprescricao = :id\
      GROUP BY\
        p.fkprescricao"
        ),
        {"id": idPrescription},
    )

    return ([row[0] for row in result])[0]


def createPrescriptionDrug(data, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if "prescriptionEdit" not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    pdCreate = PrescriptionDrug()

    pdCreate.id = getNextId(data.get("idPrescription", None), user.schema)
    pdCreate.idPrescription = data.get("idPrescription", None)
    pdCreate.source = data.get("source", None)

    pdCreate.idDrug = data.get("idDrug", None)
    pdCreate.dose = data.get("dose", None)
    pdCreate.idMeasureUnit = data.get("measureUnit", None)
    pdCreate.idFrequency = data.get("frequency", None)
    pdCreate.interval = data.get("interval", None)
    pdCreate.route = data.get("route", None)

    pdCreate.update = datetime.today()
    pdCreate.user = user.id

    db.session.add(pdCreate)
    db.session.flush()

    return pdCreate.id


def updatePrescriptionDrug(idPrescriptionDrug, data, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if "prescriptionEdit" not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    pdUpdate = PrescriptionDrug.query.get(idPrescriptionDrug)
    if pdUpdate is None:
        raise ValidationError(
            "Registro Inexistente!",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    pdUpdate.update = datetime.today()
    pdUpdate.user = user.id

    if "dose" in data.keys():
        pdUpdate.dose = data.get("dose", None)

    if "measureUnit" in data.keys():
        pdUpdate.idMeasureUnit = data.get("measureUnit", None)

    if "frequency" in data.keys():
        pdUpdate.idFrequency = data.get("frequency", None)

    if "interval" in data.keys():
        pdUpdate.interval = data.get("interval", None)

    if "route" in data.keys():
        pdUpdate.route = data.get("route", None)

    if "recommendation" in data.keys():
        pdUpdate.notes = data.get("recommendation", None)

    db.session.add(pdUpdate)
    db.session.flush()

    # calc score
    query = text(
        "\
      INSERT INTO "
        + user.schema
        + ".presmed \
        SELECT *\
        FROM "
        + user.schema
        + ".presmed\
        WHERE fkpresmed = :id"
    )

    db.session.execute(query, {"id": idPrescriptionDrug})


def togglePrescriptionDrugSuspension(idPrescriptionDrug, user, suspend):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if "prescriptionEdit" not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    pdUpdate = PrescriptionDrug.query.get(idPrescriptionDrug)
    if pdUpdate is None:
        raise ValidationError(
            "Registro Inexistente!",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    if suspend == True:
        pdUpdate.suspendedDate = datetime.today()
    else:
        pdUpdate.suspendedDate = None

    pdUpdate.update = datetime.today()
    pdUpdate.user = user.id

    db.session.add(pdUpdate)
    db.session.flush()

    return pdUpdate


def copy_missing_drugs(idPrescription, user, idDrugs):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if "prescriptionEdit" not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    if idDrugs == None or len(idDrugs) == 0:
        raise ValidationError(
            "Nenhum medicamento selecionado",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    prescription = Prescription.query.get(idPrescription)
    if prescription is None:
        raise ValidationError(
            "Registro Inexistente!",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    drugs = (
        db.session.query(PrescriptionDrug)
        .distinct(PrescriptionDrug.idDrug)
        .join(Prescription, Prescription.id == PrescriptionDrug.idPrescription)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .filter(PrescriptionDrug.idDrug.in_(idDrugs))
        .order_by(PrescriptionDrug.idDrug)
        .all()
    )

    ids_list = []

    for d in drugs:
        pdCreate = PrescriptionDrug()
        new_id = getNextId(idPrescription, user.schema)
        ids_list.append(new_id)

        pdCreate.id = new_id
        pdCreate.idPrescription = idPrescription
        pdCreate.source = d.source

        pdCreate.idDrug = d.idDrug
        pdCreate.dose = d.dose
        pdCreate.idMeasureUnit = d.idMeasureUnit
        pdCreate.idFrequency = d.idFrequency
        pdCreate.interval = d.interval
        pdCreate.route = d.route

        pdCreate.update = datetime.today()
        pdCreate.user = user.id
        db.session.add(pdCreate)
        db.session.flush()

    return ids_list


def get_missing_drugs(idPrescription, user):
    roles = user.config["roles"] if user.config and "roles" in user.config else []
    if "prescriptionEdit" not in roles:
        raise ValidationError(
            "Usuário não autorizado",
            "errors.unauthorizedUser",
            status.HTTP_401_UNAUTHORIZED,
        )

    prescription = Prescription.query.get(idPrescription)
    if prescription is None:
        return {
            "status": "error",
            "message": "Registro Inexistente!",
            "code": "errors.invalidRegister",
        }, status.HTTP_400_BAD_REQUEST

    pd_drugs = db.aliased(PrescriptionDrug)
    q_drugs = (
        db.session.query(pd_drugs.idDrug)
        .select_from(pd_drugs)
        .filter(pd_drugs.idPrescription == prescription.id)
    )

    return (
        db.session.query(distinct(PrescriptionDrug.idDrug), Drug.name)
        .join(Prescription, Prescription.id == PrescriptionDrug.idPrescription)
        .join(Drug, Drug.id == PrescriptionDrug.idDrug)
        .filter(Prescription.admissionNumber == prescription.admissionNumber)
        .filter(PrescriptionDrug.suspendedDate == None)
        .filter(PrescriptionDrug.idDrug.notin_(q_drugs))
        .order_by(Drug.name)
        .all()
    )
