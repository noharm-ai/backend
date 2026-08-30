"""Integration tests for the /admin/drug/attributes-list endpoint
(admin_drug_service.get_drug_list / drugs_repository.get_admin_drug_list).

The listing is the entry point of the drug curation screen: it joins the
outlier counters with the schema drug attributes and the public substance
catalog, and exposes a large set of filters used to find drugs that still
need curation.
"""

import pytest
from sqlalchemy import bindparam, text

from tests.conftest import get_access, make_headers, session, session_commit

# Test rows use a high id range so they never collide with seed data.
# demo.medicamento / demo.medatributos / demo.outlier ids >= 95000 and
# public.substancia sctid >= 9500000 belong to this file only.
_SUBSTANCE_ID = 9500001
_SUBSTANCE_NAME = "ZZTEST Substancia Alfa"

_DRUG_ALFA = 95001  # curated: substance confirmed, attributes on segment 1
_DRUG_BETA = 95002  # no substance and no attributes row (inconsistency)
_DRUG_GAMA = 95003  # AI-suggested substance, attributes on segments 1 and 2

_DRUG_IDS = (_DRUG_ALFA, _DRUG_BETA, _DRUG_GAMA)

_NAME_ALFA = "ZZTEST DRUG ALFA"
_NAME_BETA = "ZZTEST DRUG BETA"
_NAME_GAMA = "ZZTEST DRUG GAMA"

_TERM = "%ZZTEST DRUG%"

# demo.segmento seed rows
_SEGMENT_ADULT = 1
_SEGMENT_CPOE = 2


@pytest.fixture
def seed_admin_drugs():
    """Drugs, attributes, outlier counters and a substance for the listing."""
    session.execute(
        text(
            "INSERT INTO public.substancia "
            "(sctid, nome, ativo, dosemax_adulto, dosemax_peso_adulto, "
            "dosemax_pediatrico, dosemax_peso_pediatrico, unidadepadrao) "
            "VALUES (:id, :name, true, 500, 10, 250, 5, 'mg')"
        ),
        {"id": _SUBSTANCE_ID, "name": _SUBSTANCE_NAME},
    )

    for id_drug, name, sctid, accuracy in (
        (_DRUG_ALFA, _NAME_ALFA, _SUBSTANCE_ID, None),
        (_DRUG_BETA, _NAME_BETA, None, None),
        (_DRUG_GAMA, _NAME_GAMA, _SUBSTANCE_ID, 80),
    ):
        session.execute(
            text(
                "INSERT INTO demo.medicamento "
                "(fkhospital, fkmedicamento, nome, sctid, ia_acuracia) "
                "VALUES (1, :id, :name, :sctid, :accuracy)"
            ),
            {"id": id_drug, "name": name, "sctid": sctid, "accuracy": accuracy},
        )

    # ALFA is fully curated on the adult segment
    session.execute(
        text(
            "INSERT INTO demo.medatributos "
            "(fkmedicamento, idsegmento, fkunidademedida, fkunidademedidacusto, "
            "custo, dosemaxima, ref_dosemaxima, usapeso, antimicro, divisor) "
            "VALUES (:id, :segment, '1', '1', 1.5, 100, 100, false, true, 2)"
        ),
        {"id": _DRUG_ALFA, "segment": _SEGMENT_ADULT},
    )
    # GAMA is only partially filled on the adult segment...
    session.execute(
        text(
            "INSERT INTO demo.medatributos "
            "(fkmedicamento, idsegmento, usapeso, antimicro) "
            "VALUES (:id, :segment, true, false)"
        ),
        {"id": _DRUG_GAMA, "segment": _SEGMENT_ADULT},
    )
    # ...and curated on the CPOE segment, so it yields two listing rows
    session.execute(
        text(
            "INSERT INTO demo.medatributos "
            "(fkmedicamento, idsegmento, fkunidademedida, dosemaxima) "
            "VALUES (:id, :segment, '1', 50)"
        ),
        {"id": _DRUG_GAMA, "segment": _SEGMENT_CPOE},
    )
    # BETA has no attributes row at all -> inconsistency

    # the listing is driven by the outlier counters: one group per
    # (drug, segment) pair, with the summed prescription count
    for id_outlier, id_drug, segment, count in (
        (95001, _DRUG_ALFA, _SEGMENT_ADULT, 50),
        (95002, _DRUG_BETA, _SEGMENT_ADULT, 5),
        (95003, _DRUG_GAMA, _SEGMENT_ADULT, 120),
        (95004, _DRUG_GAMA, _SEGMENT_ADULT, 80),
        (95005, _DRUG_GAMA, _SEGMENT_CPOE, 7),
    ):
        session.execute(
            text(
                "INSERT INTO demo.outlier "
                "(idoutlier, fkmedicamento, idsegmento, contagem, doseconv, "
                "frequenciadia) "
                "VALUES (:id_outlier, :id_drug, :segment, :count, :id_outlier, 1)"
            ),
            {
                "id_outlier": id_outlier,
                "id_drug": id_drug,
                "segment": segment,
                "count": count,
            },
        )
    session_commit()

    yield

    session.execute(text("DELETE FROM demo.outlier WHERE idoutlier >= 95001"))
    session.execute(
        text("DELETE FROM demo.medatributos WHERE fkmedicamento IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": list(_DRUG_IDS)},
    )
    session.execute(
        text("DELETE FROM demo.medicamento WHERE fkmedicamento IN :ids").bindparams(
            bindparam("ids", expanding=True)
        ),
        {"ids": list(_DRUG_IDS)},
    )
    session.execute(
        text("DELETE FROM public.substancia WHERE sctid = :id"), {"id": _SUBSTANCE_ID}
    )
    session_commit()


