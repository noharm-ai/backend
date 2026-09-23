"""Unit tests for the writing half of the clinical-notes Redis cache.

The prescription screen reads a patient's allergies, dialysis sessions and
latest vital signs from Redis rather than from ``demo.evolucao`` -- that side,
and the reshaping it does, is covered by
``tests/unit/test_clinical_notes_cache_reads.py``. ``clinical_notes_service``
owns the other end: three refreshers that read the notes back out of the
database and rewrite the entries those reads depend on.

Two of them run whenever a pharmacist removes an annotation from a note
(``POST /notes/remove-annotation``): striking an allergy off a chart has to
take it off every screen showing it, and an entry left behind keeps warning
about an allergy the patient does not have. The third rewrites the vital-signs
and patient-info entries.

None of this can be reached from an integration test. ``ENV=test`` has no
Redis, so the first command inside each refresher raises and
``cache_service.tolerate_failure`` -- deliberately, since a cold cache must not
break a prescription -- swallows it before any entry is built. These tests put
a recording double in place of the client instead, so the payloads, the keys
and the retention each refresher writes are pinned. Nothing touches Redis or
the database.
"""

import json
import time
from contextlib import ExitStack, contextmanager
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from redis.exceptions import ConnectionError as RedisConnectionError

from repository import clinical_notes_repository
from services import clinical_notes_service

# undecorated business logic (skips the permission gate)
_refresh_stats = clinical_notes_service.refresh_clinical_notes_stats_cache.__wrapped__
_refresh_dialysis = clinical_notes_service.refresh_dialysis_cache.__wrapped__
_refresh_allergies = clinical_notes_service.refresh_allergies_cache.__wrapped__

SCHEMA = "zztest"
ADMISSION = 4455

_USER = SimpleNamespace(schema=SCHEMA, id=1)

DAY = 24 * 60 * 60


class _FakeJson:
    """The ``.json()`` handle of the redis client."""

    def __init__(self, recorder):
        self._recorder = recorder

    def set(self, key, path, value):
        self._recorder.calls.append(("json.set", key, path, value))
        self._recorder.entries[key] = value


class FakeRedis:
    """Records every command instead of talking to a server."""

    def __init__(self, fail_with=None):
        self.calls = []
        self.entries = {}
        self.sorted_sets = {}
        self._fail_with = fail_with

    def _maybe_fail(self):
        if self._fail_with is not None:
            raise self._fail_with

    def json(self):
        self._maybe_fail()
        return _FakeJson(self)

    def expire(self, key, seconds):
        self._maybe_fail()
        self.calls.append(("expire", key, seconds))

    def delete(self, key):
        self._maybe_fail()
        self.calls.append(("delete", key))
        self.sorted_sets.pop(key, None)

    def zadd(self, key, mapping):
        self._maybe_fail()
        self.calls.append(("zadd", key, mapping))
        self.sorted_sets.setdefault(key, {}).update(mapping)

    def zremrangebyscore(self, key, min, max):  # noqa: A002 - redis' own signature
        self._maybe_fail()
        self.calls.append(("zremrangebyscore", key, min, max))

    # helpers for the assertions

    def commands(self, name):
        """Every recorded call of one command, in order."""
        return [call for call in self.calls if call[0] == name]

    def members(self, key):
        """The entries of a sorted set, decoded, highest score first."""
        items = sorted(self.sorted_sets.get(key, {}).items(), key=lambda i: -i[1])
        return [json.loads(raw) for raw, _ in items]

    def scores(self, key):
        """The scores of a sorted set, in insertion order."""
        return list(self.sorted_sets.get(key, {}).values())


@contextmanager
def refreshing(client, **rows):
    """Point the service at the recording client and at canned note rows.

    Every keyword is a ``clinical_notes_repository`` reader to stub and the
    value it should answer with.
    """
    with ExitStack() as stack:
        stack.enter_context(
            patch.object(clinical_notes_service, "redis_client", client)
        )
        for name, value in rows.items():
            stack.enter_context(
                patch.object(
                    clinical_notes_service.clinical_notes_repository,
                    name,
                    _answering(value),
                )
            )
        yield


def _answering(value):
    """A repository reader that ignores its arguments and answers ``value``."""

    def _reader(**kwargs):
        return value

    return _reader


