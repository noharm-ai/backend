from sqlalchemy import and_, case, func

from models.main import db, User
from models.prescription import (
    Prescription,
    PrescriptionDrug,
    Drug,
    MeasureUnit,
    Frequency,
    MeasureUnitConvert,
    DrugAttributes,
    Intervention,
)
from models.appendix import InterventionReason


def get_outcome(id_intervention: int):
    """
    Intervention outcome main data
    """
    InterventionReasonParent = db.aliased(InterventionReason)
    reason_column = case(
        (
            InterventionReasonParent.description != None,
            func.concat(
                InterventionReasonParent.description,
                " - ",
                InterventionReason.description,
            ),
        ),
        else_=InterventionReason.description,
    )

    reason = (
        db.session.query(reason_column)
        .select_from(InterventionReason)
        .outerjoin(
            InterventionReasonParent,
            InterventionReasonParent.id == InterventionReason.mamy,
        )
        .filter(InterventionReason.id == func.any(Intervention.idInterventionReason))
        .scalar_subquery()
    )

    return (
        db.session.query(
            Intervention,
            PrescriptionDrug,
            Drug,
            User,
            func.array(reason).label("reason"),
        )
        .outerjoin(PrescriptionDrug, PrescriptionDrug.id == Intervention.id)
        .outerjoin(Drug, PrescriptionDrug.idDrug == Drug.id)
        .outerjoin(User, Intervention.outcome_by == User.id)
        .filter(Intervention.idIntervention == id_intervention)
        .first()
    )


def get_outcome_data_query():
    """
    Base query to get prescription economy data
    """

    PrescriptionDrugConvert = db.aliased(MeasureUnitConvert)
    PrescriptionDrugPriceConvert = db.aliased(MeasureUnitConvert)
    PrescriptionDrugFrequency = db.aliased(Frequency)
    DefaultMeasureUnit = db.aliased(MeasureUnit)

    return (
        db.session.query(
            PrescriptionDrug,
            Drug,
            DrugAttributes,
            PrescriptionDrugConvert,
            PrescriptionDrugPriceConvert,
            Prescription,
            DefaultMeasureUnit,
            PrescriptionDrugFrequency,
        )
        .join(Drug, PrescriptionDrug.idDrug == Drug.id)
        .join(Prescription, PrescriptionDrug.idPrescription == Prescription.id)
        .outerjoin(
            DrugAttributes,
            and_(
                PrescriptionDrug.idDrug == DrugAttributes.idDrug,
                PrescriptionDrug.idSegment == DrugAttributes.idSegment,
            ),
        )
        .outerjoin(
            PrescriptionDrugConvert,
            and_(
                PrescriptionDrugConvert.idDrug == PrescriptionDrug.idDrug,
                PrescriptionDrugConvert.idSegment == PrescriptionDrug.idSegment,
                PrescriptionDrugConvert.idMeasureUnit == PrescriptionDrug.idMeasureUnit,
            ),
        )
        .outerjoin(
            PrescriptionDrugPriceConvert,
            and_(
                PrescriptionDrugPriceConvert.idDrug == PrescriptionDrug.idDrug,
                PrescriptionDrugPriceConvert.idSegment == PrescriptionDrug.idSegment,
                PrescriptionDrugPriceConvert.idMeasureUnit
                == DrugAttributes.idMeasureUnitPrice,
            ),
        )
        .outerjoin(
            DefaultMeasureUnit,
            DrugAttributes.idMeasureUnit == DefaultMeasureUnit.id,
        )
        .outerjoin(
            PrescriptionDrugFrequency,
            PrescriptionDrug.idFrequency == PrescriptionDrugFrequency.id,
        )
    )