def _post(client, headers, **filters):
    """Call the listing restricted to the seeded drugs unless told otherwise."""
    body = {"term": _TERM, "limit": 50}
    body.update(filters)

    return client.post("/admin/drug/attributes-list", json=body, headers=headers)


def _names(response):
    """Drug names of the returned rows, in response order."""
    return [item["name"] for item in response.get_json()["data"]["list"]]


def _pairs(response):
    """(idDrug, idSegment) of the returned rows, as a set."""
    return {
        (int(item["idDrug"]), item["idSegment"])
        for item in response.get_json()["data"]["list"]
    }


def test_drug_list_permission_denied(client, analyst_headers):
    """A user without ADMIN_DRUGS cannot list drug attributes [401]."""
    response = _post(client, analyst_headers)

    assert response.status_code == 401


def test_drug_list_permission_denied_config_manager(client, config_manager_headers):
    """WRITE_DRUG_ATTRIBUTES alone does not grant access to the listing [401]."""
    response = _post(client, config_manager_headers)

    assert response.status_code == 401


def test_drug_list_curator_is_allowed(client, curator_headers, seed_admin_drugs):
    """The curator role carries ADMIN_DRUGS, so the listing is available."""
    response = _post(client, curator_headers)

    assert response.status_code == 200
    assert _names(response)


def test_drug_list_returns_one_row_per_drug_segment_group(
    client, admin_headers, seed_admin_drugs
):
    """Each (drug, segment) outlier group produces one row, ordered by name."""
    response = _post(client, admin_headers)

    assert response.status_code == 200
    assert _pairs(response) == {
        (_DRUG_ALFA, _SEGMENT_ADULT),
        # BETA has no attributes row, so it carries no segment
        (_DRUG_BETA, None),
        (_DRUG_GAMA, _SEGMENT_ADULT),
        (_DRUG_GAMA, _SEGMENT_CPOE),
    }
    # ordered by drug name: ALFA < BETA < GAMA
    assert _names(response) == [_NAME_ALFA, _NAME_BETA, _NAME_GAMA, _NAME_GAMA]


def test_drug_list_row_shape(client, admin_headers, seed_admin_drugs):
    """A curated row exposes its attributes, substance and outlier counters."""
    response = _post(client, admin_headers, idDrugList=[_DRUG_ALFA])

    assert response.status_code == 200
    row = response.get_json()["data"]["list"][0]

    assert row["idDrug"] == str(_DRUG_ALFA)
    assert row["name"] == _NAME_ALFA
    assert row["idSegment"] == _SEGMENT_ADULT
    assert row["sctid"] == str(_SUBSTANCE_ID)
    assert row["substance"] == _SUBSTANCE_NAME
    assert row["idMeasureUnitDefault"] == "1"
    assert row["idMeasureUnitPrice"] == "1"
    assert row["price"] == 1.5
    assert row["maxDose"] == 100
    assert row["refMaxDose"] == 100
    assert row["useWeight"] is False
    assert row["doseRange"] == 2
    # summed outlier count for the (drug, segment) group
    assert row["drugCount"] == 50


