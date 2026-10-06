"""Tests: PUT /outliers/<id> — the observation note stored alongside an outlier.

``outlier_service.update_outlier`` serves two independent edits on the same
endpoint, each gated by the *presence* of its key in the payload rather than by
its value:

* ``manualScore`` overrides the computed score of a dose/frequency outlier;
* ``obs`` keeps the pharmacist's written justification for that override.

The note does not live on the outlier. It is a row of ``demo.observacao``, a
table shared with prescription-level notes, whose primary key is
``(idoutlier, fkpresmed)``. An outlier note is written with ``fkpresmed = 0``,
which is what separates it from a note attached to a prescribed item, and it
copies the segment, drug, dose and frequency of the outlier it belongs to so
the row stands on its own.

``test_outlier.py`` covers the ``manualScore`` half. This module covers the
note: that the first write inserts a row carrying the outlier's own
dose/frequency identity, that later writes update that row instead of stacking
a second one, that the two keys are independent in both directions, and that a
caller without WRITE_DRUG_SCORE leaves no note behind.
"""

import pytest
from sqlalchemy import text

from models.appendix import Notes
from models.main import Outlier
from tests.conftest import session, session_commit
from tests.utils.utils_test_unit_conversion import (
    create_test_drug,
    create_test_outlier,
    create_test_substance,
)

# IDs reserved for this module (>= 90000, distinct from test_outlier.py's 90050).
_SCTID = 90051
_DRUG_ID = 90051
_OUTLIER_ID = 90051
_SEGMENT_ID = 1

# the fixture outlier's own dose/frequency — the note must copy these
_OUTLIER_DOSE = 100.0
_OUTLIER_FREQUENCY = 1.0

# an outlier note is keyed with fkpresmed = 0: it belongs to no prescribed item
_OUTLIER_NOTE_PRESMED = 0


@pytest.fixture(scope="module", autouse=True)
def setup_outlier_note_data(clean_test_artifacts):  # noqa: ARG001
    """Create the drug + outlier the notes hang off, after the global cleanup."""
    create_test_substance(_SCTID, "ZZTest Outlier Note Drug", "mg")
    create_test_drug(_DRUG_ID, "ZZTest Outlier Note Drug", _SCTID)
    create_test_outlier(_OUTLIER_ID, _DRUG_ID, _SEGMENT_ID)


@pytest.fixture(autouse=True)
def clean_notes():
    """Each test starts with no note on the fixture outlier, and leaves none."""
    _delete_notes()
    yield
    _delete_notes()


def _delete_notes():
    session.execute(
        text("DELETE FROM demo.observacao WHERE idoutlier = :id"),
        {"id": _OUTLIER_ID},
    )
    session_commit()


def _read_notes() -> list[Notes]:
    """Every note row of the fixture outlier (commit first to drop any snapshot)."""
    session_commit()
    return session.query(Notes).filter(Notes.idOutlier == _OUTLIER_ID).all()


def _read_note() -> Notes:
    """The single note row of the fixture outlier, or None."""
    notes = _read_notes()
    assert len(notes) <= 1, "the outlier must never carry more than one note"
    return notes[0] if notes else None


def _read_outlier() -> Outlier:
    session_commit()
    return session.query(Outlier).filter(Outlier.id == _OUTLIER_ID).first()


def _put(client, headers, payload):
    return client.put(f"/outliers/{_OUTLIER_ID}", headers=headers, json=payload)


def test_first_note_is_created_with_the_outlier_identity(
    client, config_manager_headers
):
    """The first note inserts a row that copies the outlier's drug/dose/frequency."""
    response = _put(client, config_manager_headers, {"obs": "dose acima do usual"})

    assert response.status_code == 200

    note = _read_note()
    assert note is not None
    assert note.notes == "dose acima do usual"
    # the note stands on its own: it carries the outlier's identity, not just its id
    assert note.idSegment == _SEGMENT_ID
    assert note.idDrug == _DRUG_ID
    assert note.dose == _OUTLIER_DOSE
    assert note.frequency == _OUTLIER_FREQUENCY
    # fkpresmed = 0 is what marks it as an outlier note instead of an item note
    assert note.idPrescriptionDrug == _OUTLIER_NOTE_PRESMED
    # and the write is stamped
    assert note.update is not None
    assert note.user is not None


