"""Unit tests for the cached half of the clinical-notes extraction.

``repository/clinical_notes_repository`` answers the prescription screen's
chart questions — latest vital signs and patient info, allergies, dialysis
sessions and the per-tag note counts — from one of two sources. Which one is
decided by the caller: with the Redis cache feature on it reads the entries a
previous run wrote to Redis, otherwise it queries ``demo.evolucao``.

The database half is covered end to end by
``tests/integration/test_prescription_view_clinical_notes.py``. The cached
half cannot be: ``cache_service`` short-circuits to ``None`` under
``ENV=test``, so no integration test can reach past it, and the reshaping it
guards is not trivial — the cache stores one entry per note as a list of
fragments, which has to be joined back into text, ordered newest first,
folded so a term repeated across notes is listed once, and, for the stats,
summed across every cached entry.

These tests stub ``cache_service`` with the payloads
``clinical_notes_service`` writes there, so they exercise that reshaping on
its own. Nothing touches Redis or the database.
"""

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from repository import clinical_notes_repository
from services import clinical_notes_service

ADMISSION = 4455
SCHEMA = "zztest"

_USER = SimpleNamespace(schema=SCHEMA)


def _entry(*, id_note: int, date: str, items: list):
    """One cached note, in the shape the cache refresh writes."""
    return {"fkevolucao": id_note, "dtevolucao": date, "lista": items}


@pytest.fixture
def cached_key():
    """Stub ``get_by_key`` and return the recorded (key, payload) calls."""
    calls = {}

    def _install(payload):
        def _get_by_key(key):
            calls["key"] = key
            return payload

        return patch.object(
            clinical_notes_repository.cache_service, "get_by_key", _get_by_key
        )

    return SimpleNamespace(install=_install, calls=calls)


@pytest.fixture
def cached_range():
    """Stub ``get_range`` and return the recorded (key, days_ago) calls."""
    calls = {}

    def _install(payload):
        def _get_range(key, days_ago):
            calls["key"] = key
            calls["days_ago"] = days_ago
            return payload

        return patch.object(
            clinical_notes_repository.cache_service, "get_range", _get_range
        )

    return SimpleNamespace(install=_install, calls=calls)


# --- signs and info -----------------------------------------------------------


@pytest.mark.parametrize(
    "read, cache_key",
    [
        (clinical_notes_repository.get_signs, "sinais"),
        (clinical_notes_repository.get_infos, "dados"),
    ],
    ids=["signs", "info"],
)
def test_cached_note_fragments_are_joined_back_into_one_text(
    cached_key, read, cache_key
):
    """The cache holds a note as fragments; the screen shows one sentence."""
    payload = _entry(
        id_note=91, date="2024-05-02T08:30:00", items=["PA 120x80", "FC 78"]
    )

    with cached_key.install(payload):
        result = read(admission_number=ADMISSION, user_context=_USER)

    assert result == {
        "id": "91",
        "data": "PA 120x80 FC 78",
        "date": "2024-05-02T08:30:00",
        "cache": True,
    }
    # the entry is looked up per schema and admission
    assert cached_key.calls["key"] == f"{SCHEMA}:{ADMISSION}:{cache_key}"


@pytest.mark.parametrize(
    "read",
    [clinical_notes_repository.get_signs, clinical_notes_repository.get_infos],
    ids=["signs", "info"],
)
def test_nothing_cached_reports_nothing_rather_than_falling_back(cached_key, read):
    """A cache miss is an answer: the caller asked not to query the database."""
    with cached_key.install(None):
        assert read(admission_number=ADMISSION, user_context=_USER) == {}


# --- allergies ----------------------------------------------------------------


def test_cached_allergies_are_returned_newest_first(cached_range):
    """Redis hands the entries back unordered; the newest finding leads."""
    payload = [
        _entry(id_note=11, date="2024-05-01T10:00:00", items=["Sulfa"]),
        _entry(id_note=13, date="2024-05-03T10:00:00", items=["Penicilina"]),
        _entry(id_note=12, date="2024-05-02T10:00:00", items=["Dipirona"]),
    ]

    with cached_range.install(payload):
        allergies = clinical_notes_repository.get_allergies(
            admission_number=ADMISSION, user_context=_USER
        )

    assert [a["text"] for a in allergies] == ["Penicilina", "Dipirona", "Sulfa"]
    assert allergies[0] == {
        "id": "13",
        "text": "Penicilina",
        "date": "2024-05-03T10:00:00",
        "cache": True,
        "source": "care",
    }
    # allergies are kept for the length of a long admission
    assert cached_range.calls["key"] == f"{SCHEMA}:{ADMISSION}:alergia"
    assert cached_range.calls["days_ago"] == 120


def test_an_allergy_repeated_across_notes_is_listed_once(cached_range):
    """Every note re-copies the whole allergy list; the screen shows one row."""
    payload = [
        _entry(id_note=21, date="2024-05-01T10:00:00", items=["Dipirona", "Sulfa"]),
        _entry(id_note=22, date="2024-05-04T10:00:00", items=["Dipirona", "Sulfa"]),
    ]

    with cached_range.install(payload):
        allergies = clinical_notes_repository.get_allergies(
            admission_number=ADMISSION, user_context=_USER
        )

    assert [a["text"] for a in allergies] == ["Dipirona Sulfa"]
    # kept under the most recent note that mentioned it
    assert allergies[0]["id"] == "22"


