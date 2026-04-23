"""Tests: GET /admin/unit-conversion/list"""

import pytest

from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_drug_attributes,
    create_test_measure_unit,
    create_test_measure_unit_convert,
    create_test_outlier,
    create_test_prescription_agg,
    create_test_substance,
)
from utils import status

URL = "/admin/unit-conversion/list"

# ---------------------------------------------------------------------------
# Test substance / drug IDs reserved for this module (>= 90000 range).
# Keep them distinct across tests to avoid cross-test interference.
# ---------------------------------------------------------------------------
_DRUG_NO_OUTLIER = 90001
_DRUG_BASIC = 90002
_DRUG_SYNTHETIC = 90003
_DRUG_DEFAULT_UNIT = 90004
_DRUG_NON_UNIFORM = 90005
_DRUG_UNIFORM_WITH_CONVERSIONS = 90006
_DRUG_NO_DEFAULT_UNIT = 90007

_SCTID_NO_OUTLIER = 90001
_SCTID_BASIC = 90002
_SCTID_SYNTHETIC = 90003
_SCTID_DEFAULT_UNIT = 90004
_SCTID_NON_UNIFORM = 90005
_SCTID_NO_DEFAULT_UNIT = 90006

_OUTLIER_BASE_ID = 90001


@pytest.fixture(scope="session", autouse=True)
def setup_unit_conversion_test_data(clean_test_artifacts):  # noqa: ARG001
    """Create all test records after the global cleanup fixture has run."""
    create_test_measure_unit("mg", "Miligrama", "mg")
    create_test_measure_unit("MILIGRAMA", "Miligrama", "mg")
    create_test_measure_unit("ml", "Mililitro", "ml")

    # --- Drug 90001: substance + prescribed unit, but NO outlier ---
    create_test_substance(_SCTID_NO_OUTLIER, "Test Drug No Outlier", "mg")
    create_test_drug(_DRUG_NO_OUTLIER, "Test Drug No Outlier", _SCTID_NO_OUTLIER)
    create_test_prescription_agg(_DRUG_NO_OUTLIER, "mg")

    # --- Drug 90002: basic success case ---
    create_test_substance(_SCTID_BASIC, "Test Drug Basic", "mg")
    create_test_drug(_DRUG_BASIC, "Test Drug Basic", _SCTID_BASIC)
    create_test_outlier(_OUTLIER_BASE_ID, _DRUG_BASIC)
    create_test_prescription_agg(_DRUG_BASIC, "mg", id_department=1, dose=200.0)

    # --- Drug 90003: synthetic default-unit entry (prescribed in ml, default is mg) ---
    create_test_substance(_SCTID_SYNTHETIC, "Test Drug Synthetic", "mg")
    create_test_drug(_DRUG_SYNTHETIC, "Test Drug Synthetic", _SCTID_SYNTHETIC)
    create_test_outlier(_OUTLIER_BASE_ID + 1, _DRUG_SYNTHETIC)
    create_test_prescription_agg(_DRUG_SYNTHETIC, "ml", id_department=1, dose=50.0)
    create_test_prescription_agg(
        _DRUG_SYNTHETIC, "MILIGRAMA", id_department=1, dose=50.0
    )

    # --- Drug 90004: uniform=True + is_default_unit=True → factor=1, prediction=100 ---
    create_test_substance(_SCTID_DEFAULT_UNIT, "Test Drug Default Unit", "mg")
    create_test_drug(_DRUG_DEFAULT_UNIT, "Test Drug Default Unit", _SCTID_DEFAULT_UNIT)
    create_test_outlier(_OUTLIER_BASE_ID + 2, _DRUG_DEFAULT_UNIT)
    create_test_prescription_agg(_DRUG_DEFAULT_UNIT, "mg", id_department=1, dose=10.0)
    # Single DrugAttributes entry with idMeasureUnit='mg' → distinct_units_count=1,
    # measureunit_nh='mg' (set by ensure_default_measure_units) == default_measureunit='mg'
    create_test_drug_attributes(_DRUG_DEFAULT_UNIT, id_segment=1, id_measure_unit="mg")

    # --- Drug 90005: no DrugAttributes → uniform_measure_unit=False; prescribed in
    #     a non-default unit ('ml') → is_default_unit=False → factor=None ---
    create_test_substance(_SCTID_NON_UNIFORM, "Test Drug Non Uniform", "mg")
    create_test_drug(_DRUG_NON_UNIFORM, "Test Drug Non Uniform", _SCTID_NON_UNIFORM)
    create_test_outlier(_OUTLIER_BASE_ID + 3, _DRUG_NON_UNIFORM)
    create_test_drug_attributes(_DRUG_NON_UNIFORM, id_segment=1, id_measure_unit="mg")
    create_test_drug_attributes(_DRUG_NON_UNIFORM, id_segment=2, id_measure_unit="ml")
    # Prescribed in 'ml' (non-default); no DrugAttributes configured
    create_test_prescription_agg(_DRUG_NON_UNIFORM, "ml", id_department=1, dose=30.0)
    create_test_measure_unit_convert(
        _DRUG_NON_UNIFORM,
        "ml",
        id_segment=1,
        factor=1,
    )
    create_test_measure_unit_convert(
        _DRUG_NON_UNIFORM,
        "mg",
        id_segment=1,
        factor=1,
    )

    # --- Drug 90006: uniform and with saved conversions
    create_test_substance(_SCTID_BASIC, "Test Drug Uniform With Conversions", "mg")
    create_test_drug(
        _DRUG_UNIFORM_WITH_CONVERSIONS,
        "Test Drug Uniform With Conversions",
        _SCTID_BASIC,
    )
    create_test_outlier(_OUTLIER_BASE_ID + 4, _DRUG_UNIFORM_WITH_CONVERSIONS)
    create_test_prescription_agg(
        _DRUG_UNIFORM_WITH_CONVERSIONS, "ml", id_department=1, dose=50.0
    )
    create_test_prescription_agg(
        _DRUG_UNIFORM_WITH_CONVERSIONS, "MILIGRAMA", id_department=1, dose=50.0
    )
    create_test_measure_unit_convert(
        _DRUG_UNIFORM_WITH_CONVERSIONS,
        "ml",
        id_segment=1,
        factor=1000.0,
    )
    create_test_measure_unit_convert(
        _DRUG_UNIFORM_WITH_CONVERSIONS,
        "MILIGRAMA",
        id_segment=1,
        factor=1,
    )
    create_test_measure_unit_convert(
        _DRUG_UNIFORM_WITH_CONVERSIONS,
        "mg",
        id_segment=1,
        factor=1,
    )
    # DrugAttributes with idMeasureUnit="mg" → distinct_units_count=1,
    # measureunit_nh="mg" == default_measureunit="mg" → uniform_measure_unit=True
    create_test_drug_attributes(
        _DRUG_UNIFORM_WITH_CONVERSIONS, id_segment=1, id_measure_unit="mg"
    )

    # --- Drug 90007: substance with no default measure unit → fallback to 'un'
    create_test_substance(_SCTID_NO_DEFAULT_UNIT, "Test Drug No Default Unit", None)
    create_test_drug(
        _DRUG_NO_DEFAULT_UNIT, "Test Drug No Default Unit", _SCTID_NO_DEFAULT_UNIT
    )
    create_test_outlier(_OUTLIER_BASE_ID + 5, _DRUG_NO_DEFAULT_UNIT)
    create_test_prescription_agg(_DRUG_NO_DEFAULT_UNIT, "mg", id_department=1, dose=20.0)


