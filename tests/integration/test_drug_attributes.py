"""Integration tests for drug attributes management (``/drugs/attributes`` and
``/drugs/substance``).

Exercises ``drug_service.get_attributes``, ``drug_service.save_attributes``,
``drug_service.update_substance`` and, indirectly,
``drug_service.copy_substance_default_attributes`` — the flow a curator uses to
bind a drug to a substance and let the substance's curated defaults propagate to
every segment. None of these endpoints had prior coverage.

Fixtures use the reserved ``>= 90000`` id range so the session-scoped
``clean_test_artifacts`` fixture removes them afterwards.
"""

import pytest
from sqlalchemy import text

from models.enums import DrugAttributesAuditTypeEnum, SubstanceTagEnum
from models.main import Drug, DrugAttributes, DrugAttributesAudit, Substance
from tests.conftest import session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_outlier,
    create_test_substance,
)

# Ids reserved for this module (90100 block, distinct from other modules' ranges).
_SCTID_TAGGED = 90101
_SCTID_PLAIN = 90102
_SCTID_INACTIVE = 90103

_DRUG_ATTRIBUTES = 90101  # receives the save/get attribute calls
_DRUG_NO_ATTRIBUTES = 90102  # never gets a medatributos row
_DRUG_SUBSTANCE = 90103  # has its substance replaced

_OUTLIER_SUBSTANCE = 90103  # makes _DRUG_SUBSTANCE visible to the admin drug list

_UNKNOWN_DRUG = 90199
_UNKNOWN_SCTID = 90199
_UNAUTHORIZED_SEGMENT = 3  # the demo user is only authorized on segments 1 and 2

# Curated values carried by _SCTID_TAGGED, mirrored into every segment on update.
_REFERENCE_TAGS = [
    SubstanceTagEnum.ANTIMICRO.value,
    SubstanceTagEnum.CONTROLLED.value,
    SubstanceTagEnum.DIALYZABLE.value,
]
_REFERENCE_KIDNEY_ADULT = 30
_REFERENCE_LIVER_ADULT = 40
_REFERENCE_PLATELETS = 50
_REFERENCE_FALL_RISK = 2
_REFERENCE_ADMIN_TEXT = "Curadoria de teste"


@pytest.fixture(scope="module", autouse=True)
def setup_drug_attributes_data(clean_test_artifacts):  # noqa: ARG001
    """Create the substances and drugs used by this module, after the global cleanup."""
    create_test_substance(_SCTID_TAGGED, "ZZTest Substância Curada", "mg")
    create_test_substance(_SCTID_PLAIN, "ZZTest Substância Simples", "mg")
    create_test_substance(_SCTID_INACTIVE, "ZZTest Substância Inativa", "mg")

    session.execute(
        text(
            "UPDATE public.substancia SET tags = :tags, renal_adulto = :kidney,"
            " hepatico_adulto = :liver, plaquetas = :platelets, risco_queda = :fall_risk,"
            " curadoria = :admin_text WHERE sctid = :sctid"
        ),
        {
            "tags": _REFERENCE_TAGS,
            "kidney": _REFERENCE_KIDNEY_ADULT,
            "liver": _REFERENCE_LIVER_ADULT,
            "platelets": _REFERENCE_PLATELETS,
            "fall_risk": _REFERENCE_FALL_RISK,
            "admin_text": _REFERENCE_ADMIN_TEXT,
            "sctid": _SCTID_TAGGED,
        },
    )
    session.execute(
        text("UPDATE public.substancia SET ativo = false WHERE sctid = :sctid"),
        {"sctid": _SCTID_INACTIVE},
    )
    session_commit()

    create_test_drug(_DRUG_ATTRIBUTES, "ZZTest Medicamento Atributos", _SCTID_TAGGED)
    create_test_drug(_DRUG_NO_ATTRIBUTES, "ZZTest Medicamento Sem Atributos", None)
    create_test_drug(_DRUG_SUBSTANCE, "ZZTest Medicamento Substância", None)
    # the admin drug list is driven by the outlier table
    create_test_outlier(_OUTLIER_SUBSTANCE, _DRUG_SUBSTANCE, id_segment=1)