def _note(*, id_note: int, date: datetime, annotations):
    """One row as ``get_dialysis_cache``/``get_allergies_cache`` returns it."""
    return SimpleNamespace(id=id_note, date=date, annotations=annotations)


def _expected_score(moment: datetime) -> int:
    """The score a note's timestamp is stored under, in local time."""
    return int(time.mktime(moment.replace(microsecond=0).timetuple()))


# --- signs and info -----------------------------------------------------------


def test_signs_and_info_are_written_as_one_entry_each():
    """Each refresh replaces the single entry the screen reads back."""
    client = FakeRedis()
    signs = {"id": 91, "data": "PA 120x80 FC 78", "date": "2024-05-02T08:30:00"}
    infos = {"id": 92, "data": "Paciente lúcido", "date": "2024-05-02T09:00:00"}

    with refreshing(client, get_signs=signs, get_infos=infos):
        _refresh_stats(admission_number=ADMISSION, user_context=_USER)

    assert client.entries[f"{SCHEMA}:{ADMISSION}:sinais"] == {
        "dtevolucao": "2024-05-02T08:30:00",
        "fkevolucao": 91,
        "lista": ["PA 120x80 FC 78"],
    }
    assert client.entries[f"{SCHEMA}:{ADMISSION}:dados"] == {
        "dtevolucao": "2024-05-02T09:00:00",
        "fkevolucao": 92,
        "lista": ["Paciente lúcido"],
    }


def test_signs_and_info_entries_are_kept_for_thirty_days():
    """An admission outlives a single prescription, the entry has to too."""
    client = FakeRedis()

    with refreshing(
        client,
        get_signs={"id": 1, "data": "PA 120x80", "date": "2024-05-02T08:30:00"},
        get_infos={"id": 2, "data": "Sem queixas", "date": "2024-05-02T09:00:00"},
    ):
        _refresh_stats(admission_number=ADMISSION, user_context=_USER)

    assert client.commands("expire") == [
        ("expire", f"{SCHEMA}:{ADMISSION}:sinais", 30 * DAY),
        ("expire", f"{SCHEMA}:{ADMISSION}:dados", 30 * DAY),
    ]


def test_an_admission_with_nothing_recorded_writes_no_entry():
    """Nothing found is not an empty entry: a stale one is better than none."""
    client = FakeRedis()

    with refreshing(client, get_signs={}, get_infos={}):
        _refresh_stats(admission_number=ADMISSION, user_context=_USER)

    assert client.calls == []


def test_the_refresh_reads_past_the_cache_it_is_rewriting():
    """Reading through the cache would write back what is already there."""
    client = FakeRedis()
    seen = {}

    def _record(name):
        def _reader(**kwargs):
            seen[name] = kwargs
            return {}

        return _reader

    with (
        patch.object(clinical_notes_service, "redis_client", client),
        patch.object(
            clinical_notes_service.clinical_notes_repository,
            "get_signs",
            _record("signs"),
        ),
        patch.object(
            clinical_notes_service.clinical_notes_repository,
            "get_infos",
            _record("infos"),
        ),
    ):
        _refresh_stats(admission_number=ADMISSION, user_context=_USER)

    assert seen["signs"]["cache"] is False
    assert seen["infos"]["cache"] is False


def test_what_the_refresh_writes_is_what_the_screen_reads_back():
    """The two halves of the cache agree on the payload shape."""
    client = FakeRedis()

    with refreshing(
        client,
        get_signs={"id": 91, "data": "PA 120x80 FC 78", "date": "2024-05-02T08:30:00"},
        get_infos={},
    ):
        _refresh_stats(admission_number=ADMISSION, user_context=_USER)

    with patch.object(
        clinical_notes_repository.cache_service,
        "get_by_key",
        lambda key: client.entries.get(key),
    ):
        assert clinical_notes_repository.get_signs(
            admission_number=ADMISSION, user_context=_USER
        ) == {
            "id": "91",
            "data": "PA 120x80 FC 78",
            "date": "2024-05-02T08:30:00",
            "cache": True,
        }


# --- dialysis -----------------------------------------------------------------


