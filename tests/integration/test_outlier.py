"""Integration tests for the outlier update endpoint (PUT /outliers/<id>).

Exercises ``outlier_service.update_outlier``, which lets a user holding
``WRITE_DRUG_SCORE`` store a manual score on an outlier. The endpoint had no
prior coverage in the suite.

The drug/outlier fixtures use IDs in the reserved ``>= 90000`` range so the
session-scoped ``clean_test_artifacts`` fixture removes them afterwards.
"""

import pytest

from models.main import Outlier
from tests.conftest import session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_outlier,
    create_test_substance,
)

# IDs reserved for this module (>= 90000, distinct from other modules' ranges).
_SCTID = 90050
_DRUG_ID = 90050
_OUTLIER_ID = 90050


@pytest.fixture(scope="module", autouse=True)
def setup_outlier_test_data(clean_test_artifacts):  # noqa: ARG001
    """Create the drug + outlier to update, after the global cleanup fixture runs."""
    create_test_substance(_SCTID, "Test Outlier Drug", "mg")
    create_test_drug(_DRUG_ID, "Test Outlier Drug", _SCTID)
    create_test_outlier(_OUTLIER_ID, _DRUG_ID)


def _read_outlier() -> Outlier:
    """Return a fresh copy of the test outlier (commit first to drop any snapshot)."""
    session_commit()
    return session.query(Outlier).filter(Outlier.id == _OUTLIER_ID).first()


def test_update_outlier_sets_manual_score(client, config_manager_headers):
    """A WRITE_DRUG_SCORE user sets a manual score and it is persisted [200 OK]."""
    response = client.put(
        f"/outliers/{_OUTLIER_ID}",
        headers=config_manager_headers,
        json={"manualScore": 3},
    )

    assert response.status_code == 200

    outlier = _read_outlier()
    assert outlier.manualScore == 3
    # the update stamps who changed it and when
    assert outlier.update is not None
    assert outlier.user is not None


def test_update_outlier_overwrites_manual_score(client, config_manager_headers):
    """A second update replaces the previously stored manual score."""
    client.put(
        f"/outliers/{_OUTLIER_ID}",
        headers=config_manager_headers,
        json={"manualScore": 2},
    )

    response = client.put(
        f"/outliers/{_OUTLIER_ID}",
        headers=config_manager_headers,
        json={"manualScore": 4},
    )

    assert response.status_code == 200
    assert _read_outlier().manualScore == 4


def test_update_outlier_permission_denied(client, analyst_headers):
    """Without WRITE_DRUG_SCORE the update is rejected [401] and nothing changes."""
    before = _read_outlier().manualScore

    response = client.put(
        f"/outliers/{_OUTLIER_ID}",
        headers=analyst_headers,
        json={"manualScore": 99},
    )

    assert response.status_code == 401
    # the rejected write must leave the stored score untouched
    after = _read_outlier().manualScore
    assert after == before
    assert after != 99