def test_drug_list_sums_outlier_count_per_segment(
    client, admin_headers, seed_admin_drugs
):
    """drugCount sums every outlier row of the (drug, segment) group."""
    response = _post(client, admin_headers, idDrugList=[_DRUG_GAMA])

    assert response.status_code == 200
    counts = {
        item["idSegment"]: item["drugCount"]
        for item in response.get_json()["data"]["list"]
    }

    assert counts[_SEGMENT_ADULT] == 200  # 120 + 80
    assert counts[_SEGMENT_CPOE] == 7


def test_drug_list_exposes_substance_max_dose_by_segment_type(
    client, admin_headers, seed_admin_drugs
):
    """Substance reference doses follow the segment type (adult seed segments)."""
    response = _post(client, admin_headers, idDrugList=[_DRUG_ALFA])

    assert response.status_code == 200
    row = response.get_json()["data"]["list"][0]

    assert row["substanceMaxDose"] == 500
    assert row["substanceMaxDoseWeight"] == 10
    assert row["substanceMeasureUnit"] == "mg"


def test_drug_list_count_ignores_pagination(client, admin_headers, seed_admin_drugs):
    """count reports every matching row while the page respects limit/offset."""
    first_page = _post(client, admin_headers, limit=2, offset=0)
    second_page = _post(client, admin_headers, limit=2, offset=2)

    assert first_page.status_code == 200
    assert second_page.status_code == 200

    assert first_page.get_json()["data"]["count"] == 4
    assert second_page.get_json()["data"]["count"] == 4
    assert _names(first_page) == [_NAME_ALFA, _NAME_BETA]
    assert _names(second_page) == [_NAME_GAMA, _NAME_GAMA]


def test_drug_list_empty_result_reports_zero_count(client, admin_headers):
    """A term matching nothing returns an empty list and a zero count."""
    response = _post(client, admin_headers, term="%ZZTEST NOTHING MATCHES%")

    assert response.status_code == 200
    data = response.get_json()["data"]

    assert data["list"] == []
    assert data["count"] == 0


def test_drug_list_filter_by_term(client, admin_headers, seed_admin_drugs):
    """term matches the drug name, case-insensitively."""
    response = _post(client, admin_headers, term="%zztest drug beta%")

    assert response.status_code == 200
    assert _names(response) == [_NAME_BETA]


def test_drug_list_filter_by_substance_name(client, admin_headers, seed_admin_drugs):
    """substance matches the public substance name."""
    response = _post(client, admin_headers, substance="%substancia alfa%")

    assert response.status_code == 200
    assert _pairs(response) == {
        (_DRUG_ALFA, _SEGMENT_ADULT),
        (_DRUG_GAMA, _SEGMENT_ADULT),
        (_DRUG_GAMA, _SEGMENT_CPOE),
    }


def test_drug_list_filter_has_substance(client, admin_headers, seed_admin_drugs):
    """hasSubstance splits drugs already linked to a substance from the rest."""
    linked = _post(client, admin_headers, hasSubstance=True)
    unlinked = _post(client, admin_headers, hasSubstance=False)

    assert {p[0] for p in _pairs(linked)} == {_DRUG_ALFA, _DRUG_GAMA}
    assert _names(unlinked) == [_NAME_BETA]


def test_drug_list_filter_has_inconsistency(client, admin_headers, seed_admin_drugs):
    """hasInconsistency isolates drugs prescribed without an attributes row."""
    inconsistent = _post(client, admin_headers, hasInconsistency=True)
    consistent = _post(client, admin_headers, hasInconsistency=False)

    assert _names(inconsistent) == [_NAME_BETA]
    assert {p[0] for p in _pairs(consistent)} == {_DRUG_ALFA, _DRUG_GAMA}


