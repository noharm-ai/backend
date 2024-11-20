from models.main import db
from models.prescription import Patient
from models.regulation import RegSolicitation, RegSolicitationType


def get_prioritization():
    query = (
        db.session.query(RegSolicitation, RegSolicitationType, Patient)
        .outerjoin(
            RegSolicitationType,
            RegSolicitation.id_reg_solicitation_type == RegSolicitationType.id,
        )
        .outerjoin(Patient, RegSolicitation.admission_number == Patient.admissionNumber)
    )

    return query.all()