def test_every_annotated_dialysis_note_becomes_one_scored_entry():
    """The screen orders sessions by score, so each note carries its timestamp."""
    client = FakeRedis()
    older = datetime(2024, 5, 1, 7, 0, 0)
    newer = datetime(2024, 5, 2, 7, 30, 0)
    notes = [
        _note(id_note=32, date=newer, annotations={"dialise": ["HD", "3h"]}),
        _note(id_note=31, date=older, annotations={"dialise": ["HD", "4h"]}),
    ]

    with refreshing(client, get_dialysis_cache=notes):
        _refresh_dialysis(admission_number=ADMISSION, user_context=_USER)

    key = f"{SCHEMA}:{ADMISSION}:dialise"
    assert client.members(key) == [
        {"dtevolucao": "2024-05-02T07:30:00", "fkevolucao": 32, "lista": ["HD", "3h"]},
        {"dtevolucao": "2024-05-01T07:00:00", "fkevolucao": 31, "lista": ["HD", "4h"]},
    ]
    assert sorted(client.scores(key)) == sorted(
        [_expected_score(newer), _expected_score(older)]
    )


def test_the_dialysis_key_is_emptied_before_it_is_rewritten():
    """A session removed from a note must not survive in the cache."""
    client = FakeRedis()
    notes = [
        _note(
            id_note=31,
            date=datetime(2024, 5, 1, 7, 0, 0),
            annotations={"dialise": ["HD"]},
        )
    ]

    with refreshing(client, get_dialysis_cache=notes):
        _refresh_dialysis(admission_number=ADMISSION, user_context=_USER)

    assert client.calls[0] == ("delete", f"{SCHEMA}:{ADMISSION}:dialise")


def test_an_admission_with_no_dialysis_only_clears_the_key():
    """The common case: the patient is not on dialysis at all."""
    client = FakeRedis()

    with refreshing(client, get_dialysis_cache=[]):
        _refresh_dialysis(admission_number=ADMISSION, user_context=_USER)

    assert client.calls == [("delete", f"{SCHEMA}:{ADMISSION}:dialise")]


def test_a_dialysis_note_without_annotations_is_skipped():
    """Only the extracted annotations are cached, never the raw note."""
    client = FakeRedis()
    notes = [
        _note(id_note=31, date=datetime(2024, 5, 1, 7, 0, 0), annotations=None),
        _note(id_note=32, date=datetime(2024, 5, 2, 7, 0, 0), annotations={}),
        _note(
            id_note=33,
            date=datetime(2024, 5, 3, 7, 0, 0),
            annotations={"dialise": ["HD"]},
        ),
    ]

    with refreshing(client, get_dialysis_cache=notes):
        _refresh_dialysis(admission_number=ADMISSION, user_context=_USER)

    stored = client.members(f"{SCHEMA}:{ADMISSION}:dialise")
    assert [entry["fkevolucao"] for entry in stored] == [33]


def test_a_note_annotated_for_something_else_is_cached_as_no_session():
    """A note carrying only, say, an allergy still counts as read."""
    client = FakeRedis()
    notes = [
        _note(
            id_note=31,
            date=datetime(2024, 5, 1, 7, 0, 0),
            annotations={"allergiesComposed": ["Dipirona"]},
        )
    ]

    with refreshing(client, get_dialysis_cache=notes):
        _refresh_dialysis(admission_number=ADMISSION, user_context=_USER)

    assert client.members(f"{SCHEMA}:{ADMISSION}:dialise") == [
        {"dtevolucao": "2024-05-01T07:00:00", "fkevolucao": 31, "lista": []}
    ]


def test_dialysis_entries_older_than_ten_days_are_dropped():
    """Only recent sessions change how today's doses are adjusted."""
    client = FakeRedis()
    notes = [
        _note(
            id_note=31,
            date=datetime(2024, 5, 1, 7, 0, 0),
            annotations={"dialise": ["HD"]},
        )
    ]

    with refreshing(client, get_dialysis_cache=notes):
        _refresh_dialysis(admission_number=ADMISSION, user_context=_USER)

    key = f"{SCHEMA}:{ADMISSION}:dialise"
    trim = client.commands("zremrangebyscore")
    assert len(trim) == 1
    assert trim[0][1] == key
    assert trim[0][2] == 0
    assert trim[0][3] == pytest.approx(int(time.time()) - 10 * DAY, abs=5)
    assert client.commands("expire") == [("expire", key, 10 * DAY)]