def test_drug_list_filter_has_default_unit(client, admin_headers, seed_admin_drugs):
    """hasDefaultUnit finds the attribute rows still missing a measure unit."""
    with_unit = _post(client, admin_headers, hasDefaultUnit=True)
    without_unit = _post(client, admin_headers, hasDefaultUnit=False)

    assert _pairs(with_unit) == {
        (_DRUG_ALFA, _SEGMENT_ADULT),
        (_DRUG_GAMA, _SEGMENT_CPOE),
    }
    # GAMA on the adult segment has attributes but no unit; BETA has no row
    assert _pairs(without_unit) == {
        (_DRUG_BETA, None),
        (_DRUG_GAMA, _SEGMENT_ADULT),
    }


def test_drug_list_filter_has_price_unit(client, admin_headers, seed_admin_drugs):
    """hasPriceUnit isolates rows carrying a price measure unit."""
    response = _post(client, admin_headers, hasPriceUnit=True)

    assert _pairs(response) == {(_DRUG_ALFA, _SEGMENT_ADULT)}


def test_drug_list_filter_has_price_conversion(client, admin_headers, seed_admin_drugs):
    """A price unit equal to the default unit already counts as converted."""
    response = _post(client, admin_headers, hasPriceConversion=True)

    assert _pairs(response) == {(_DRUG_ALFA, _SEGMENT_ADULT)}


def test_drug_list_filter_has_max_dose(client, admin_headers, seed_admin_drugs):
    """hasMaxDose separates the rows with a configured maximum dose."""
    with_max_dose = _post(client, admin_headers, hasMaxDose=True)
    without_max_dose = _post(client, admin_headers, hasMaxDose=False)

    assert _pairs(with_max_dose) == {
        (_DRUG_ALFA, _SEGMENT_ADULT),
        (_DRUG_GAMA, _SEGMENT_CPOE),
    }
    assert _pairs(without_max_dose) == {
        (_DRUG_BETA, None),
        (_DRUG_GAMA, _SEGMENT_ADULT),
    }


def test_drug_list_filter_ref_max_dose_equal_and_diff(
    client, admin_headers, seed_admin_drugs
):
    """tpRefMaxDose compares the curated dose with the reference dose."""
    equal = _post(client, admin_headers, tpRefMaxDose="equal")
    empty = _post(client, admin_headers, tpRefMaxDose="empty")

    # ALFA has ref_maxdose == maxDose (100)
    assert _pairs(equal) == {(_DRUG_ALFA, _SEGMENT_ADULT)}
    # GAMA/CPOE has no reference dose, GAMA/adult uses weight and has none
    assert _pairs(empty) == {
        (_DRUG_BETA, None),
        (_DRUG_GAMA, _SEGMENT_ADULT),
        (_DRUG_GAMA, _SEGMENT_CPOE),
    }


def test_drug_list_filter_has_ai_substance(client, admin_headers, seed_admin_drugs):
    """hasAISubstance isolates substances suggested by the prediction job."""
    predicted = _post(client, admin_headers, hasAISubstance=True)
    not_predicted = _post(client, admin_headers, hasAISubstance=False)

    assert {p[0] for p in _pairs(predicted)} == {_DRUG_GAMA}
    assert {p[0] for p in _pairs(not_predicted)} == {_DRUG_ALFA, _DRUG_BETA}


def test_drug_list_filter_ai_accuracy_range(client, admin_headers, seed_admin_drugs):
    """aiAccuracyRange narrows the prediction confidence window."""
    inside = _post(client, admin_headers, hasAISubstance=True, aiAccuracyRange=[70, 90])
    outside = _post(
        client, admin_headers, hasAISubstance=True, aiAccuracyRange=[90, 100]
    )

    assert {p[0] for p in _pairs(inside)} == {_DRUG_GAMA}
    assert _pairs(outside) == set()


def test_drug_list_filter_substance_status(client, admin_headers, seed_admin_drugs):
    """substanceStatus groups drugs by how their substance link was obtained."""
    empty = _post(client, admin_headers, substanceStatus="empty")
    confirmed = _post(client, admin_headers, substanceStatus="confirmed")
    not_confirmed = _post(client, admin_headers, substanceStatus="not_confirmed")
    below_75 = _post(client, admin_headers, substanceStatus="not_confirmed_75")

    assert {p[0] for p in _pairs(empty)} == {_DRUG_BETA}
    assert {p[0] for p in _pairs(confirmed)} == {_DRUG_ALFA}
    assert {p[0] for p in _pairs(not_confirmed)} == {_DRUG_GAMA}
    # accuracy 80 is not below 75
    assert _pairs(below_75) == set()


