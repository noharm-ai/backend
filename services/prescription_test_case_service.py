"""Service: prescription test cases, created by maintainers in their test schema

Maintainers build test cases (alerts, interactions, scores, prioritization)
with prescriptions they write themselves, only in a schema with the
PRESCRIPTION_TEST_CASE feature (one only they use, no hospital's). The
prescription is inserted as the hospital integration inserts it, so the
database triggers complete it, and prescalc runs on it right away as the
static user (as prescalc central would a few minutes later), so it is in the
prioritization when the request returns.
"""

import json
from datetime import datetime, timedelta

from decorators.has_permission_decorator import Permission, has_permission
from exception.validation_error import ValidationError
from models.enums import FeatureEnum
from models.main import User
from models.requests.prescription_test_case_request import PrescriptionTestCaseRequest
from repository import prescription_test_case_repository as repository
from services import (
    feature_service,
    memory_service,
    prescription_agg_service,
    segment_service,
)
from utils import logger, prescriptionutils, status

# the memoria kind that maps the hospital's origem values to each item kind
_ORIGIN_KINDS = {
    "Medicamentos": "map-origin-drug",
    "Soluções": "map-origin-solution",
    "Proced/Exames": "map-origin-procedure",
    "Dietas": "map-origin-diet",
    "Materiais": "map-origin-material",
}