def test_a_dialysis_timestamp_is_stored_without_microseconds():
    """The score is parsed back from the text, which has no sub-second part."""
    client = FakeRedis()
    moment = datetime(2024, 5, 1, 7, 0, 0, 123456)
    notes = [_note(id_note=31, date=moment, annotations={"dialise": ["HD"]})]

    with refreshing(client, get_dialysis_cache=notes):
        _refresh_dialysis(admission_number=ADMISSION, user_context=_USER)

    key = f"{SCHEMA}:{ADMISSION}:dialise"
    assert client.members(key)[0]["dtevolucao"] == "2024-05-01T07:00:00"
    assert client.scores(key) == [_expected_score(moment)]


# --- allergies ----------------------------------------------------------------


def test_every_annotated_allergy_note_becomes_one_scored_entry():
    """Allergies are cached per note, the same way sessions are."""
    client = FakeRedis()
    moment = datetime(2024, 5, 3, 10, 0, 0)
    notes = [
        _note(
            id_note=13,
            date=moment,
            annotations={"allergiesComposed": ["Penicilina", "Sulfa"]},
        )
    ]

    with refreshing(client, get_allergies_cache=notes):
        _refresh_allergies(admission_number=ADMISSION, user_context=_USER)

    key = f"{SCHEMA}:{ADMISSION}:alergia"
    assert client.members(key) == [
        {
            "dtevolucao": "2024-05-03T10:00:00",
            "fkevolucao": 13,
            "lista": ["Penicilina", "Sulfa"],
        }
    ]
    assert client.scores(key) == [_expected_score(moment)]


def test_the_allergy_key_is_emptied_before_it_is_rewritten():
    """This is what makes a removed allergy disappear from the chart."""
    client = FakeRedis()

    with refreshing(client, get_allergies_cache=[]):
        _refresh_allergies(admission_number=ADMISSION, user_context=_USER)

    assert client.calls == [("delete", f"{SCHEMA}:{ADMISSION}:alergia")]


def test_an_allergy_note_without_annotations_is_skipped():
    """A note with nothing extracted contributes no entry."""
    client = FakeRedis()
    notes = [
        _note(id_note=11, date=datetime(2024, 5, 1, 10, 0, 0), annotations=None),
        _note(
            id_note=12,
            date=datetime(2024, 5, 2, 10, 0, 0),
            annotations={"allergiesComposed": ["Dipirona"]},
        ),
    ]

    with refreshing(client, get_allergies_cache=notes):
        _refresh_allergies(admission_number=ADMISSION, user_context=_USER)

    stored = client.members(f"{SCHEMA}:{ADMISSION}:alergia")
    assert [entry["fkevolucao"] for entry in stored] == [12]


def test_allergy_entries_are_kept_for_the_length_of_an_admission():
    """An allergy stays relevant far longer than a dialysis session."""
    client = FakeRedis()
    notes = [
        _note(
            id_note=11,
            date=datetime(2024, 5, 1, 10, 0, 0),
            annotations={"allergiesComposed": ["Dipirona"]},
        )
    ]

    with refreshing(client, get_allergies_cache=notes):
        _refresh_allergies(admission_number=ADMISSION, user_context=_USER)

    key = f"{SCHEMA}:{ADMISSION}:alergia"
    assert client.commands("expire") == [("expire", key, 120 * DAY)]
    # unlike dialysis, nothing is trimmed by age: the query feeding this
    # refresh already stops at the same 120 day cutoff the read window uses
    assert client.commands("zremrangebyscore") == []


# --- best effort --------------------------------------------------------------


@pytest.mark.parametrize(
    "refresh, rows",
    [
        (
            _refresh_stats,
            {
                "get_signs": {
                    "id": 1,
                    "data": "PA 120x80",
                    "date": "2024-05-01T08:00:00",
                },
                "get_infos": {},
            },
        ),
        (_refresh_dialysis, {"get_dialysis_cache": []}),
        (_refresh_allergies, {"get_allergies_cache": []}),
    ],
    ids=["stats", "dialysis", "allergies"],
)
def test_an_unreachable_cache_does_not_break_the_caller(refresh, rows):
    """Removing an annotation must succeed even with Redis down."""
    client = FakeRedis(fail_with=RedisConnectionError("no route to host"))

    with refreshing(client, **rows):
        refresh(admission_number=ADMISSION, user_context=_USER)