def test_drug_list_filter_min_drug_count(client, admin_headers, seed_admin_drugs):
    """minDrugCount drops rarely prescribed (drug, segment) groups."""
    response = _post(client, admin_headers, minDrugCount=50)

    assert _pairs(response) == {
        (_DRUG_ALFA, _SEGMENT_ADULT),
        (_DRUG_GAMA, _SEGMENT_ADULT),
    }


def test_drug_list_filter_by_segment(client, admin_headers, seed_admin_drugs):
    """idSegmentList keeps only the attribute rows of the given segments."""
    response = _post(client, admin_headers, idSegmentList=[_SEGMENT_CPOE])

    assert _pairs(response) == {(_DRUG_GAMA, _SEGMENT_CPOE)}


def test_drug_list_filter_by_substance_list(client, admin_headers, seed_admin_drugs):
    """substanceList filters in or out the given substance ids."""
    included = _post(client, admin_headers, substanceList=[_SUBSTANCE_ID])
    excluded = _post(
        client, admin_headers, substanceList=[_SUBSTANCE_ID], tpSubstanceList="notin"
    )

    assert {p[0] for p in _pairs(included)} == {_DRUG_ALFA, _DRUG_GAMA}
    # the exclusion runs on the joined substance, so unlinked drugs drop out too
    assert _pairs(excluded) == set()


def test_drug_list_filter_by_attribute_list(client, admin_headers, seed_admin_drugs):
    """attributeList keeps (in) or drops (notin) rows carrying the attribute."""
    marked = _post(client, admin_headers, attributeList=["antimicro"])
    unmarked = _post(
        client, admin_headers, attributeList=["antimicro"], tpAttributeList="notin"
    )

    assert _pairs(marked) == {(_DRUG_ALFA, _SEGMENT_ADULT)}
    # a false or absent flag both count as "not marked"
    assert _pairs(unmarked) == {
        (_DRUG_BETA, None),
        (_DRUG_GAMA, _SEGMENT_ADULT),
        (_DRUG_GAMA, _SEGMENT_CPOE),
    }


def test_drug_list_filter_by_non_boolean_attribute(
    client, admin_headers, seed_admin_drugs
):
    """A numeric attribute counts as set when it holds any value."""
    response = _post(client, admin_headers, attributeList=["dosemaxima"])

    assert _pairs(response) == {
        (_DRUG_ALFA, _SEGMENT_ADULT),
        (_DRUG_GAMA, _SEGMENT_CPOE),
    }


def test_drug_list_group_by_drug_collapses_segments(
    client, admin_headers, seed_admin_drugs
):
    """groupByDrug returns one row per drug and counts distinct drugs."""
    response = _post(client, admin_headers, groupByDrug=True)

    assert response.status_code == 200
    data = response.get_json()["data"]

    assert _names(response) == [_NAME_ALFA, _NAME_BETA, _NAME_GAMA]
    assert data["count"] == 3


def test_drug_list_filter_has_substance_max_dose_weight(
    client, admin_headers, seed_admin_drugs
):
    """The substance weight-based reference doses are filterable."""
    response = _post(client, admin_headers, hasSubstanceMaxDoseWeightAdult=True)

    assert {p[0] for p in _pairs(response)} == {_DRUG_ALFA, _DRUG_GAMA}

    response = _post(client, admin_headers, hasSubstanceMaxDoseWeightPediatric=False)

    assert {p[0] for p in _pairs(response)} == {_DRUG_BETA}


def test_drug_list_rejects_invalid_params(client, admin_headers):
    """A malformed filter is rejected by the request model [400]."""
    response = client.post(
        "/admin/drug/attributes-list",
        json={"limit": "not-a-number"},
        headers=admin_headers,
    )

    assert response.status_code == 400


def test_drug_list_unauthenticated(client):
    """The endpoint requires a valid token [401]."""
    response = client.post(
        "/admin/drug/attributes-list",
        json={},
        headers=make_headers("invalid-token"),
    )

    assert response.status_code == 401


def test_drug_list_denied_for_plain_user(client):
    """A user with no roles at all cannot reach the listing [401]."""
    headers = make_headers(get_access(client, roles=[]))
    response = _post(client, headers)

    assert response.status_code == 401
