"""Repository: antimicrobial related queries"""

from sqlalchemy import and_, func, or_

from models.appendix import Department, Frequency, MeasureUnit
from models.main import DrugAttributes, Drug, Substance, db
from models.prescription import Prescription, PrescriptionDrug
from models.segment import Segment


def get_admission_antimicrobials(admission_number: int):
    """Every antimicrobial prescribed for an admission, oldest prescription first.

    Aggregated (prescription-day) and conciliation prescriptions are left out:
    the first repeats the real prescriptions and the second is not a treatment.
    A drug counts as antimicrobial when its attributes for the item's segment
    are flagged ``antimicro``.
    """
    # the measure unit of an item may be registered for another hospital only
    measure_unit_any = db.aliased(MeasureUnit)
    measure_unit_hospital = (
        db.session.query(func.min(measure_unit_any.idHospital))
        .filter(measure_unit_any.id == PrescriptionDrug.idMeasureUnit)
        .scalar_subquery()
    )

    return (
        db.session.query(
            PrescriptionDrug.id.label("id_prescription_drug"),
            PrescriptionDrug.idDrug.label("id_drug"),
            PrescriptionDrug.dose,
            PrescriptionDrug.doseconv,
            PrescriptionDrug.frequency.label("daily_frequency"),
            PrescriptionDrug.route,
            PrescriptionDrug.suspendedDate.label("suspended_date"),
            PrescriptionDrug.period_total,
            Prescription.id.label("id_prescription"),
            Prescription.date,
            Prescription.expire,
            Prescription.idSegment.label("id_segment"),
            Segment.cpoe,
            Drug.name.label("drug"),
            Substance.name.label("substance"),
            Substance.atb_level,
            MeasureUnit.description.label("measure_unit"),
            Frequency.description.label("frequency"),
        )
        .join(Prescription, Prescription.id == PrescriptionDrug.idPrescription)
        .join(
            DrugAttributes,
            and_(
                DrugAttributes.idDrug == PrescriptionDrug.idDrug,
                DrugAttributes.idSegment
                == func.coalesce(PrescriptionDrug.idSegment, Prescription.idSegment),
            ),
        )
        .join(Drug, Drug.id == PrescriptionDrug.idDrug)
        .outerjoin(Substance, Substance.id == Drug.sctid)
        .outerjoin(Segment, Segment.id == Prescription.idSegment)
        .outerjoin(
            MeasureUnit,
            and_(
                MeasureUnit.id == PrescriptionDrug.idMeasureUnit,
                MeasureUnit.idHospital == measure_unit_hospital,
            ),
        )
        .outerjoin(
            Frequency,
            and_(
                Frequency.id == PrescriptionDrug.idFrequency,
                Frequency.idHospital == Prescription.idHospital,
            ),
        )
        .filter(Prescription.admissionNumber == admission_number)
        .filter(or_(Prescription.agg == None, Prescription.agg == False))
        .filter(Prescription.concilia == None)
        .filter(DrugAttributes.antimicro == True)
        .order_by(Prescription.date, PrescriptionDrug.id)
        .all()
    )


def get_last_prescription(admission_number: int):
    """The latest real prescription of an admission with its department and
    segment names, or None when the admission has no prescription"""
    return (
        db.session.query(
            Prescription,
            Department.name.label("department"),
            Segment.description.label("segment"),
        )
        .outerjoin(
            Department,
            and_(
                Department.id == Prescription.idDepartment,
                Department.idHospital == Prescription.idHospital,
            ),
        )
        .outerjoin(Segment, Segment.id == Prescription.idSegment)
        .filter(Prescription.admissionNumber == admission_number)
        .filter(or_(Prescription.agg == None, Prescription.agg == False))
        .filter(Prescription.concilia == None)
        .order_by(Prescription.date.desc())
        .first()
    )