def _read_attributes(id_drug: int, id_segment: int = 1) -> DrugAttributes:
    """Return a fresh copy of a medatributos row (commit first to drop any snapshot)."""
    session_commit()
    return (
        session.query(DrugAttributes)
        .filter(DrugAttributes.idDrug == id_drug)
        .filter(DrugAttributes.idSegment == id_segment)
        .first()
    )


def _audit_types(id_drug: int) -> list[int]:
    """Return the audit types recorded for a drug, oldest first."""
    session_commit()
    return [
        a.auditType
        for a in session.query(DrugAttributesAudit)
        .filter(DrugAttributesAudit.idDrug == id_drug)
        .order_by(DrugAttributesAudit.id)
        .all()
    ]


def test_get_attributes_without_record_returns_only_drug_ref(client, analyst_headers):
    """GET /drugs/attributes - drug without medatributos returns just the reference text"""
    response = client.get(
        f"/drugs/attributes/1/{_DRUG_NO_ATTRIBUTES}", headers=analyst_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"] == {"drugRef": None}


def test_get_attributes_unknown_drug_returns_400(client, analyst_headers):
    """GET /drugs/attributes - unknown drug is rejected [400 BAD REQUEST]"""
    response = client.get(
        f"/drugs/attributes/1/{_UNKNOWN_DRUG}", headers=analyst_headers
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.invalidParams"


def test_save_attributes_creates_record_and_audit(client, config_manager_headers):
    """POST /drugs/attributes - first save inserts the row and an UPSERT audit entry"""
    response = client.post(
        "/drugs/attributes",
        headers=config_manager_headers,
        json={
            "idDrug": _DRUG_ATTRIBUTES,
            "idSegment": 1,
            "antimicro": True,
            "mav": True,
            "controlled": False,
            "idMeasureUnit": "mg",
            "maxDose": 500,
            "kidney": 30,
            "liver": 40,
            "platelets": 50,
            "elderly": True,
            "chemo": False,
            "tube": True,
            "maxTime": 7,
            "fallRisk": 2,
            "useWeight": True,
            "amount": 10,
            "amountUnit": "mg",
            "price": 1.5,
            "dialyzable": True,
            "pregnant": "A",
            "lactating": "B",
            "fasting": True,
        },
    )

    assert response.status_code == 200

    attributes = _read_attributes(_DRUG_ATTRIBUTES)
    assert attributes is not None
    assert attributes.antimicro is True
    assert attributes.mav is True
    assert attributes.controlled is False
    assert attributes.idMeasureUnit == "mg"
    assert attributes.maxDose == 500
    assert attributes.kidney == 30
    assert attributes.liver == 40
    assert attributes.platelets == 50
    assert attributes.tube is True
    assert attributes.maxTime == 7
    assert attributes.fallRisk == 2
    assert attributes.useWeight is True
    assert attributes.amount == 10
    assert attributes.amountUnit == "mg"
    assert attributes.price == 1.5
    assert attributes.dialyzable is True
    assert attributes.pregnant == "A"
    assert attributes.lactating == "B"
    assert attributes.fasting is True
    # the save stamps the responsible user
    assert attributes.user is not None
    assert attributes.update is not None

    assert DrugAttributesAuditTypeEnum.UPSERT.value in _audit_types(_DRUG_ATTRIBUTES)


def test_save_attributes_only_updates_submitted_fields(client, config_manager_headers):
    """POST /drugs/attributes - fields absent from the payload keep their stored value"""
    response = client.post(
        "/drugs/attributes",
        headers=config_manager_headers,
        json={"idDrug": _DRUG_ATTRIBUTES, "idSegment": 1, "antimicro": False},
    )

    assert response.status_code == 200

    attributes = _read_attributes(_DRUG_ATTRIBUTES)
    assert attributes.antimicro is False
    # untouched by this request
    assert attributes.mav is True
    assert attributes.maxDose == 500
    assert attributes.idMeasureUnit == "mg"


def test_save_attributes_converts_empty_strings_to_null(client, config_manager_headers):
    """POST /drugs/attributes - numeric fields sent as empty strings are stored as NULL"""
    response = client.post(
        "/drugs/attributes",
        headers=config_manager_headers,
        json={
            "idDrug": _DRUG_ATTRIBUTES,
            "idSegment": 1,
            "maxDose": "",
            "kidney": "",
            "liver": "",
            "platelets": "",
            "price": "",
            "amount": "",
            "whiteList": "",
        },
    )

    assert response.status_code == 200

    attributes = _read_attributes(_DRUG_ATTRIBUTES)
    assert attributes.maxDose is None
    assert attributes.kidney is None
    assert attributes.liver is None
    assert attributes.platelets is None
    assert attributes.price is None
    assert attributes.amount is None
    assert attributes.whiteList is None


def test_get_attributes_returns_saved_values_and_sctid(client, analyst_headers):
    """GET /drugs/attributes - returns the stored attributes plus the drug's sctid"""
    response = client.get(
        f"/drugs/attributes/1/{_DRUG_ATTRIBUTES}", headers=analyst_headers
    )

    assert response.status_code == 200

    data = response.get_json()["data"]
    assert data["sctid"] == str(_SCTID_TAGGED)
    assert data["antimicro"] is False
    assert data["mav"] is True
    assert data["dialyzable"] is True
    assert data["amountUnit"] == "mg"
    # a plain analyst has no ADMIN_DRUGS permission, so no curation text is exposed
    assert data["drugRef"] is None


def test_get_attributes_exposes_drug_ref_to_admin_drugs(client, curator_headers):
    """GET /drugs/attributes - ADMIN_DRUGS users also get the substance curation text"""
    response = client.get(
        f"/drugs/attributes/1/{_DRUG_ATTRIBUTES}", headers=curator_headers
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["drugRef"] == _REFERENCE_ADMIN_TEXT


def test_save_attributes_requires_drug_and_segment(client, config_manager_headers):
    """POST /drugs/attributes - missing idDrug/idSegment is rejected [400 BAD REQUEST]"""
    response = client.post(
        "/drugs/attributes",
        headers=config_manager_headers,
        json={"idSegment": 1, "antimicro": True},
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.invalidParams"


def test_save_attributes_rejects_unauthorized_segment(client, config_manager_headers):
    """POST /drugs/attributes - a segment the user is not authorized on [401 UNAUTHORIZED]"""
    response = client.post(
        "/drugs/attributes",
        headers=config_manager_headers,
        json={
            "idDrug": _DRUG_ATTRIBUTES,
            "idSegment": _UNAUTHORIZED_SEGMENT,
            "antimicro": True,
        },
    )

    assert response.status_code == 401
    assert _read_attributes(_DRUG_ATTRIBUTES, _UNAUTHORIZED_SEGMENT) is None


def test_save_attributes_requires_write_permission(client, analyst_headers):
    """POST /drugs/attributes - user without WRITE_DRUG_ATTRIBUTES [401 UNAUTHORIZED]"""
    response = client.post(
        "/drugs/attributes",
        headers=analyst_headers,
        json={"idDrug": _DRUG_ATTRIBUTES, "idSegment": 1, "antimicro": True},
    )

    assert response.status_code == 401


def test_update_substance_copies_reference_to_every_segment(
    client, config_manager_headers
):
    """POST /drugs/substance - binds the substance and mirrors its defaults per segment"""
    response = client.post(
        "/drugs/substance",
        headers=config_manager_headers,
        json={"idDrug": _DRUG_SUBSTANCE, "sctid": _SCTID_TAGGED},
    )

    assert response.status_code == 200

    # the endpoint answers with the refreshed admin drug list for that drug
    drug_list = response.get_json()["data"]["list"]
    assert [d["idDrug"] for d in drug_list] == [str(_DRUG_SUBSTANCE)]
    assert drug_list[0]["sctid"] == str(_SCTID_TAGGED)

    session_commit()
    drug = session.query(Drug).filter(Drug.id == _DRUG_SUBSTANCE).first()
    assert drug.sctid == _SCTID_TAGGED
    # the manual binding invalidates any AI-suggested match
    assert drug.ai_accuracy is None
    assert drug.updated_by is not None

    segment_ids = [1, 2]
    for id_segment in segment_ids:
        attributes = _read_attributes(_DRUG_SUBSTANCE, id_segment)
        assert attributes is not None, f"no attributes created for segment {id_segment}"
        # tags present on the substance become boolean flags
        assert attributes.antimicro is True
        assert attributes.controlled is True
        assert attributes.dialyzable is True
        # tags absent from the substance are cleared
        assert attributes.mav is False
        assert attributes.chemo is False
        assert attributes.tube is False
        # both seed segments are adult, so the adult reference values are used
        assert attributes.kidney == _REFERENCE_KIDNEY_ADULT
        assert attributes.liver == _REFERENCE_LIVER_ADULT
        assert attributes.platelets == _REFERENCE_PLATELETS
        assert attributes.fallRisk == _REFERENCE_FALL_RISK

    assert DrugAttributesAuditTypeEnum.UPSERT_UPDATE_SUBSTANCE.value in _audit_types(
        _DRUG_SUBSTANCE
    )


def test_update_substance_overwrites_previous_binding(client, config_manager_headers):
    """POST /drugs/substance - rebinding to another substance clears the copied flags"""
    response = client.post(
        "/drugs/substance",
        headers=config_manager_headers,
        json={"idDrug": _DRUG_SUBSTANCE, "sctid": _SCTID_PLAIN},
    )

    assert response.status_code == 200

    session_commit()
    drug = session.query(Drug).filter(Drug.id == _DRUG_SUBSTANCE).first()
    assert drug.sctid == _SCTID_PLAIN

    attributes = _read_attributes(_DRUG_SUBSTANCE, 1)
    # the new substance carries no tags nor clinical references
    assert attributes.antimicro is False
    assert attributes.controlled is False
    assert attributes.dialyzable is False
    assert attributes.kidney is None
    assert attributes.liver is None


def test_update_substance_rejects_missing_sctid(client, config_manager_headers):
    """POST /drugs/substance - a null substance is rejected [400 BAD REQUEST]"""
    response = client.post(
        "/drugs/substance",
        headers=config_manager_headers,
        json={"idDrug": _DRUG_SUBSTANCE, "sctid": None},
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_update_substance_rejects_inactive_substance(client, config_manager_headers):
    """POST /drugs/substance - an inactive substance is rejected [400 BAD REQUEST]"""
    response = client.post(
        "/drugs/substance",
        headers=config_manager_headers,
        json={"idDrug": _DRUG_SUBSTANCE, "sctid": _SCTID_INACTIVE},
    )

    assert response.status_code == 400

    session_commit()
    drug = session.query(Drug).filter(Drug.id == _DRUG_SUBSTANCE).first()
    assert drug.sctid == _SCTID_PLAIN


def test_update_substance_rejects_unknown_substance(client, config_manager_headers):
    """POST /drugs/substance - a substance that does not exist [400 BAD REQUEST]"""
    response = client.post(
        "/drugs/substance",
        headers=config_manager_headers,
        json={"idDrug": _DRUG_SUBSTANCE, "sctid": _UNKNOWN_SCTID},
    )

    assert response.status_code == 400
    assert (
        session.query(Substance).filter(Substance.id == _UNKNOWN_SCTID).first() is None
    )


def test_update_substance_rejects_unknown_drug(client, config_manager_headers):
    """POST /drugs/substance - a drug that does not exist [400 BAD REQUEST]"""
    response = client.post(
        "/drugs/substance",
        headers=config_manager_headers,
        json={"idDrug": _UNKNOWN_DRUG, "sctid": _SCTID_PLAIN},
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_update_substance_requires_write_permission(client, analyst_headers):
    """POST /drugs/substance - user without WRITE_DRUG_ATTRIBUTES [401 UNAUTHORIZED]"""
    response = client.post(
        "/drugs/substance",
        headers=analyst_headers,
        json={"idDrug": _DRUG_SUBSTANCE, "sctid": _SCTID_TAGGED},
    )

    assert response.status_code == 401