def test_no_cached_allergies_reports_an_empty_list(cached_range):
    """An admission with nothing recorded is the common case, not an error."""
    with cached_range.install(None):
        assert (
            clinical_notes_repository.get_allergies(
                admission_number=ADMISSION, user_context=_USER
            )
            == []
        )


# --- dialysis -----------------------------------------------------------------


def test_cached_dialysis_sessions_are_returned_newest_first(cached_range):
    """The most recent session decides how today's doses are adjusted."""
    payload = [
        _entry(id_note=31, date="2024-05-01T07:00:00", items=["HD", "4h"]),
        _entry(id_note=32, date="2024-05-02T07:00:00", items=["HD", "3h"]),
    ]

    with cached_range.install(payload):
        dialysis = clinical_notes_repository.get_dialysis(
            admission_number=ADMISSION, user_context=_USER
        )

    assert [d["text"] for d in dialysis] == ["HD 3h", "HD 4h"]
    assert dialysis[0] == {
        "id": "32",
        "text": "HD 3h",
        "date": "2024-05-02T07:00:00",
        "cache": True,
    }
    # only the last few days are relevant to the prescription being reviewed
    assert cached_range.calls["key"] == f"{SCHEMA}:{ADMISSION}:dialise"
    assert cached_range.calls["days_ago"] == 3


def test_a_cached_dialysis_entry_without_a_date_sorts_last(cached_range):
    """A missing timestamp must not break the ordering of the rest."""
    payload = [
        _entry(id_note=41, date=None, items=["HD sem data"]),
        _entry(id_note=42, date="2024-05-02T07:00:00", items=["HD datada"]),
    ]

    with cached_range.install(payload):
        dialysis = clinical_notes_repository.get_dialysis(
            admission_number=ADMISSION, user_context=_USER
        )

    assert [d["text"] for d in dialysis] == ["HD datada", "HD sem data"]
    assert dialysis[1]["date"] is None


def test_repeated_dialysis_sessions_are_not_folded(cached_range):
    """Unlike allergies, an identical session is listed once per cached note.

    ``get_allergies`` records each text it emits and skips the repeats;
    ``get_dialysis`` compares against a list it never adds to, so its
    equivalent check can never match. The database path folds by calendar day
    instead, so the two sources disagree here — pinned so the difference is
    deliberate rather than discovered on a chart.
    """
    payload = [
        _entry(id_note=51, date="2024-05-01T07:00:00", items=["HD"]),
        _entry(id_note=52, date="2024-05-02T07:00:00", items=["HD"]),
    ]

    with cached_range.install(payload):
        dialysis = clinical_notes_repository.get_dialysis(
            admission_number=ADMISSION, user_context=_USER
        )

    assert [d["text"] for d in dialysis] == ["HD", "HD"]


def test_no_cached_dialysis_reports_an_empty_list(cached_range):
    """Most patients are not on dialysis, so nothing cached is expected."""
    with cached_range.install(None):
        assert (
            clinical_notes_repository.get_dialysis(
                admission_number=ADMISSION, user_context=_USER
            )
            == []
        )


# --- note stats ---------------------------------------------------------------


def test_cached_stats_are_summed_across_every_entry(cached_range):
    """Each cached note counts its own findings; the badges show the total."""
    payload = [
        _entry(id_note=61, date="2024-05-01T10:00:00", items=[]),
        _entry(id_note=62, date="2024-05-02T10:00:00", items=[]),
    ]
    payload[0]["lista"] = {"sinais_count": 2, "alergia_count": 1}
    payload[1]["lista"] = {"sinais_count": 3, "dialise_count": 4}

    with cached_range.install(payload):
        stats = clinical_notes_repository.get_admission_stats(
            admission_number=ADMISSION, user_context=_USER
        )

    assert stats["signs"] == 5
    assert stats["allergy"] == 1
    assert stats["dialysis"] == 4
    # a tag no note mentioned still reports a count, so the screen can render it
    assert stats["germs"] == 0
    assert cached_range.calls["key"] == f"{SCHEMA}:{ADMISSION}:stats"
    assert cached_range.calls["days_ago"] == 6


def test_cached_stats_report_every_tag_the_screen_knows(cached_range):
    """The badge row is fixed, so the payload always carries all of its keys."""
    payload = [_entry(id_note=71, date="2024-05-01T10:00:00", items=[])]
    payload[0]["lista"] = {"sinais_count": 1}

    with cached_range.install(payload):
        stats = clinical_notes_repository.get_admission_stats(
            admission_number=ADMISSION, user_context=_USER
        )

    tags = {tag["key"] for tag in clinical_notes_service.get_tags()}
    assert set(stats) == tags
    assert stats["signs"] == 1
    assert all(stats[key] == 0 for key in tags - {"signs"})


def test_no_cached_stats_reports_no_badges_at_all(cached_range):
    """Without an entry there is nothing to count, not even a zero per tag."""
    with cached_range.install(None):
        assert (
            clinical_notes_repository.get_admission_stats(
                admission_number=ADMISSION, user_context=_USER
            )
            == {}
        )
