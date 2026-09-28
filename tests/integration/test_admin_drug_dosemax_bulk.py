"""Integration tests for the bulk max-dose calculation endpoint.

``POST /admin/drug/calculate-dosemax``
(``admin_drug_service.calculate_dosemax_bulk``) is the button that applies the
shared substance catalog's reference max doses to a whole schema at once. It
had no coverage at all, and it is the only caller of
``drug_attributes_repository.update_dose_max`` and
``drug_attributes_repository.copy_dose_max_from_ref`` — two hand-written SQL
statements that no test ever executed, so a typo in either one only showed up
in production.

The endpoint walks every ``medatributos`` row that has a substance and sorts it
into one of three outcomes:

* ``converted`` — the substance carries a reference dose *and* the drug has a
  measure-unit conversion factor for the segment, so the reference (always
  expressed in the substance's default unit) can be restated in the unit the
  drug is prescribed in. The converted values are written to the two reference
  columns by ``update_dose_max``;
* ``not_converted`` — there is a reference dose but no factor to apply it
  through, so nothing is written;
* ``no_reference`` — the substance has no reference dose at all.

``copy_dose_max_from_ref`` then promotes the reference to the max dose actually
used by the alerts, and this is the rule the tests care about most: it only
touches rows whose ``dosemaxima`` is still empty (or was last written by
internal staff), so a value a curator typed by hand survives the bulk run.
Which reference is promoted depends on ``usapeso``.

Fixtures use the reserved ``>= 90000`` id range (91600 block) so the
session-scoped ``clean_test_artifacts`` fixture removes them. The measure unit
falls outside that window, so this module removes it on teardown.

The endpoint writes to every row of the schema, so the assertions below read
back the module's own rows rather than trusting the counters alone; the
counters are only asserted to include this module's contribution.

The calculation runs once for the whole module (``bulk_result``) and the tests
then read the rows it left behind, so they stay independent of each other: a
second run is a no-op on the rows this module owns, which is what
``test_bulk_calculation_is_idempotent`` asserts.
"""

import pytest
from sqlalchemy import text

from mobile import app
from models.main import DrugAttributes
from tests.conftest import get_access, make_headers, session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_substance,
)
from utils import status

URL = "/admin/drug/calculate-dosemax"

_SEGMENT = 1

# the ADMIN user the module calls the endpoint as
CALLER_EMAIL = "user@admin.com"
CALLER_PASSWORD = "useradmin"
CALLER_ID = 2
# a different real user, used to mark a row as curated by hand
_OTHER_USER_ID = 1

# Ids reserved for this module (91600 block, distinct from other modules').
_SCTID_REF = 91601  # carries the reference max doses
_SCTID_PLAIN = 91602  # no reference dose at all

_DRUG_CONVERTED = 91601  # reference + factor, dosemaxima still empty
_DRUG_WEIGHT = 91602  # same, but usapeso picks the by-weight reference
_DRUG_NOT_CONVERTED = 91603  # reference but no factor for the segment
_DRUG_NO_REFERENCE = 91604  # substance without any reference dose
_DRUG_CURATED = 91605  # dosemaxima already typed by a curator

# Reference doses carried by _SCTID_REF, in the substance's default unit.
_REF_MAXDOSE = 100.0
_REF_MAXDOSE_WEIGHT = 5.0
# the factor the references are converted through
_FACTOR = 2.0
# the max dose a curator typed by hand on _DRUG_CURATED
_CURATED_MAXDOSE = 42.0

# A measure unit of our own, mapped onto the NoHarm "mg" the substances default
# to: the conversion is looked up by ``unidademedida_nh``, and no seed unit has
# it filled in.
_MEASURE_UNIT = "ZZDMXMG"

_DRUGS_WITH_REFERENCE = [
    (_DRUG_CONVERTED, "ZZTest Medicamento Dosemax Convertido"),
    (_DRUG_WEIGHT, "ZZTest Medicamento Dosemax Peso"),
    (_DRUG_NOT_CONVERTED, "ZZTest Medicamento Dosemax Sem Fator"),
    (_DRUG_CURATED, "ZZTest Medicamento Dosemax Curado"),
]


