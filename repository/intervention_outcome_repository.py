"""Repository: intervention outcome related operations"""

from sqlalchemy import and_, case, func

from models.main import db, User, Drug, DrugAttributes
from models.prescription import (
    Prescription,
    PrescriptionDrug,
    Intervention,
)
from models.appendix import (
    InterventionReason,
    MeasureUnit,
    MeasureUnitConvert,
    Frequency,
)


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
        .outerjoin(Drug, PrescriptionDrug.idDrug == Drug.id)
        .join(Prescription, PrescriptionDrug.idPrescription == Prescription.id)
        .outerjoin(
            DrugAttributes,
            and_(
                PrescriptionDrug.idDrug == DrugAttributes.idDrug,
                func.coalesce(PrescriptionDrug.idSegment, 1)
                == DrugAttributes.idSegment,
            ),
        )
        .outerjoin(
            PrescriptionDrugConvert,
            and_(
                PrescriptionDrugConvert.idDrug == PrescriptionDrug.idDrug,
                PrescriptionDrugConvert.idSegment
                == func.coalesce(PrescriptionDrug.idSegment, 1),
                PrescriptionDrugConvert.idMeasureUnit == PrescriptionDrug.idMeasureUnit,
            ),
        )
        .outerjoin(
            PrescriptionDrugPriceConvert,
            and_(
                PrescriptionDrugPriceConvert.idDrug == PrescriptionDrug.idDrug,
                PrescriptionDrugPriceConvert.idSegment
                == func.coalesce(PrescriptionDrug.idSegment, 1),
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
