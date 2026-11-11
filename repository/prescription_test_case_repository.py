"""Repository: prescription test cases (maintainers' test schema)

The rows are inserted as the hospital integration inserts them: the
prescricao and presmed insert triggers complete them (segment, doseconv,
frequenciadia, outlier, score...) and upsert the row themselves, so the ORM
never sees the insert and the rows are read back afterwards.
"""

from datetime import datetime

from sqlalchemy import func, insert, select, text, update

from models.appendix import (
    Department,
    Frequency,
    MeasureUnit,
    Memory,
    SegmentDepartment,
)
from models.main import Drug, db
from models.prescription import Patient, Prescription, PrescriptionDrug

# nratendimento has a check constraint (and the prescription-day id adds it to
# the segment's billions)
MAX_ADMISSION_NUMBER = 999_999_999

# presmed ids are the prescription id followed by a 3 digit sequence (as the
# prescription edit does), and must fit a bigint
MAX_PRESCRIPTION_ID = 9_223_372_036_854_775_807 // 1000 - 1


def lock_allocation(schema: str):
    """Serialize the test cases of a schema until the transaction ends: the ids
    are the next free ones"""
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:key, 0))"),
        {"key": f"prescription_test_case:{schema}"},
    )


def get_segment_departments(id_department: int) -> list[SegmentDepartment]:
    """The segments of a department (one per hospital it is in)"""
    return (
        db.session.query(SegmentDepartment)
        .filter(SegmentDepartment.idDepartment == id_department)
        .order_by(SegmentDepartment.idHospital)
        .all()
    )


def get_department(id_department: int, id_hospital: int) -> Department | None:
    """The department record"""
    return (
        db.session.query(Department)
        .filter(Department.id == id_department)
        .filter(Department.idHospital == id_hospital)
        .first()
    )


def get_patient(admission_number: int) -> Patient | None:
    """The admission (pessoa)"""
    return db.session.get(Patient, admission_number)


def next_admission_number() -> int:
    """After every admission of the schema, with or without a pessoa record"""
    last_patient = db.session.query(func.max(Patient.admissionNumber)).scalar()
    last_prescription = db.session.query(
        func.max(Prescription.admissionNumber)
    ).scalar()

    return max(last_patient or 0, last_prescription or 0) + 1


def next_patient_id() -> int:
    """After every patient of the schema"""
    last_patient = db.session.query(func.max(Patient.idPatient)).scalar()
    last_prescription = db.session.query(func.max(Prescription.idPatient)).scalar()

    return max(last_patient or 0, last_prescription or 0) + 1


def next_prescription_id() -> int:
    """After every prescription the hospital sent: prescription-days and
    conciliations have ids of their own"""
    last_prescription = (
        db.session.query(func.max(Prescription.id))
        .filter(Prescription.agg.is_(None))
        .filter(Prescription.concilia.is_(None))
        .scalar()
    )

    return (last_prescription or 0) + 1


def prescription_exists(id_prescription: int) -> bool:
    """Whether a prescription has the id"""
    return (
        db.session.query(Prescription.id)
        .filter(Prescription.id == id_prescription)
        .first()
        is not None
    )


def count_prescription_drugs(ids: list[int]) -> int:
    """How many presmed records have one of the ids"""
    return (
        db.session.query(func.count(PrescriptionDrug.id))
        .filter(PrescriptionDrug.id.in_(ids))
        .scalar()
    )


def find_missing_drugs(ids: list[int]) -> set[int]:
    """The drug ids without a medicamento record"""
    found = db.session.execute(select(Drug.id).where(Drug.id.in_(ids))).scalars()
    return set(ids) - set(found)


def find_missing_measure_units(ids: list[str]) -> set[str]:
    """The measure unit ids without a unidademedida record"""
    found = db.session.execute(
        select(MeasureUnit.id).where(MeasureUnit.id.in_(ids))
    ).scalars()
    return set(ids) - set(found)


def find_missing_frequencies(ids: list[str]) -> set[str]:
    """The frequency ids without a frequencia record"""
    found = db.session.execute(
        select(Frequency.id).where(Frequency.id.in_(ids))
    ).scalars()
    return set(ids) - set(found)


