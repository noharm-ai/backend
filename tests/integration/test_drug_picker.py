"""Integration tests for the drug picker endpoint (``GET /drugs``).

``outlier_service.get_outlier_drugs`` backs the drug selector used by the score
configuration screens. Nothing in the suite exercised it, even though the query
it builds changes shape three times depending on the request:

* ``GET /drugs/<segment>`` — only drugs the scoring pipeline knows in that
  segment (i.e. drugs with an ``outlier`` row), never grouped;
* ``GET /drugs`` — every drug in the schema, collapsed by name so the same
  product registered under several hospital codes shows up once
  (``group=0`` opts out and returns every row);
* ``GET /drugs?addSubstance=1`` — drugs *and* the public substance catalog in a
  single list, which is how a score rule can target a substance instead of a
  drug. Drugs generated from a substance (``origem = 'SUBNH'``) are left out of
  that list so a substance never appears twice.

Fixtures use the reserved ``>= 90000`` id range so the session-scoped
``clean_test_artifacts`` fixture in ``tests/conftest.py`` removes them.
"""

import pytest
from sqlalchemy import text

from security.role import Role
from tests.conftest import get_access, make_headers, session, session_commit

URL = "/drugs"

# Segments seeded in demo.segmento
_SEGMENT = 1
_OTHER_SEGMENT = 2

# ids reserved for this module (91300 block for drugs, 9130000 for substances)
_DRUG_SCORED = 91301  # has an outlier on _SEGMENT
_DRUG_UNSCORED = 91302  # no outlier at all
_DRUG_SCORED_TWIN = 91303  # same name as _DRUG_SCORED, higher id, no outlier
_DRUG_FROM_SUBSTANCE = 91304  # origem = SUBNH

_SUBSTANCE_ACTIVE = 9130001
_SUBSTANCE_INACTIVE = 9130002

_TERM = "ZZTEST PICKER"
_NAME_ALFA = "ZZTEST PICKER ALFA"
_NAME_BETA = "ZZTEST PICKER BETA"
_NAME_SUBNH = "ZZTEST PICKER SUBNH"
_NAME_SUBSTANCE_ACTIVE = "ZZTEST PICKER SUBSTANCIA ATIVA"
_NAME_SUBSTANCE_INACTIVE = "ZZTEST PICKER SUBSTANCIA INATIVA"


@pytest.fixture
def dispensing_headers(client):
    """Headers with DISPENSING_MANAGER role — does not hold READ_PRESCRIPTION."""
    return make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))


@pytest.fixture
def picker_drugs():
    """Drugs, substances and the single outlier row the picker filters on."""
    for sctid, name, active in (
        (_SUBSTANCE_ACTIVE, _NAME_SUBSTANCE_ACTIVE, True),
        (_SUBSTANCE_INACTIVE, _NAME_SUBSTANCE_INACTIVE, False),
    ):
        session.execute(
            text(
                "INSERT INTO public.substancia (sctid, nome, link, ativo) "
                "VALUES (:sctid, :name, '', :active)"
            ),
            {"sctid": sctid, "name": name, "active": active},
        )

    for id_drug, name, source in (
        (_DRUG_SCORED, _NAME_ALFA, None),
        (_DRUG_UNSCORED, _NAME_BETA, None),
        (_DRUG_SCORED_TWIN, _NAME_ALFA, None),
        (_DRUG_FROM_SUBSTANCE, _NAME_SUBNH, "SUBNH"),
    ):
        session.execute(
            text(
                "INSERT INTO demo.medicamento (fkmedicamento, fkhospital, nome, origem) "
                "VALUES (:id, 1, :name, :source)"
            ),
            {"id": id_drug, "name": name, "source": source},
        )

    session.execute(
        text(
            "INSERT INTO demo.outlier "
            "(fkmedicamento, idsegmento, contagem, doseconv, frequenciadia, escore) "
            "VALUES (:id, :segment, 10, 1, 1, 1)"
        ),
        {"id": _DRUG_SCORED, "segment": _SEGMENT},
    )
    session_commit()

    yield

    session.execute(text("DELETE FROM demo.outlier WHERE fkmedicamento >= 90000"))
    session.execute(text("DELETE FROM demo.medicamento WHERE fkmedicamento >= 90000"))
    session.execute(text("DELETE FROM public.substancia WHERE sctid >= 9130000"))
    session_commit()


def _items(response):
    """Payload of a successful response."""
    return response.get_json()["data"]


def _names(response):
    """Returned names, in response order."""
    return [item["name"] for item in _items(response)]


def _ids(response):
    """Returned drug ids, as the integers the client sends back."""
    return [int(item["idDrug"]) for item in _items(response)]