@pytest.fixture(scope="module", autouse=True)
def setup_dosemax_bulk_data(clean_test_artifacts):  # noqa: ARG001
    """Create the substances, drugs and the measure unit, after the global cleanup.

    The substance names deliberately avoid the ``ZZTest Subs`` prefix that
    ``test_admin_substance.py`` isolates its own listing on — this module runs
    before it, so a matching name would leak into its assertions.
    """
    create_test_substance(_SCTID_REF, "ZZTest Dosemax Substancia", "mg")
    create_test_substance(_SCTID_PLAIN, "ZZTest Dosemax Substancia Sem Ref", "mg")

    session.execute(
        text(
            "UPDATE public.substancia SET dosemax_adulto = :maxdose,"
            " dosemax_peso_adulto = :maxdose_weight WHERE sctid = :sctid"
        ),
        {
            "maxdose": _REF_MAXDOSE,
            "maxdose_weight": _REF_MAXDOSE_WEIGHT,
            "sctid": _SCTID_REF,
        },
    )

    session.execute(
        text(
            "INSERT INTO demo.unidademedida"
            " (fkunidademedida, fkhospital, nome, unidademedida_nh)"
            " VALUES (:id, 1, :name, 'mg')"
            " ON CONFLICT (fkhospital, fkunidademedida) DO NOTHING"
        ),
        {"id": _MEASURE_UNIT, "name": _MEASURE_UNIT},
    )
    session_commit()

    for id_drug, name in _DRUGS_WITH_REFERENCE:
        create_test_drug(id_drug, name, _SCTID_REF)

    create_test_drug(
        _DRUG_NO_REFERENCE, "ZZTest Medicamento Dosemax Sem Substancia", _SCTID_PLAIN
    )

    # one medatributos row per drug: only the curated one starts with a max dose
    for id_drug, use_weight, max_dose, update_by in (
        (_DRUG_CONVERTED, False, None, None),
        (_DRUG_WEIGHT, True, None, None),
        (_DRUG_NOT_CONVERTED, False, None, None),
        (_DRUG_NO_REFERENCE, False, None, None),
        (_DRUG_CURATED, False, _CURATED_MAXDOSE, _OTHER_USER_ID),
    ):
        session.execute(
            text(
                "INSERT INTO demo.medatributos"
                " (fkmedicamento, idsegmento, usapeso, dosemaxima, update_by)"
                " VALUES (:id_drug, :id_segment, :use_weight, :max_dose, :update_by)"
            ),
            {
                "id_drug": id_drug,
                "id_segment": _SEGMENT,
                "use_weight": use_weight,
                "max_dose": max_dose,
                "update_by": update_by,
            },
        )

    # every drug but _DRUG_NOT_CONVERTED can be converted
    for id_drug in (_DRUG_CONVERTED, _DRUG_WEIGHT, _DRUG_NO_REFERENCE, _DRUG_CURATED):
        session.execute(
            text(
                "INSERT INTO demo.unidadeconverte"
                " (idsegmento, fkmedicamento, fkunidademedida, fator)"
                " VALUES (:id_segment, :id_drug, :unit, :factor)"
            ),
            {
                "id_segment": _SEGMENT,
                "id_drug": id_drug,
                "unit": _MEASURE_UNIT,
                "factor": _FACTOR,
            },
        )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM demo.unidademedida WHERE fkunidademedida = :id"),
        {"id": _MEASURE_UNIT},
    )
    session_commit()


@pytest.fixture(scope="module")
def bulk_result(setup_dosemax_bulk_data):  # noqa: ARG001
    """Run the bulk calculation once and hand its payload to every test.

    The shared ``client``/``admin_headers`` fixtures are function-scoped, so
    this one builds its own client to keep the calculation to a single run for
    the whole module.
    """
    module_client = app.test_client()
    headers = make_headers(
        get_access(module_client, email=CALLER_EMAIL, password=CALLER_PASSWORD)
    )

    response = module_client.post(URL, headers=headers)
    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"]


def _attributes(id_drug: int) -> DrugAttributes:
    """Read one medatributos row back from the database."""
    session.expire_all()
    return (
        session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idSegment == _SEGMENT)
        .first()
    )


