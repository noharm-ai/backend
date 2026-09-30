"""Tests: GET /intervention/reasons — the intervention reason catalog.

Every clinical intervention a pharmacist records has to name a reason, and the
reasons are a two-level tree kept per schema in ``demo.motivointervencao``:
a reason may hang under a parent reason, and each one carries the flags that
tell the intervention form how to behave — whether picking it suspends the
drug, substitutes it, blocks the prescription, records an adverse reaction
(``ram``) or asks for a custom economy value.

This endpoint is the only reader of that catalog. It serves the *active*
reasons alone, and it sorts them by parent name followed by their own name, so
a child always comes out right below its parent instead of wherever its own
name would fall alphabetically.

What these tests pin down:

* only active reasons are served;
* a child reports its parent's id and name, and a root reason reports neither;
* the ordering really is by parent-then-name, not by name — the fixture's
  child is named so that sorting by its own name would put it first;
* every flag of a reason reaches the caller under its API name, and
  ``protected`` is not computed on this path;
* the catalog is readable by a pharmacist (READ_PRESCRIPTION) and by a curator
  (ADMIN_INTERVENTION_REASON), and refused to a caller holding neither.
"""

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from utils import status

URL = "/intervention/reasons"

# reserved ids for this module — seed reasons live below 100, and
# test_intervention_multiple.py owns 90001
PARENT_ID = 900001
CHILD_ID = 900002
ROOT_ID = 900003
INACTIVE_ID = 900004

REASON_IDS = [PARENT_ID, CHILD_ID, ROOT_ID, INACTIVE_ID]

# Names are letters and spaces only, so the ordering assertion holds under
# both the C and the en_US collations. The child sorts *before* the parent by
# its own name and *after* it once the parent name is prepended, which is
# exactly the difference the endpoint's ordering has to make.
PARENT_NAME = "ZZTEST MOTIVO PAI"
CHILD_NAME = "ZZTEST MOTIVO AAA FILHO"
ROOT_NAME = "ZZTEST MOTIVO ZZZ SOZINHO"
INACTIVE_NAME = "ZZTEST MOTIVO INATIVO"

RELATION_TYPE = 2


def _insert_reason(
    id_reason: int,
    name: str,
    mamy: int = None,
    active: bool = True,
    suspension: bool = False,
    substitution: bool = False,
    custom_economy: bool = False,
    blocking: bool = False,
    ram: bool = False,
    relation_type: int = 0,
):
    """Insert a motivointervencao row directly, bypassing the endpoint."""
    session.execute(
        text(
            "INSERT INTO demo.motivointervencao "
            "(idmotivointervencao, fkhospital, nome, idmotivomae, ativo, "
            "suspensao, substituicao, economia_customizada, bloqueante, ram, "
            "tp_relacao) "
            "VALUES (:id, 1, :name, :mamy, :active, :suspension, :substitution, "
            ":custom_economy, :blocking, :ram, :relation_type)"
        ),
        {
            "id": id_reason,
            "name": name,
            "mamy": mamy,
            "active": active,
            "suspension": suspension,
            "substitution": substitution,
            "custom_economy": custom_economy,
            "blocking": blocking,
            "ram": ram,
            "relation_type": relation_type,
        },
    )


def _cleanup():
    """Remove every reason this module may have created.

    Scoped to the exact ids rather than to a range, so the module can never
    reach a row another test owns however the ranges are reshuffled later.
    """
    session.execute(
        text(
            "DELETE FROM demo.motivointervencao WHERE idmotivointervencao = ANY(:ids)"
        ),
        {"ids": REASON_IDS},
    )
    session_commit()


@pytest.fixture(autouse=True)
def seed_reasons():
    """A parent with one child, a root reason and an inactive one."""
    _cleanup()

    _insert_reason(PARENT_ID, PARENT_NAME)
    _insert_reason(
        CHILD_ID,
        CHILD_NAME,
        mamy=PARENT_ID,
        suspension=True,
        substitution=True,
        custom_economy=True,
        blocking=True,
        ram=True,
        relation_type=RELATION_TYPE,
    )
    _insert_reason(ROOT_ID, ROOT_NAME)
    _insert_reason(INACTIVE_ID, INACTIVE_NAME, active=False)
    session_commit()

    yield

    _cleanup()