def test_no_token(client):
    """GET /drugs — 401 without authentication."""
    response = client.get(f"{URL}?q={_TERM}")

    assert response.status_code == 401


def test_permission_denied(client, dispensing_headers):
    """GET /drugs — 401 for a role without READ_PRESCRIPTION."""
    response = client.get(f"{URL}?q={_TERM}", headers=dispensing_headers)

    assert response.status_code == 401


def test_segment_returns_only_scored_drugs(client, analyst_headers, picker_drugs):
    """A segment-scoped search only returns drugs with an outlier in it."""
    response = client.get(
        f"{URL}/{_SEGMENT}?q={_TERM}",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    # the twin shares its name but has no outlier, so the segment query keeps
    # the scored row instead of the highest id the grouped query would pick
    assert _ids(response) == [_DRUG_SCORED]


def test_segment_without_scores_returns_nothing(
    client, analyst_headers, picker_drugs
):
    """The same drug is invisible on a segment where it was never scored."""
    response = client.get(
        f"{URL}/{_OTHER_SEGMENT}?q={_TERM}",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert _items(response) == []


def test_without_segment_groups_by_name(client, analyst_headers, picker_drugs):
    """Without a segment the listing collapses same-named drugs onto the highest id."""
    response = client.get(f"{URL}?q={_TERM}", headers=analyst_headers)

    assert response.status_code == 200
    ids = _ids(response)

    # one entry for the two drugs named ALFA, and it carries the highest id
    assert ids.count(_DRUG_SCORED_TWIN) == 1
    assert _DRUG_SCORED not in ids
    # unscored drugs are listed here: the outlier restriction is segment-only
    assert _DRUG_UNSCORED in ids
    assert _NAME_ALFA in _names(response)


def test_group_off_returns_every_row(client, analyst_headers, picker_drugs):
    """group=0 opts out of the collapsing and returns both same-named drugs."""
    response = client.get(f"{URL}?q={_TERM}&group=0", headers=analyst_headers)

    assert response.status_code == 200
    ids = _ids(response)

    assert _DRUG_SCORED in ids
    assert _DRUG_SCORED_TWIN in ids


def test_results_are_sorted_by_name(client, analyst_headers, picker_drugs):
    """Results come back in alphabetical order."""
    response = client.get(f"{URL}?q={_TERM}", headers=analyst_headers)

    assert response.status_code == 200
    names = _names(response)

    assert names == sorted(names)


def test_term_is_case_insensitive_and_partial(client, analyst_headers, picker_drugs):
    """The q filter matches any case and any position in the name."""
    response = client.get(f"{URL}?q=zztest picker beta", headers=analyst_headers)

    assert response.status_code == 200
    assert _names(response) == [_NAME_BETA]


def test_term_without_matches(client, analyst_headers, picker_drugs):
    """A term matching nothing returns an empty list rather than an error."""
    response = client.get(f"{URL}?q=ZZTEST PICKER INEXISTENTE", headers=analyst_headers)

    assert response.status_code == 200
    assert _items(response) == []


def test_filter_by_id(client, analyst_headers, picker_drugs):
    """idDrug[] narrows the listing to the requested ids."""
    response = client.get(
        f"{URL}?q={_TERM}&group=0&idDrug[]={_DRUG_UNSCORED}",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert _ids(response) == [_DRUG_UNSCORED]


def test_add_substance_merges_catalog(client, analyst_headers, picker_drugs):
    """addSubstance=1 returns drugs and active substances in one list."""
    response = client.get(
        f"{URL}?q={_TERM}&addSubstance=1",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    names = _names(response)

    assert _NAME_ALFA in names
    assert _NAME_BETA in names
    assert _NAME_SUBSTANCE_ACTIVE in names
    # an inactive substance is not offered
    assert _NAME_SUBSTANCE_INACTIVE not in names
    # neither is a drug the substance catalog generated, which would duplicate it
    assert _NAME_SUBNH not in names
    assert names == sorted(names)


def test_add_substance_returns_substance_id(client, analyst_headers, picker_drugs):
    """A substance entry carries its sctid, which is what the rule stores."""
    response = client.get(
        f"{URL}?q={_NAME_SUBSTANCE_ACTIVE}&addSubstance=1",
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert _ids(response) == [_SUBSTANCE_ACTIVE]


def test_ids_are_returned_as_strings(client, analyst_headers, picker_drugs):
    """Ids are serialized as strings so large ids survive the JSON round trip."""
    response = client.get(f"{URL}?q={_NAME_BETA}", headers=analyst_headers)

    assert response.status_code == 200
    assert _items(response) == [{"idDrug": str(_DRUG_UNSCORED), "name": _NAME_BETA}]
