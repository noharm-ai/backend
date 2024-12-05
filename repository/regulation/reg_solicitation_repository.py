from sqlalchemy import asc, desc, func, nullslast
from datetime import timedelta

from models.main import db, User
from models.prescription import Patient, Department
from models.regulation import RegSolicitation, RegSolicitationType, RegMovement
from models.requests.regulation_prioritization_request import (
    RegulationPrioritizationRequest,
)


def get_prioritization(request_data: RegulationPrioritizationRequest):
    query = (
        db.session.query(
            RegSolicitation,
            RegSolicitationType,
            Patient,
            Department,
            func.count().over().label("total"),
        )
        .outerjoin(
            RegSolicitationType,
            RegSolicitation.id_reg_solicitation_type == RegSolicitationType.id,
        )
        .outerjoin(Patient, RegSolicitation.admission_number == Patient.admissionNumber)
        .outerjoin(Department, Department.id == RegSolicitation.id_department)
    )

    if request_data.startDate:
        query = query.filter(RegSolicitation.date >= request_data.startDate.date())

    if request_data.endDate:
        query = query.filter(
            RegSolicitation.date
            <= (request_data.endDate + timedelta(hours=23, minutes=59))
        )

    if request_data.scheduleStartDate:
        query = query.filter(
            RegSolicitation.schedule_date >= request_data.scheduleStartDate.date()
        )

    if request_data.scheduleEndDate:
        query = query.filter(
            RegSolicitation.schedule_date
            <= (request_data.scheduleEndDate + timedelta(hours=23, minutes=59))
        )

    if request_data.transportationStartDate:
        query = query.filter(
            RegSolicitation.transportation_date
            >= request_data.transportationStartDate.date()
        )

    if request_data.transportationEndDate:
        query = query.filter(
            RegSolicitation.transportation_date
            <= (request_data.transportationEndDate + timedelta(hours=23, minutes=59))
        )

    if request_data.riskList:
        query = query.filter(RegSolicitation.risk.in_(request_data.riskList))

    if request_data.idPatientList:
        query = query.filter(RegSolicitation.id_patient.in_(request_data.idPatientList))

    if request_data.idDepartmentList:
        query = query.filter(
            RegSolicitation.id_department.in_(request_data.idDepartmentList)
        )

    if request_data.typeType:
        query = query.filter(RegSolicitationType.tp_type == request_data.typeType)

    if request_data.typeList:
        query = query.filter(
            RegSolicitation.id_reg_solicitation_type.in_(request_data.typeList)
        )

    if request_data.stageList:
        query = query.filter(RegSolicitation.stage.in_(request_data.stageList))

    for order in request_data.order:
        direction = desc if order.direction == "desc" else asc
        if order.field in ["date", "risk"]:
            query = query.order_by(
                nullslast(direction(getattr(RegSolicitation, order.field)))
            )

        if order.field in ["birthdate"]:
            direction = asc if order.direction == "desc" else desc
            query = query.order_by(nullslast(direction(getattr(Patient, order.field))))

    query = query.limit(request_data.limit).offset(request_data.offset)

    return query.all()


def get_solicitation(id: int):
    query = (
        db.session.query(
            RegSolicitation,
            RegSolicitationType,
            Patient,
        )
        .outerjoin(
            RegSolicitationType,
            RegSolicitation.id_reg_solicitation_type == RegSolicitationType.id,
        )
        .outerjoin(Patient, RegSolicitation.admission_number == Patient.admissionNumber)
        .filter(RegSolicitation.id == id)
    )

    return query.first()


def get_solicitation_movement(id_reg_solicitation: int):
    query = (
        db.session.query(RegMovement, User)
        .outerjoin(User, RegMovement.created_by == User.id)
        .filter(RegMovement.id_reg_solicitation == id_reg_solicitation)
        .order_by(RegMovement.created_at.desc())
    )

    return query.all()


def get_types():
    query = db.session.query(RegSolicitationType).order_by(
        RegSolicitationType.name.asc()
    )

    return query.all()