def test_bulk_calculation_reports_each_outcome(bulk_result):
    """Cálculo em massa da dose máxima: relata convertidos, não convertidos e sem referência"""
    # other modules may have left rows of their own behind, so the counters are
    # asserted to include this module's rows rather than to equal them
    assert bulk_result["converted"] >= 3  # converted, weight and curated
    assert bulk_result["notConverted"] >= 1
    assert bulk_result["noReference"] >= 1
    assert bulk_result["updated"] >= 2  # curated keeps the dose a human typed


def test_bulk_calculation_converts_the_reference_dose(bulk_result):  # noqa: ARG001
    """Cálculo em massa da dose máxima: converte a dose de referência pelo fator do medicamento"""
    attributes = _attributes(_DRUG_CONVERTED)

    assert attributes.ref_maxdose == _REF_MAXDOSE * _FACTOR
    assert attributes.ref_maxdose_weight == _REF_MAXDOSE_WEIGHT * _FACTOR
    # the row had no max dose, so the reference is promoted
    assert attributes.maxDose == _REF_MAXDOSE * _FACTOR
    assert attributes.user == CALLER_ID


def test_bulk_calculation_uses_the_by_weight_reference_when_the_drug_uses_weight(
    bulk_result,  # noqa: ARG001
):
    """Cálculo em massa da dose máxima: usa a referência por peso quando o medicamento usa peso"""
    attributes = _attributes(_DRUG_WEIGHT)

    assert attributes.ref_maxdose == _REF_MAXDOSE * _FACTOR
    assert attributes.ref_maxdose_weight == _REF_MAXDOSE_WEIGHT * _FACTOR
    assert attributes.maxDose == _REF_MAXDOSE_WEIGHT * _FACTOR


def test_bulk_calculation_skips_a_drug_without_a_conversion_factor(
    bulk_result,  # noqa: ARG001
):
    """Cálculo em massa da dose máxima: ignora o medicamento sem fator de conversão"""
    attributes = _attributes(_DRUG_NOT_CONVERTED)

    assert attributes.ref_maxdose is None
    assert attributes.ref_maxdose_weight is None
    assert attributes.maxDose is None


def test_bulk_calculation_skips_a_substance_without_a_reference(
    bulk_result,  # noqa: ARG001
):
    """Cálculo em massa da dose máxima: ignora a substância sem dose de referência"""
    attributes = _attributes(_DRUG_NO_REFERENCE)

    assert attributes.ref_maxdose is None
    assert attributes.ref_maxdose_weight is None
    assert attributes.maxDose is None


def test_bulk_calculation_keeps_a_max_dose_a_curator_typed(bulk_result):  # noqa: ARG001
    """Cálculo em massa da dose máxima: preserva a dose máxima definida por um curador"""
    attributes = _attributes(_DRUG_CURATED)

    # the reference columns are always refreshed
    assert attributes.ref_maxdose == _REF_MAXDOSE * _FACTOR
    assert attributes.ref_maxdose_weight == _REF_MAXDOSE_WEIGHT * _FACTOR
    # but the curated max dose and its author are left alone
    assert attributes.maxDose == _CURATED_MAXDOSE
    assert attributes.user == _OTHER_USER_ID


def test_bulk_calculation_is_idempotent(client, admin_headers, bulk_result):  # noqa: ARG001
    """Cálculo em massa da dose máxima: uma segunda execução não repromove as doses já aplicadas"""
    # the rows this module owns now carry a max dose written by CALLER_ID, whose
    # schema is not the internal one, so they are out of reach of a second run
    converted_before = _attributes(_DRUG_CONVERTED).maxDose

    response = client.post(URL, headers=admin_headers)
    assert response.status_code == status.HTTP_200_OK

    assert _attributes(_DRUG_CONVERTED).maxDose == converted_before
    assert _attributes(_DRUG_CURATED).maxDose == _CURATED_MAXDOSE


def test_bulk_calculation_requires_the_admin_drugs_permission(client, viewer_headers):
    """Cálculo em massa da dose máxima: recusa o usuário sem permissão de administrar medicamentos"""
    response = client.post(URL, headers=viewer_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