def _reasons(client, headers):
    """Call the endpoint and return the reason list."""
    response = client.get(URL, headers=headers)

    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"]


def _by_id(reasons):
    """Index a reason list by id."""
    return {reason["id"]: reason for reason in reasons}


def test_serves_the_active_reasons(client, analyst_headers):
    """The catalog lists the active reasons, seeded and test alike."""
    reasons = _by_id(_reasons(client, analyst_headers))

    assert PARENT_ID in reasons
    assert CHILD_ID in reasons
    assert ROOT_ID in reasons
    # the demo schema ships its own catalog, which is served too
    assert len(reasons) > 4


def test_inactive_reasons_are_left_out(client, analyst_headers):
    """A reason switched off is not offered to the intervention form."""
    reasons = _by_id(_reasons(client, analyst_headers))

    assert INACTIVE_ID not in reasons
    assert all(reason["active"] is True for reason in reasons.values())


def test_child_reports_its_parent(client, analyst_headers):
    """A child names the id and the description of the reason above it."""
    child = _by_id(_reasons(client, analyst_headers))[CHILD_ID]

    assert child["name"] == CHILD_NAME
    assert child["parentId"] == PARENT_ID
    assert child["parentName"] == PARENT_NAME


def test_root_reason_has_no_parent(client, analyst_headers):
    """A reason at the top of the tree reports no parent at all."""
    root = _by_id(_reasons(client, analyst_headers))[ROOT_ID]

    assert root["parentId"] is None
    assert root["parentName"] is None


def test_children_are_ordered_below_their_parent(client, analyst_headers):
    """Sorting is by parent name then own name, so the child follows its parent.

    ``ZZTEST MOTIVO AAA FILHO`` sorts before ``ZZTEST MOTIVO PAI`` by its own
    name; it only lands between the parent and ``ZZTEST MOTIVO ZZZ SOZINHO``
    because the parent's name is prepended before sorting.
    """
    ordered = [
        reason["id"]
        for reason in _reasons(client, analyst_headers)
        if reason["id"] in (PARENT_ID, CHILD_ID, ROOT_ID)
    ]

    assert ordered == [PARENT_ID, CHILD_ID, ROOT_ID]


def test_reason_flags_reach_the_caller(client, analyst_headers):
    """Every flag the intervention form reads is carried in the DTO."""
    child = _by_id(_reasons(client, analyst_headers))[CHILD_ID]

    assert child["suspension"] is True
    assert child["substitution"] is True
    assert child["customEconomy"] is True
    assert child["blocking"] is True
    assert child["ram"] is True
    assert child["relationType"] == RELATION_TYPE


def test_flags_of_a_plain_reason_are_false(client, analyst_headers):
    """A reason created with no flag set reports every one of them off."""
    root = _by_id(_reasons(client, analyst_headers))[ROOT_ID]

    assert root["suspension"] is False
    assert root["substitution"] is False
    assert root["customEconomy"] is False
    assert root["blocking"] is False
    assert root["ram"] is False
    assert root["relationType"] == 0


def test_protected_is_not_computed_on_this_path(client, analyst_headers):
    """The active-only listing skips the "reason already used" lookup."""
    reasons = _reasons(client, analyst_headers)

    assert all(reason["protected"] == 0 for reason in reasons)


def test_readable_with_the_admin_permission(client, admin_headers):
    """ADMIN_INTERVENTION_REASON reads the catalog without READ_PRESCRIPTION."""
    reasons = _by_id(_reasons(client, admin_headers))

    assert PARENT_ID in reasons


def test_requires_prescription_or_admin_permission(client, navigator_headers):
    """NAVIGATOR holds neither permission and is refused [401 UNAUTHORIZED]."""
    response = client.get(URL, headers=navigator_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
