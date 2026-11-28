"""Integration tests: the culture card with cultures to show

GET /prescriptions/<id>/cultures serves the antibiogram summary of the patient
(DynamoDB, noharm_cultura_resumo) to the culture card, enriched on the way:

* ``prescribed``: whether the substance the lab tested is in the drug list the
  alerts read (alert_service.flag_prescribed_cultures);
* ``atbLevel``: the AWaRe level of that substance (substancia.tp_nivel_atb),
  read in one query (culture_service.flag_antimicrobial_levels);
* the mapping fields the card never reads (``sctid``, ``idSubstanceClass``,
  ``idExamItem``) are dropped (culture_service.to_card).

test_prescription_cultures.py only reaches the empty answer: DynamoDB is
skipped in the TEST env. Here the DynamoDB read is replaced by a summary of
fictitious items and the CULTURE feature is turned on, so the whole card
pipeline runs against the seed prescription and the database.
"""

from decimal import Decimal
from unittest.mock import patch

import pytest
from sqlalchemy import text

from models.enums import (
    AntimicrobialLevelEnum,
    CultureResultTypeEnum,
    FeatureEnum,
)
from services import feature_service
from tests.conftest import session, session_commit
from utils import status

# Seed prescription (noharm-ai/database): its drug list carries MEROPENEM
# (fkmedicamento 22), not suspended, from the "Medicamentos" source
SEED_PRESCRIPTION_ID = 199
PRESCRIBED_DRUG = 22

# fictitious substances reserved for this module
PRESCRIBED_SUBSTANCE = 9080001
OTHER_SUBSTANCE = 9080002

URL = f"/prescriptions/{SEED_PRESCRIPTION_ID}/cultures"
DYNAMODB_READ = "repository.culture_repository.get_culture_summary_from_dynamodb"


def _drug_sctid() -> int | None:
    """The substance the seed drug is mapped to, leaving out this module's
    own (a run killed before its teardown leaves the drug pointing at one)"""
    sctid = session.execute(
        text("SELECT sctid FROM demo.medicamento WHERE fkmedicamento = :id"),
        {"id": PRESCRIBED_DRUG},
    ).scalar()
    return None if sctid in (PRESCRIBED_SUBSTANCE, OTHER_SUBSTANCE) else sctid


def _set_drug_sctid(sctid: int | None):
    """Map the seed drug to a substance (None for none)"""
    session.execute(
        text("UPDATE demo.medicamento SET sctid = :sctid WHERE fkmedicamento = :id"),
        {"sctid": sctid, "id": PRESCRIBED_DRUG},
    )


def _delete_substances():
    """Remove this module's substances"""
    session.execute(
        text("DELETE FROM public.substancia WHERE sctid IN (:prescribed, :other)"),
        {"prescribed": PRESCRIBED_SUBSTANCE, "other": OTHER_SUBSTANCE},
    )


@pytest.fixture
def substances():
    """Two antimicrobial substances: the prescribed one (Reserve) and one the
    prescription does not carry (never classified). The seed drug of the
    prescription is mapped to the first one for the duration of the test, and
    then put back on the substance it had."""
    original_sctid = _drug_sctid()
    _delete_substances()
    session.execute(
        text(
            "INSERT INTO public.substancia (sctid, nome, ativo, tp_nivel_atb) "
            "VALUES (:prescribed, 'ZZTEST ATM PRESCRITO', true, :level), "
            "(:other, 'ZZTEST ATM OUTRO', true, NULL)"
        ),
        {
            "prescribed": PRESCRIBED_SUBSTANCE,
            "other": OTHER_SUBSTANCE,
            "level": AntimicrobialLevelEnum.RESERVE.value,
        },
    )
    _set_drug_sctid(PRESCRIBED_SUBSTANCE)
    session_commit()

    yield

    _set_drug_sctid(original_sctid)
    _delete_substances()
    session_commit()


def _patch_culture_feature(enabled: bool):
    """Patch the CULTURE tenant feature on or off, leaving every other
    feature as the schema has it"""
    original = feature_service.has_feature

    def has_feature(feature: FeatureEnum):
        """CULTURE as asked, the schema's answer for any other feature"""
        if feature == FeatureEnum.CULTURE:
            return enabled
        return original(feature)

    return patch.object(feature_service, "has_feature", side_effect=has_feature)


@pytest.fixture
def culture_feature():
    """Turn the CULTURE tenant feature on"""
    with _patch_culture_feature(enabled=True):
        yield


@pytest.fixture
def no_culture_feature():
    """Turn the CULTURE tenant feature off, whatever the schema's features
    memory lists"""
    with _patch_culture_feature(enabled=False):
        yield


def _item(drug: str, **fields) -> dict:
    """A DynamoDB item of the culture summary, active by default. DynamoDB
    hands numbers over as Decimal."""
    item = {
        "ativo": True,
        "nomemedicamento": drug,
        "chave": f"{drug}-1",
        "fkitemexame": Decimal(7001),
        "microorganismo": "Klebsiella pneumoniae",
        "nomematerial": "Urina",
        "datacoleta": "2026-01-10T08:00:00",
        "dataliberacao": "2026-01-12T10:00:00",
    }
    item.update(fields)
    return item