def get_origin_values(kinds: list[str]) -> dict[str, list[str]]:
    """The values the hospital sends in presmed.origem for each item kind
    (memoria map-origin-*), as the presmed trigger maps them"""
    rows = db.session.query(Memory).filter(Memory.kind.in_(kinds)).all()

    values: dict[str, list[str]] = {}
    for row in rows:
        if isinstance(row.value, list):
            values.setdefault(row.kind, []).extend(str(v) for v in row.value)

    return values


def insert_patient(
    schema: str,
    admission_number: int,
    id_patient: int,
    id_hospital: int,
    admission_date: datetime,
    birthdate,
    gender: str | None,
    weight: float | None,
    height: float | None,
    id_department: int,
    bed: str | None,
    id_user: int,
):
    """A new admission (pessoa has no insert trigger)"""
    db.session.execute(
        insert(Patient.__table__).values(
            nratendimento=admission_number,
            fkpessoa=id_patient,
            fkhospital=id_hospital,
            dtinternacao=admission_date,
            dtnascimento=birthdate,
            sexo=gender,
            peso=weight,
            dtpeso=admission_date if weight else None,
            altura=height,
            update_at=datetime.today(),
            update_by=id_user,
        )
    )
    # not in the model: the admission's department and bed (a text query is
    # not schema translated; the schema is the user's, from the token)
    db.session.execute(
        text(
            f"UPDATE {schema}.pessoa SET fksetor = :id_department, leito = :bed "
            "WHERE nratendimento = :admission_number"
        ),
        {
            "id_department": id_department,
            "bed": bed,
            "admission_number": admission_number,
        },
    )


def insert_prescription(
    id_prescription: int,
    id_patient: int,
    admission_number: int,
    id_hospital: int,
    id_department: int,
    prescription_date: datetime,
    expire: datetime,
    bed: str | None,
    prescriber: str | None,
):
    """The prescription, through the prescricao insert trigger (it sets the
    segment of the department)"""
    db.session.execute(
        insert(Prescription.__table__).values(
            fkprescricao=id_prescription,
            fkpessoa=id_patient,
            nratendimento=admission_number,
            fkhospital=id_hospital,
            fksetor=id_department,
            dtprescricao=prescription_date,
            dtvigencia=expire,
            leito=bed,
            prescritor=prescriber,
        )
    )


def insert_prescription_drug(
    id_prescription_drug: int,
    id_prescription: int,
    id_drug: int,
    origin: str,
    dose: float | None,
    id_measure_unit: str | None,
    id_frequency: str | None,
    interval: str | None,
    route: str | None,
    notes: str | None,
):
    """An item, through the presmed insert trigger (doseconv, frequenciadia,
    segment, outlier and score, as for the hospital's items)"""
    db.session.execute(
        insert(PrescriptionDrug.__table__).values(
            fkpresmed=id_prescription_drug,
            fkprescricao=id_prescription,
            fkmedicamento=id_drug,
            origem=origin,
            dose=dose,
            fkunidademedida=id_measure_unit,
            fkfrequencia=id_frequency,
            horario=interval,
            via=route,
            complemento=notes,
        )
    )


def set_prescription_drug_origin(id_prescription_drug: int, origin: str):
    """Keep the item kind chosen when the schema maps no value to it (the
    trigger falls back to Medicamentos)"""
    db.session.execute(
        update(PrescriptionDrug.__table__)
        .where(PrescriptionDrug.__table__.c.fkpresmed == id_prescription_drug)
        .values(origem=origin)
    )


def get_prescription_drug_origins(id_prescription: int) -> dict[int, str]:
    """The item kind of each item of the prescription"""
    rows = db.session.execute(
        select(PrescriptionDrug.id, PrescriptionDrug.source).where(
            PrescriptionDrug.idPrescription == id_prescription
        )
    ).all()

    return {row.id: row.source for row in rows}


def get_prescription(id_prescription: int) -> Prescription | None:
    """The prescription as it is in the database (not the identity map's)"""
    return db.session.execute(
        select(Prescription)
        .where(Prescription.id == id_prescription)
        .execution_options(populate_existing=True)
    ).scalar_one_or_none()