def test_second_note_updates_the_same_row(client, config_manager_headers):
    """A later note rewrites the existing row rather than inserting a second one.

    ``(idoutlier, fkpresmed)`` is unique, so stacking a row would fail outright;
    this pins that the service finds the existing note and overwrites its text.
    """
    _put(client, config_manager_headers, {"obs": "primeira observacao"})
    response = _put(client, config_manager_headers, {"obs": "segunda observacao"})

    assert response.status_code == 200

    notes = _read_notes()
    assert len(notes) == 1
    assert notes[0].notes == "segunda observacao"


def test_updating_a_note_keeps_the_outlier_identity(client, config_manager_headers):
    """Rewriting the text leaves the copied drug/dose/frequency in place."""
    _put(client, config_manager_headers, {"obs": "primeira"})
    _put(client, config_manager_headers, {"obs": "segunda"})

    note = _read_note()
    assert note.idDrug == _DRUG_ID
    assert note.idSegment == _SEGMENT_ID
    assert note.dose == _OUTLIER_DOSE
    assert note.frequency == _OUTLIER_FREQUENCY


@pytest.mark.parametrize("cleared", ["", None])
def test_a_note_can_be_cleared(client, config_manager_headers, cleared):
    """Sending an empty note empties the stored text instead of being ignored.

    The branch is chosen by the presence of the ``obs`` key, so an empty string
    and an explicit null both reach the write — the row survives, emptied.
    """
    _put(client, config_manager_headers, {"obs": "a remover"})
    response = _put(client, config_manager_headers, {"obs": cleared})

    assert response.status_code == 200

    note = _read_note()
    assert note is not None, "clearing the text must not delete the row"
    assert not note.notes


def test_note_and_manual_score_in_one_request_both_apply(
    client, config_manager_headers
):
    """The two edits are independent and a single request may carry both."""
    response = _put(
        client,
        config_manager_headers,
        {"manualScore": 3, "obs": "escore ajustado pelo farmaceutico"},
    )

    assert response.status_code == 200
    assert _read_outlier().manualScore == 3
    assert _read_note().notes == "escore ajustado pelo farmaceutico"


def test_a_manual_score_alone_writes_no_note(client, config_manager_headers):
    """Omitting ``obs`` leaves the note untouched — here, uncreated."""
    response = _put(client, config_manager_headers, {"manualScore": 2})

    assert response.status_code == 200
    assert _read_outlier().manualScore == 2
    assert _read_note() is None


def test_a_manual_score_alone_does_not_erase_an_existing_note(
    client, config_manager_headers
):
    """A score-only edit must not drop the justification already recorded."""
    _put(client, config_manager_headers, {"obs": "justificativa a preservar"})
    response = _put(client, config_manager_headers, {"manualScore": 4})

    assert response.status_code == 200
    assert _read_outlier().manualScore == 4
    assert _read_note().notes == "justificativa a preservar"


def test_a_note_alone_does_not_change_the_manual_score(client, config_manager_headers):
    """The mirror case: writing a note leaves the stored score alone."""
    _put(client, config_manager_headers, {"manualScore": 3})
    before = _read_outlier().manualScore

    response = _put(client, config_manager_headers, {"obs": "apenas observacao"})

    assert response.status_code == 200
    assert _read_outlier().manualScore == before


def test_note_requires_write_drug_score(client, analyst_headers):
    """Without WRITE_DRUG_SCORE the note is refused [401] and nothing is stored."""
    response = _put(client, analyst_headers, {"obs": "nao deve ser gravada"})

    assert response.status_code == 401
    assert _read_note() is None