def _summary() -> list:
    """The culture summary of the patient: one resistant antibiogram of the
    prescribed substance, one susceptible of another substance, one drug the
    integration could not map to a substance, a confident prediction, and the
    items the card must never show"""
    return [
        _item(
            "ZZTEST PRESCRITO",
            sctid=Decimal(PRESCRIBED_SUBSTANCE),
            idclasse="J01DH",
            resultado="Resistente",
            qtdmicroorganismo=Decimal("32.0"),
        ),
        _item(
            "ZZTEST OUTRO",
            # the integration may hand the substance over as text
            sctid=str(OTHER_SUBSTANCE),
            resultado="S",
            qtdmicroorganismo="<=0.5",
        ),
        _item("ZZTEST SEM SUBSTANCIA", resultado="R"),
        _item(
            "ZZTEST PREDICAO",
            resultado=" ",
            predict="R",
            predict_proba=Decimal("0.85"),
        ),
        # inactive: dropped
        _item("ZZTEST INATIVO", ativo=False, resultado="R"),
        # pending without a confident prediction: nothing to show
        _item(
            "ZZTEST INCERTO",
            resultado=None,
            predict="R",
            predict_proba=Decimal("0.4"),
        ),
    ]


def _card(client, headers) -> dict:
    """The culture card of the seed prescription, by drug name"""
    response = client.get(URL, headers=headers)

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return {drug["drug"]: drug for drug in response.get_json()["data"]}


@pytest.mark.usefixtures("substances", "culture_feature")
def test_card_flags_the_prescribed_substance_and_its_aware_level(
    client, analyst_headers
):
    """Only the substance in the drug list reads as prescribed, and only a
    curated substance carries an AWaRe level"""
    with patch(DYNAMODB_READ, return_value=_summary()):
        card = _card(client, analyst_headers)

    prescribed = card["ZZTEST PRESCRITO"]
    assert prescribed["prescribed"] is True
    assert prescribed["atbLevel"] == AntimicrobialLevelEnum.RESERVE.value

    other = card["ZZTEST OUTRO"]
    assert other["prescribed"] is False
    assert other["atbLevel"] is None

    unmapped = card["ZZTEST SEM SUBSTANCIA"]
    assert unmapped["prescribed"] is False
    assert unmapped["atbLevel"] is None


@pytest.mark.usefixtures("substances", "culture_feature")
def test_card_shows_only_what_has_a_result_or_a_confident_prediction(
    client, analyst_headers
):
    """Inactive items and pending collections without a confident prediction
    stay out; the drugs come sorted by name"""
    with patch(DYNAMODB_READ, return_value=_summary()):
        response = client.get(URL, headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert [drug["drug"] for drug in response.get_json()["data"]] == [
        "ZZTEST OUTRO",
        "ZZTEST PREDICAO",
        "ZZTEST PRESCRITO",
        "ZZTEST SEM SUBSTANCIA",
    ]


@pytest.mark.usefixtures("substances", "culture_feature")
def test_card_items_carry_the_result_and_hide_the_mapping(client, analyst_headers):
    """The result is classified, the MIC goes out as text and the prediction
    only while the result is pending; the substance mapping and the exam item
    id never reach the card"""
    with patch(DYNAMODB_READ, return_value=_summary()):
        card = _card(client, analyst_headers)

    prescribed = card["ZZTEST PRESCRITO"]
    assert "sctid" not in prescribed
    assert "idSubstanceClass" not in prescribed

    [item] = prescribed["items"]
    assert "idExamItem" not in item
    assert item["result"] == "Resistente"
    assert item["resultType"] == CultureResultTypeEnum.RESISTANT.value
    assert item["mic"] == "32"
    assert item["prediction"] is None
    assert item["microorganism"] == "Klebsiella pneumoniae"
    assert item["material"] == "Urina"

    [other_item] = card["ZZTEST OUTRO"]["items"]
    assert other_item["resultType"] == CultureResultTypeEnum.SUSCEPTIBLE.value
    assert other_item["mic"] == "<=0.5"

    [predicted] = card["ZZTEST PREDICAO"]["items"]
    assert predicted["result"] is None
    assert predicted["resultType"] is None
    assert predicted["mic"] is None
    assert predicted["prediction"] == "R"
    assert predicted["predictionType"] == CultureResultTypeEnum.RESISTANT.value
    assert predicted["probability"] == pytest.approx(0.85)


@pytest.mark.usefixtures("substances", "culture_feature")
def test_view_counts_the_resistant_culture_in_use(client, analyst_headers):
    """The prescription view does not embed the cultures, but its tab badge
    (cultureStats) counts the prescribed drug with a resistant antibiogram:
    the same reading the card makes. A resistant drug not prescribed does not
    count."""
    with patch(DYNAMODB_READ, return_value=_summary()):
        response = client.get(
            f"/prescriptions/{SEED_PRESCRIPTION_ID}", headers=analyst_headers
        )

    assert response.status_code == status.HTTP_200_OK
    data = response.get_json()["data"]
    assert "cultures" not in data
    assert data["cultureStats"] == {"resistantInUse": 1}


@pytest.mark.usefixtures("substances", "culture_feature")
def test_card_is_empty_when_dynamodb_fails(client, analyst_headers):
    """A DynamoDB outage degrades the card to empty instead of failing"""
    with patch(DYNAMODB_READ, side_effect=RuntimeError("dynamodb unavailable")):
        response = client.get(URL, headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []


@pytest.mark.usefixtures("substances", "no_culture_feature")
def test_card_skips_dynamodb_without_the_culture_feature(client, analyst_headers):
    """Without the CULTURE feature the summary is not even read"""
    with patch(DYNAMODB_READ, return_value=_summary()) as dynamodb_read:
        response = client.get(URL, headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"] == []
    dynamodb_read.assert_not_called()
