from sqlalchemy import distinct, text
from datetime import datetime

from models.main import db, User
from models.prescription import Prescription, PrescriptionDrug, Drug
from models.enums import FeatureEnum
from services import memory_service
from exception.validation_error import ValidationError
from decorators.has_permission_decorator import has_permission, Permission
from utils import status


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


@has_permission(Permission.WRITE_PRESCRIPTION)
def createPrescriptionDrug(data, user_context: User):
    prescription = (
        db.session.query(Prescription)
        .filter(Prescription.id == data.get("idPrescription", None))
        .first()
    )

    _validate_permission(prescription=prescription)

    if prescription.concilia == None:
        next_id = getNextId(prescription.id, user_context.schema)
    else:
        count = (
            db.session.query(PrescriptionDrug)
            .filter(PrescriptionDrug.idPrescription == prescription.id)
            .count()
        )
        next_id = str(prescription.id - 90000000000000000) + str(count).zfill(2)

    pdCreate = PrescriptionDrug()

    pdCreate.id = next_id
    pdCreate.idPrescription = data.get("idPrescription", None)
    pdCreate.source = data.get("source", None)

    pdCreate.idDrug = data.get("idDrug", None)
    pdCreate.dose = data.get("dose", None)
    pdCreate.idMeasureUnit = data.get("measureUnit", None)
    pdCreate.idFrequency = data.get("frequency", None)
    pdCreate.interval = data.get("interval", None)
    pdCreate.route = data.get("route", None)
    pdCreate.notes = data.get("recommendation", None)

    pdCreate.update = datetime.today()
    pdCreate.user = user_context.id

    db.session.add(pdCreate)
    db.session.flush()

    return pdCreate.id


@has_permission(Permission.WRITE_PRESCRIPTION)
def updatePrescriptionDrug(idPrescriptionDrug, data, user_context: User):
    pdUpdate = PrescriptionDrug.query.get(idPrescriptionDrug)
    if pdUpdate is None:
        raise ValidationError(
            "Registro Inexistente!",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    prescription = (
        db.session.query(Prescription)
        .filter(Prescription.id == pdUpdate.idPrescription)
        .first()
    )

    _validate_permission(prescription=prescription)

    pdUpdate.update = datetime.today()
    pdUpdate.user = user_context.id

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
        + user_context.schema
        + ".presmed \
        SELECT *\
        FROM "
        + user_context.schema
        + ".presmed\
        WHERE fkpresmed = :id"
    )

    db.session.execute(query, {"id": idPrescriptionDrug})


@has_permission(Permission.WRITE_PRESCRIPTION)
def togglePrescriptionDrugSuspension(idPrescriptionDrug, user_context: User, suspend):
    pdUpdate = PrescriptionDrug.query.get(idPrescriptionDrug)
    if pdUpdate is None:
        raise ValidationError(
            "Registro Inexistente!",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

    prescription = (
        db.session.query(Prescription)
        .filter(Prescription.id == pdUpdate.idPrescription)
        .first()
    )

    _validate_permission(prescription=prescription)

    if suspend == True:
        pdUpdate.suspendedDate = datetime.today()
    else:
        pdUpdate.suspendedDate = None

    pdUpdate.update = datetime.today()
    pdUpdate.user = user_context.id

    db.session.add(pdUpdate)
    db.session.flush()

    return pdUpdate


@has_permission(Permission.WRITE_PRESCRIPTION)
def copy_missing_drugs(idPrescription, user_context: User, idDrugs):
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
        new_id = getNextId(idPrescription, user_context.schema)
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
        pdCreate.user = user_context.id
        db.session.add(pdCreate)
        db.session.flush()

    return ids_list


@has_permission(Permission.WRITE_PRESCRIPTION)
def get_missing_drugs(idPrescription):
    prescription = Prescription.query.get(idPrescription)
    if prescription is None:
        raise ValidationError(
            "Registro Inexistente!",
            "errors.invalidRegister",
            status.HTTP_400_BAD_REQUEST,
        )

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


def _validate_permission(prescription: Prescription):
    if prescription == None:
        raise ValidationError(
            "Prescrição inexistente",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    if prescription.concilia != None:
        if not memory_service.has_feature(FeatureEnum.CONCILIATION_EDIT.value):
            raise ValidationError(
                "Feature desabilitada",
                "errors.unauthorizedFeature",
                status.HTTP_401_UNAUTHORIZED,
            )