@has_permission(Permission.MAINTAINER)
def create_test_case(request_data: PrescriptionTestCaseRequest, user_context: User):
    """Create a prescription in the maintainers' test schema, for a new
    admission or an existing one, and run prescalc on it.

    Returns the ids to open it: the prescription, its admission and the
    prescription-day prescalc put it in (None when prescalc left it pending)"""

    schema = user_context.schema
    # only the schema's features, never a user's: the feature marks a schema
    # no hospital uses (the frontend shows the page by the same feature)
    if not feature_service.has_feature(FeatureEnum.PRESCRIPTION_TEST_CASE):
        raise ValidationError(
            "Prescrições de teste só podem ser criadas no schema de testes",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    segment_department = _get_segment_department(request_data)
    id_hospital = segment_department.idHospital
    id_segment = segment_department.id

    _validate_items(request_data)

    prescription_date = request_data.date or datetime.today()
    expire = request_data.expire or prescription_date + timedelta(days=1)
    if expire < prescription_date:
        raise ValidationError(
            "A vigência deve ser posterior à data da prescrição",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    # the ids are the next free ones: one test case at a time per schema
    repository.lock_allocation(schema=schema)

    if request_data.admissionNumber is not None:
        patient = repository.get_patient(request_data.admissionNumber)
        if patient is None:
            raise ValidationError(
                "Atendimento inexistente",
                "errors.invalidRecord",
                status.HTTP_400_BAD_REQUEST,
            )

        admission_number = patient.admissionNumber
        id_patient = patient.idPatient
    else:
        admission_number = repository.next_admission_number()
        if admission_number > repository.MAX_ADMISSION_NUMBER:
            raise ValidationError(
                "Não há número de atendimento disponível",
                "errors.businessRules",
                status.HTTP_400_BAD_REQUEST,
            )

        id_patient = repository.next_patient_id()
        patient_data = request_data.patient
        repository.insert_patient(
            schema=schema,
            admission_number=admission_number,
            id_patient=id_patient,
            id_hospital=id_hospital,
            admission_date=prescription_date,
            birthdate=patient_data.birthdate if patient_data else None,
            gender=patient_data.gender if patient_data else None,
            weight=patient_data.weight if patient_data else None,
            height=patient_data.height if patient_data else None,
            id_department=request_data.idDepartment,
            bed=request_data.bed,
            id_user=user_context.id,
        )

    id_prescription = repository.next_prescription_id()
    item_ids = [
        int(f"{id_prescription}{str(index).zfill(3)}")
        for index in range(len(request_data.items))
    ]
    if (
        id_prescription > repository.MAX_PRESCRIPTION_ID
        or repository.prescription_exists(id_prescription)
        or repository.count_prescription_drugs(item_ids) > 0
    ):
        raise ValidationError(
            "Não há número de prescrição disponível",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    repository.insert_prescription(
        id_prescription=id_prescription,
        id_patient=id_patient,
        admission_number=admission_number,
        id_hospital=id_hospital,
        id_department=request_data.idDepartment,
        prescription_date=prescription_date,
        expire=expire,
        bed=request_data.bed,
        prescriber=request_data.prescriber,
    )

    origin_values = repository.get_origin_values(kinds=list(_ORIGIN_KINDS.values()))
    for id_prescription_drug, item in zip(item_ids, request_data.items):
        # the value the hospital sends for the kind, so the trigger maps it as
        # it maps the hospital's items
        values = origin_values.get(_ORIGIN_KINDS[item.source], [])
        repository.insert_prescription_drug(
            id_prescription_drug=id_prescription_drug,
            id_prescription=id_prescription,
            id_drug=item.idDrug,
            origin=values[0] if values else item.source,
            dose=item.dose,
            id_measure_unit=item.measureUnit,
            id_frequency=item.frequency,
            interval=item.interval,
            route=item.route,
            notes=item.notes,
        )

    # the trigger falls back to Medicamentos for a kind the schema maps no value to
    origins = repository.get_prescription_drug_origins(id_prescription)
    for id_prescription_drug, item in zip(item_ids, request_data.items):
        if origins.get(id_prescription_drug) != item.source:
            repository.set_prescription_drug_origin(
                id_prescription_drug=id_prescription_drug, origin=item.source
            )

    logger.backend_logger.warning(
        json.dumps(
            {
                "event": "prescription_test_case_created",
                "schema": schema,
                "user": user_context.id,
                "id_prescription": id_prescription,
                "admission_number": admission_number,
                "items": len(item_ids),
            }
        )
    )

    is_cpoe = segment_service.is_cpoe(id_segment=id_segment)
    _prescalc(
        schema=schema,
        id_prescription=id_prescription,
        admission_number=admission_number,
        prescription_date=prescription_date,
        is_cpoe=is_cpoe,
    )

    # prescalc rolls the transaction back when another run holds the admission
    prescription = repository.get_prescription(id_prescription)
    if prescription is None:
        raise ValidationError(
            "O atendimento está sendo processado. Tente novamente em instantes.",
            "errors.businessRules",
            status.HTTP_400_BAD_REQUEST,
        )

    id_prescription_day = _prescription_day_id(
        admission_number=admission_number,
        id_segment=prescription.idSegment,
        prescription_date=prescription_date,
        is_cpoe=is_cpoe,
    )

    return {
        "idPrescription": str(id_prescription),
        "admissionNumber": admission_number,
        "idPatient": str(id_patient),
        "idSegment": prescription.idSegment,
        "idPrescriptionDay": (
            str(id_prescription_day)
            if id_prescription_day is not None
            and repository.prescription_exists(id_prescription_day)
            else None
        ),
        "items": [str(id_prescription_drug) for id_prescription_drug in item_ids],
    }


def _get_segment_department(request_data: PrescriptionTestCaseRequest):
    """The segment of the department: without one the prescription would not
    reach the prioritization"""
    segment_departments = repository.get_segment_departments(request_data.idDepartment)
    if request_data.idHospital is not None:
        segment_departments = [
            s for s in segment_departments if s.idHospital == request_data.idHospital
        ]

    if not segment_departments:
        raise ValidationError(
            "Setor sem segmento",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    if len(segment_departments) > 1:
        raise ValidationError(
            "Setor em mais de um hospital: informe o hospital",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    segment_department = segment_departments[0]
    if (
        repository.get_department(
            id_department=segment_department.idDepartment,
            id_hospital=segment_department.idHospital,
        )
        is None
    ):
        raise ValidationError(
            "Setor inexistente",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    return segment_department


def _validate_items(request_data: PrescriptionTestCaseRequest):
    """The drugs, measure units and frequencies must exist: the prescription
    view joins them"""
    items = request_data.items

    missing_drugs = repository.find_missing_drugs(list({i.idDrug for i in items}))
    if missing_drugs:
        raise ValidationError(
            f"Medicamento inexistente: {', '.join(map(str, sorted(missing_drugs)))}",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    measure_units = list({i.measureUnit for i in items if i.measureUnit})
    missing_units = (
        repository.find_missing_measure_units(measure_units) if measure_units else set()
    )
    if missing_units:
        raise ValidationError(
            f"Unidade de medida inexistente: {', '.join(sorted(missing_units))}",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )

    frequencies = list({i.frequency for i in items if i.frequency})
    missing_frequencies = (
        repository.find_missing_frequencies(frequencies) if frequencies else set()
    )
    if missing_frequencies:
        raise ValidationError(
            f"Frequência inexistente: {', '.join(sorted(missing_frequencies))}",
            "errors.invalidParams",
            status.HTTP_400_BAD_REQUEST,
        )


def _prescalc(
    schema: str,
    id_prescription: int,
    admission_number: int,
    prescription_date: datetime,
    is_cpoe: bool,
):
    """Run prescalc as prescalc central does: as the static user, so the
    maintainer's own features do not change what it computes (and its audit
    is the static user's, as for the hospital's prescriptions). The
    maintainer's permission was already checked by this service"""
    static_user = User()
    static_user.id = 0
    static_user.schema = schema
    static_user.config = {"roles": ["STATIC_USER"]}

    if is_cpoe:
        prescription_agg_service.create_agg_prescription_by_date(
            schema=schema,
            admission_number=admission_number,
            p_date=prescription_date.date(),
            user_context=static_user,
        )
    else:
        prescription_agg_service.create_agg_prescription_by_prescription(
            schema=schema,
            id_prescription=id_prescription,
            user_context=static_user,
        )


def _prescription_day_id(
    admission_number: int, id_segment: int, prescription_date: datetime, is_cpoe: bool
):
    """The prescription-day prescalc puts a new prescription in"""
    if not is_cpoe and memory_service.has_feature_nouser(
        FeatureEnum.PRIMARY_CARE.value
    ):
        return admission_number

    return prescriptionutils.gen_agg_id(admission_number, id_segment, prescription_date)