def _drug_items(data: list, id_drug: int) -> list:
    """Filter response items by idDrug."""
    return [item for item in data if item.get("idDrug") == id_drug]


def test_unit_conversion_list_requires_admin(client, analyst_headers):
    """unit-conversion list: analyst (non-admin) receives 401"""
    response = client.post(URL, json={"idSegment": 1}, headers=analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_unit_conversion_list_drug_without_outlier_excluded(client, admin_headers):
    """unit-conversion list: drug with no outlier is excluded from results"""
    response = client.post(URL, json={"idSegment": 1}, headers=admin_headers)
    data = response.get_json()["data"]

    assert response.status_code == status.HTTP_200_OK
    assert _drug_items(data, _DRUG_NO_OUTLIER) == []


def test_unit_conversion_list_basic_success(client, admin_headers):
    """unit-conversion list: drug with outlier and prescribed unit appears in results"""
    response = client.post(URL, json={"idSegment": 1}, headers=admin_headers)
    data = response.get_json()["data"]

    assert response.status_code == status.HTTP_200_OK

    items = _drug_items(data, _DRUG_BASIC)
    assert len(items) > 0

    mg_item = next((i for i in items if i.get("idMeasureUnit") == "mg"), None)
    assert mg_item is not None
    assert mg_item["idDrug"] == _DRUG_BASIC


def test_unit_conversion_list_synthetic_default_unit_entry(client, admin_headers):
    """unit-conversion list: drug prescribed in ml (not its default mg) gets a synthetic mg entry with prediction=1"""
    response = client.post(URL, json={"idSegment": 1}, headers=admin_headers)
    data = response.get_json()["data"]

    assert response.status_code == status.HTTP_200_OK

    items = _drug_items(data, _DRUG_SYNTHETIC)
    measure_units = {i["idMeasureUnit"] for i in items}

    # Prescribed unit must appear
    assert "ml" in measure_units
    assert "MILIGRAMA" in measure_units
    # Synthetic default unit must also appear
    assert "mg" in measure_units

    synthetic = next(i for i in items if i["idMeasureUnit"] == "mg")
    assert synthetic["prediction"] == 1
    assert synthetic["probability"] == 100


def test_unit_conversion_list_default_unit_factor_one(client, admin_headers):
    """unit-conversion list: uniform drug whose prescribed unit equals its substance default gets factor=1 and prediction=100"""
    response = client.post(URL, json={"idSegment": 1}, headers=admin_headers)
    data = response.get_json()["data"]

    assert response.status_code == status.HTTP_200_OK

    items = _drug_items(data, _DRUG_DEFAULT_UNIT)
    mg_item = next((i for i in items if i.get("idMeasureUnit") == "mg"), None)

    assert mg_item is not None
    assert mg_item["factor"] == 1
    assert mg_item["prediction"] == 100
    assert mg_item["probability"] == 100


def test_unit_conversion_list_non_uniform_hides_factor(client, admin_headers):
    """unit-conversion list: drug with no DrugAttributes (uniform=False) prescribed in a non-default unit gets factor=None"""
    response = client.post(URL, json={"idSegment": 1}, headers=admin_headers)
    data = response.get_json()["data"]

    assert response.status_code == status.HTTP_200_OK

    items = _drug_items(data, _DRUG_NON_UNIFORM)
    ml_item = next((i for i in items if i.get("idMeasureUnit") == "ml"), None)
    mg_item = next((i for i in items if i.get("idMeasureUnit") == "mg"), None)

    assert ml_item is not None
    assert ml_item["factor"] is None

    assert mg_item is not None
    assert mg_item["factor"] == 1


def test_unit_conversion_list_uniform_with_saved_conversions(client, admin_headers):
    """unit-conversion list: uniform drug with saved conversions returns correct factors"""
    response = client.post(URL, json={"idSegment": 1}, headers=admin_headers)
    data = response.get_json()["data"]

    assert response.status_code == status.HTTP_200_OK

    items = _drug_items(data, _DRUG_UNIFORM_WITH_CONVERSIONS)
    measure_units = {i["idMeasureUnit"] for i in items}

    # All prescribed and saved units must appear
    assert "ml" in measure_units
    assert "MILIGRAMA" in measure_units
    assert "mg" in measure_units

    # Non-default unit: saved factor must be returned (drug is uniform)
    ml_item = next(i for i in items if i["idMeasureUnit"] == "ml")
    assert ml_item["factor"] == 1000.0

    # Units whose measureunit_nh equals the substance default are treated as default → factor=1
    miligrama_item = next(i for i in items if i["idMeasureUnit"] == "MILIGRAMA")
    assert miligrama_item["factor"] == 1

    mg_item = next(i for i in items if i["idMeasureUnit"] == "mg")
    assert mg_item["factor"] == 1


def test_unit_conversion_list_no_substance_default_unit_falls_back_to_un(
    client, admin_headers
):
    """unit-conversion list: drug whose substance has no default unit gets a synthetic 'un' entry"""
    response = client.post(URL, json={"idSegment": 1}, headers=admin_headers)
    data = response.get_json()["data"]

    assert response.status_code == status.HTTP_200_OK

    items = _drug_items(data, _DRUG_NO_DEFAULT_UNIT)
    measure_units = {i["idMeasureUnit"] for i in items}

    # Prescribed unit must appear
    assert "mg" in measure_units
    # Synthetic fallback default 'un' must also appear
    assert "un" in measure_units

    un_item = next(i for i in items if i["idMeasureUnit"] == "un")
    assert un_item["factor"] == 1
    assert un_item["prediction"] == 1
    assert un_item["probability"] == 100
