"""Helpers to seed regulation ("regulação") records for integration tests.

The regulation tables are created by ``noharm-create-regulation.sql`` and ship
without seed data, so every test builds the rows it needs. Reserved id ranges
keep the generated rows apart from the seed database and let ``_cleanup`` in
``tests/conftest.py`` remove them afterwards:

* solicitation types: ``fkreg_tipo_solicitacao >= 900000``
* solicitations (and their movements/attributes): ``fkreg_solicitacao >= 900000``
* patients/admissions: ``nratendimento >= 8000000``, below the ``90000000``
  mask used by ``get_next_admission_number`` so the manual-create flow keeps
  starting from its own range
* ICD codes: ``public.tb_cid10.co_cid10 >= 900000``
"""

from datetime import datetime

from sqlalchemy import text

from models.main import User
from models.prescription import Patient, Prescription
from models.regulation import RegSolicitation, RegSolicitationType
from tests.conftest import session, session_commit

# ids reserved for regulation test rows
TYPE_ID_BASE = 900000
SOLICITATION_ID_BASE = 900000
ADMISSION_BASE = 8000000
ICD_ID_BASE = 900000


def get_user_id(email: str = "demo") -> int:
    """Return the id of a seed user, used as the record's responsible."""
    return session.query(User).filter(User.email == email).first().id


def create_solicitation_type(id: int, name: str, tp_type: int = 1, status: int = 1):
    """Create a solicitation type (e.g. "Consulta em cardiologista")."""
    solicitation_type = RegSolicitationType()
    solicitation_type.id = id
    solicitation_type.name = name
    solicitation_type.status = status
    solicitation_type.tp_type = tp_type
    solicitation_type.created_at = datetime.now()
    solicitation_type.updated_at = datetime.now()

    session.add(solicitation_type)
    session_commit()

    return solicitation_type


def create_patient(
    admission_number: int,
    id_patient: int,
    birthdate: datetime = None,
    gender: str = "M",
    id_icd: str = None,
):
    """Create the patient/admission a solicitation points to."""
    patient = Patient()
    patient.idHospital = 1
    patient.idPatient = id_patient
    patient.admissionNumber = admission_number
    patient.admissionDate = datetime.now()
    patient.birthdate = birthdate
    patient.gender = gender
    patient.id_icd = id_icd
    patient.update = datetime.now()

    session.add(patient)
    session_commit()

    return patient


def create_solicitation(
    id: int,
    admission_number: int,
    id_patient: int,
    date: datetime,
    id_reg_solicitation_type: int,
    id_department: int = 1,
    risk: int = None,
    stage: int = 0,
    schedule_date: datetime = None,
    transportation_date: datetime = None,
    created_by: int = None,
    cid: str = None,
    attendant: str = None,
    attendant_record: str = None,
    justification: str = None,
):
    """Create a solicitation already positioned at the given stage."""
    solicitation = RegSolicitation()
    solicitation.id = id
    solicitation.admission_number = admission_number
    solicitation.id_patient = id_patient
    solicitation.date = date
    solicitation.id_reg_solicitation_type = id_reg_solicitation_type
    solicitation.id_department = id_department
    solicitation.risk = risk
    solicitation.stage = stage
    solicitation.schedule_date = schedule_date
    solicitation.transportation_date = transportation_date
    solicitation.cid = cid
    solicitation.attendant = attendant
    solicitation.attendant_record = attendant_record
    solicitation.justification = justification
    solicitation.created_at = datetime.now()
    solicitation.created_by = created_by
    solicitation.updated_at = datetime.now()

    session.add(solicitation)
    session_commit()

    return solicitation


def create_icd(id_int: int, id_str: str, name: str):
    """Create an ICD row in the shared ``public.tb_cid10`` table.

    Raw SQL, because the table carries not-null columns the ``ICDTable`` model
    does not map.
    """
    session.execute(
        text(
            "INSERT INTO public.tb_cid10 "
            "(co_cid10, nu_cid10, tp_agravo, no_cid10, no_cid10_filtro, st_ativo) "
            "VALUES (:id_int, :id_str, :kind, :name, :name, 1)"
        ),
        {"id_int": id_int, "id_str": id_str, "kind": 1, "name": name},
    )
    session_commit()


def create_agg_prescription(
    id: int, admission_number: int, id_patient: int, global_score: int
):
    """Create the aggregated prescription the prioritization reads the score from."""
    prescription = Prescription()
    prescription.id = id
    prescription.idHospital = 1
    prescription.idDepartment = 1
    prescription.idSegment = 1
    prescription.idPatient = id_patient
    prescription.admissionNumber = admission_number
    prescription.date = datetime.now()
    prescription.status = "0"
    prescription.agg = True
    prescription.features = {"globalScore": global_score}

    session.add(prescription)
    session_commit()

    return prescription


def clean_regulation_data():
    """Remove every regulation row created by the tests."""
    session.execute(
        text("DELETE FROM demo.reg_movimentacao WHERE fkreg_solicitacao >= :base"),
        {"base": SOLICITATION_ID_BASE},
    )
    session.execute(
        text(
            "DELETE FROM demo.reg_solicitacao_atributo WHERE fkreg_solicitacao >= :base"
        ),
        {"base": SOLICITATION_ID_BASE},
    )
    session.execute(
        text("DELETE FROM demo.reg_solicitacao WHERE fkreg_solicitacao >= :base"),
        {"base": SOLICITATION_ID_BASE},
    )
    session.execute(
        text(
            "DELETE FROM demo.reg_tipo_solicitacao WHERE fkreg_tipo_solicitacao >= :base"
        ),
        {"base": TYPE_ID_BASE},
    )
    session.execute(
        text("DELETE FROM public.tb_cid10 WHERE co_cid10 >= :base"),
        {"base": ICD_ID_BASE},
    )
    # patients (and their aggregated prescription) seeded for the queue; the
    # admissions created by the manual-create flow start at 90000000 and are
    # removed by the session-wide cleanup in tests/conftest.py
    session.execute(
        text(
            "DELETE FROM demo.prescricao WHERE nratendimento >= :base AND nratendimento < 90000000"
        ),
        {"base": ADMISSION_BASE},
    )
    session.execute(
        text(
            "DELETE FROM demo.pessoa WHERE nratendimento >= :base AND nratendimento < 90000000"
        ),
        {"base": ADMISSION_BASE},
    )
    session_commit()
    session.expunge_all()
