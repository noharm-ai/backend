"""Integration tests for the outlier score-generation pipeline.

The ``/outliers/generate/*`` endpoints turn one year of prescription history
into the outlier rows that dose/frequency scores are later computed from.
Nothing in the suite covered them, yet they own the rules that decide whether a
drug can be scored at all:

* ``prepare`` (``POST /outliers/generate/prepare/<segment>/<drug>``) — builds
  the aggregated history when there is none, refreshes it when there is, then
  rebuilds the drug's outlier rows;
* ``add_prescription_history``
  (``POST /outliers/generate/add-history/<segment>/<drug>``) — reloads the
  aggregation from ``presmed``, rejecting drugs not prescribed in the last year;
* ``remove_outlier`` (``POST /outliers/generate/remove-outlier/<segment>/<drug>``)
  — drops a drug's outliers, but only while it has no prescription history.

Only the drug-scoped operations are exercised: the segment-wide entry points
(``refresh-agg``, ``generate/segment``) invoke AWS Lambda and would rebuild
every outlier in the segment, which other tests read from.

All fixtures use the reserved ``>= 90000`` id range so ``clean_test_artifacts``
removes them, and prescriptions come from ``test_counters`` (ids >= 100000).
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from models.main import Outlier, PrescriptionAgg
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_outlier,
    create_test_substance,
)

_SEGMENT = 1

# IDs reserved for this module (>= 90000, distinct from other modules' ranges).
_SCTID = 90300
_DRUG_WITH_HISTORY = 90300  # two dose/frequency pairs prescribed this week
_DRUG_WITHOUT_HISTORY = 90301  # never prescribed
_DRUG_WITH_OLD_HISTORY = 90302  # prescribed, but more than a year ago
_DRUG_WITH_ORPHAN_OUTLIER = 90303  # has an outlier row, no history
_DRUG_TO_KEEP = 90304  # history is loaded by the test that needs it
_ORPHAN_OUTLIER_ID = 90303


def _next_prescription_ids():
    """Reserve a prescription id + admission number no other test uses."""
    id_prescription = test_counters["id_prescription"]
    admission_number = test_counters["admission_number"]
    test_counters["id_prescription"] += 1
    test_counters["admission_number"] += 1

    return id_prescription, admission_number


def _create_history(id_drug: int, doses: list[tuple[float, float]], days_ago: int = 1):
    """Prescribe ``id_drug`` once per (dose, frequency) pair, ``days_ago`` back.

    One prescription holds every item, so all rows share hospital, department
    and segment — exactly what ``add_prescription_history`` groups by.
    """
    id_prescription, admission_number = _next_prescription_ids()
    date = datetime.now() - timedelta(days=days_ago)

    create_prescription(
        id=id_prescription,
        admissionNumber=admission_number,
        idPatient=id_prescription,
        idSegment=_SEGMENT,
        date=date,
        expire=date + timedelta(days=1),
    )

    for index, (dose, frequency) in enumerate(doses, start=1):
        # `<prescription id>NNN` starting at 001, so every id stays above the
        # 100000001 presmed cleanup threshold used by tests/conftest.py
        create_prescription_drug(
            id=int(f"{id_prescription}{index:03d}"),
            idPrescription=id_prescription,
            idDrug=id_drug,
            dose=dose,
            frequency=frequency,
            idSegment=_SEGMENT,
        )

    return id_prescription


_DRUGS = {
    _DRUG_WITH_HISTORY: "Test Outlier Generate History",
    _DRUG_WITHOUT_HISTORY: "Test Outlier Generate Empty",
    _DRUG_WITH_OLD_HISTORY: "Test Outlier Generate Old",
    _DRUG_WITH_ORPHAN_OUTLIER: "Test Outlier Generate Orphan",
    _DRUG_TO_KEEP: "Test Outlier Generate Keep",
}


@pytest.fixture(scope="module", autouse=True)
def setup_outlier_generate_data(clean_test_artifacts):  # noqa: ARG001
    """Create the drugs and prescription history, after the global cleanup runs."""
    _drop_derived_rows()

    create_test_substance(_SCTID, "Test Outlier Generate", "mg")
    for id_drug, name in _DRUGS.items():
        create_test_drug(id_drug, name, _SCTID)

    # two prescriptions of 100mg/1x and one of 200mg/2x -> two outlier groups
    _create_history(_DRUG_WITH_HISTORY, [(100.0, 1.0), (100.0, 1.0), (200.0, 2.0)])
    _create_history(_DRUG_TO_KEEP, [(50.0, 1.0)])
    # outside the one-year window used by add_prescription_history
    _create_history(_DRUG_WITH_OLD_HISTORY, [(100.0, 1.0)], days_ago=400)

    create_test_outlier(_ORPHAN_OUTLIER_ID, _DRUG_WITH_ORPHAN_OUTLIER, _SEGMENT)

    yield

    _drop_derived_rows()


def _drop_derived_rows():
    """Remove the rows the pipeline derived from this module's drugs.

    Outlier rows created by the pipeline take their id from the table sequence,
    so they fall outside the ``>= 90000`` id range the shared cleanup deletes and
    have to be matched by drug. The drugs themselves are left to the shared
    cleanup, which deletes the prescription items referencing them first.
    """
    ids = tuple(_DRUGS)
    session.execute(
        text("DELETE FROM demo.outlier WHERE fkmedicamento IN :ids").bindparams(ids=ids)
    )
    session.execute(
        text("DELETE FROM demo.prescricaoagg WHERE fkmedicamento IN :ids").bindparams(
            ids=ids
        )
    )
    # the aggregation reads presmed, so a leftover item would inflate the counts
    # of a later run
    session.execute(
        text("DELETE FROM demo.presmed WHERE fkmedicamento IN :ids").bindparams(ids=ids)
    )
    session_commit()


def _agg_rows(id_drug: int) -> list[PrescriptionAgg]:
    """Return the aggregated history rows stored for a drug."""
    session_commit()
    return (
        session.query(PrescriptionAgg)
        .filter(PrescriptionAgg.idDrug == id_drug)
        .filter(PrescriptionAgg.idSegment == _SEGMENT)
        .all()
    )


def _outlier_rows(id_drug: int) -> list[Outlier]:
    """Return the outlier rows stored for a drug, ordered by dose."""
    session_commit()
    return (
        session.query(Outlier)
        .filter(Outlier.idDrug == id_drug)
        .filter(Outlier.idSegment == _SEGMENT)
        .order_by(Outlier.dose)
        .all()
    )


def _prepare(client, headers, id_drug: int, id_segment: int = _SEGMENT):
    """Call the prepare endpoint for a drug."""
    return client.post(
        f"/outliers/generate/prepare/{id_segment}/{id_drug}",
        json={},
        headers=headers,
    )


def _add_history(client, headers, id_drug: int, id_segment: int = _SEGMENT):
    """Call the add-history endpoint for a drug."""
    return client.post(
        f"/outliers/generate/add-history/{id_segment}/{id_drug}",
        json={},
        headers=headers,
    )


def _remove_outlier(client, headers, id_drug: int, id_segment: int = _SEGMENT):
    """Call the remove-outlier endpoint for a drug."""
    return client.post(
        f"/outliers/generate/remove-outlier/{id_segment}/{id_drug}",
        json={},
        headers=headers,
    )


class TestPrepare:
    """POST /outliers/generate/prepare/<id_segment>/<id_drug>

    Step 1 of score generation: make sure the drug has aggregated history and
    rebuild its outlier rows from it. Without history there is nothing to score,
    and the endpoint must say so instead of silently producing no outliers.
    """

    def test_prepare_builds_history_and_outliers(self, client, admin_headers):
        """Prepare aggregates presmed into history and one outlier per dose group"""
        response = _prepare(client, admin_headers, _DRUG_WITH_HISTORY)

        assert response.status_code == 200
        # one inserted outlier row per distinct (dose, frequency) pair
        assert response.get_json()["data"] == 2

        history = {
            (row.dose, row.frequency, row.countNum)
            for row in _agg_rows(_DRUG_WITH_HISTORY)
        }
        assert history == {(100.0, 1.0, 2), (200.0, 2.0, 1)}

        outliers = _outlier_rows(_DRUG_WITH_HISTORY)
        assert [(o.dose, o.frequency, o.countNum) for o in outliers] == [
            (100.0, 1.0, 2),
            (200.0, 2.0, 1),
        ]

    def test_prepare_is_idempotent(self, client, admin_headers):
        """Running prepare again refreshes the same rows instead of duplicating them

        The second run takes the other branch: history already exists, so it is
        refreshed in place rather than rebuilt from presmed.
        """
        first = _prepare(client, admin_headers, _DRUG_WITH_HISTORY)
        second = _prepare(client, admin_headers, _DRUG_WITH_HISTORY)

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.get_json()["data"] == 2
        assert len(_agg_rows(_DRUG_WITH_HISTORY)) == 2
        assert len(_outlier_rows(_DRUG_WITH_HISTORY)) == 2

    def test_prepare_without_prescription_history_fails(self, client, admin_headers):
        """A drug never prescribed cannot be scored"""
        response = _prepare(client, admin_headers, _DRUG_WITHOUT_HISTORY)

        assert response.status_code == 400
        assert response.get_json()["code"] == "errors.invalidParams"
        assert "histórico de prescrição" in response.get_json()["message"]
        assert _agg_rows(_DRUG_WITHOUT_HISTORY) == []
        assert _outlier_rows(_DRUG_WITHOUT_HISTORY) == []

    def test_prepare_ignores_prescriptions_older_than_a_year(
        self, client, admin_headers
    ):
        """History older than one year does not count as history"""
        response = _prepare(client, admin_headers, _DRUG_WITH_OLD_HISTORY)

        assert response.status_code == 400
        assert "histórico de prescrição" in response.get_json()["message"]
        assert _agg_rows(_DRUG_WITH_OLD_HISTORY) == []

    def test_prepare_requires_write_drug_score(self, client, viewer_headers):
        """A viewer holds no score permission"""
        response = _prepare(client, viewer_headers, _DRUG_WITH_HISTORY)

        assert response.status_code == 401
        assert response.get_json()["code"] == "error.authorizationError"


class TestAddHistory:
    """POST /outliers/generate/add-history/<id_segment>/<id_drug>

    Reloads the aggregated history for one drug from ``presmed``. It is the
    maintainer-only entry point, and it cleans the drug's previous aggregation
    first so a reload cannot double the counts a score is computed from.
    """

    def test_add_history_returns_the_aggregated_row_count(self, client, admin_headers):
        """The reload reports how many aggregated rows the drug now has"""
        response = _add_history(client, admin_headers, _DRUG_WITH_HISTORY)

        assert response.status_code == 200
        assert response.get_json()["data"] == 2

    def test_add_history_cleans_before_reloading(self, client, admin_headers):
        """Reloading twice keeps the counts, it does not stack them"""
        _add_history(client, admin_headers, _DRUG_WITH_HISTORY)
        response = _add_history(client, admin_headers, _DRUG_WITH_HISTORY)

        assert response.status_code == 200
        history = {(row.dose, row.countNum) for row in _agg_rows(_DRUG_WITH_HISTORY)}
        assert history == {(100.0, 2), (200.0, 1)}

    def test_add_history_rolls_back_when_nothing_was_prescribed(
        self, client, admin_headers
    ):
        """A drug with no history in the last year is rejected"""
        response = _add_history(client, admin_headers, _DRUG_WITHOUT_HISTORY)

        assert response.status_code == 400
        assert response.get_json()["code"] == "errors.invalidParams"
        assert "não foi prescrito no último ano" in response.get_json()["message"]

    def test_add_history_requires_maintainer(self, client, config_manager_headers):
        """WRITE_DRUG_SCORE alone does not grant the maintainer endpoint"""
        response = _add_history(client, config_manager_headers, _DRUG_WITH_HISTORY)

        assert response.status_code == 401
        assert response.get_json()["code"] == "error.authorizationError"


class TestRemoveOutlier:
    """POST /outliers/generate/remove-outlier/<id_segment>/<id_drug>

    Deletes a drug's outlier rows. Allowed only while the drug has no
    aggregated history — otherwise the rows would be silently regenerated by the
    next score run, and the score shown in the meantime would have no basis.
    """

    def test_remove_outlier_deletes_rows_when_there_is_no_history(
        self, client, admin_headers
    ):
        """An outlier with no prescription history behind it can be removed"""
        assert len(_outlier_rows(_DRUG_WITH_ORPHAN_OUTLIER)) == 1

        response = _remove_outlier(client, admin_headers, _DRUG_WITH_ORPHAN_OUTLIER)

        assert response.status_code == 200
        assert _outlier_rows(_DRUG_WITH_ORPHAN_OUTLIER) == []

    def test_remove_outlier_is_blocked_by_prescription_history(
        self, client, admin_headers
    ):
        """A drug with aggregated history keeps its outliers"""
        assert _add_history(client, admin_headers, _DRUG_TO_KEEP).status_code == 200

        response = _remove_outlier(client, admin_headers, _DRUG_TO_KEEP)

        assert response.status_code == 400
        assert response.get_json()["code"] == "errors.invalid"
        assert "possui histórico de prescrição" in response.get_json()["message"]
        assert len(_agg_rows(_DRUG_TO_KEEP)) == 1

    def test_remove_outlier_requires_write_segment_score(
        self, client, config_manager_headers
    ):
        """WRITE_DRUG_SCORE alone does not allow removing outliers"""
        response = _remove_outlier(
            client, config_manager_headers, _DRUG_WITH_ORPHAN_OUTLIER
        )

        assert response.status_code == 401
        assert response.get_json()["code"] == "error.authorizationError"
