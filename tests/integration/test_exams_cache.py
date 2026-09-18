"""Integration tests for the exam cache used by the prescription screen.

Laboratory results reach the prescription screen through a Redis hash, one
field per exam type, under ``<schema>:<idPatient>:exames``. Two halves make up
the feature and neither was covered: ``tests/integration/test_exams.py``
patches the refresh away as out of scope, and the read side is unreachable
from a plain request because ``cache_service`` short-circuits to ``None``
under ``ENV=test``.

* **Write** — ``exams_service.refresh_exams_cache`` runs after every manual
  exam entry and rewrites the hash with the results of the last five days,
  each carrying the value, unit, date and the previous result of that type.
* **Read** — ``exams_service.find_latest_exams`` picks one of three strategies,
  chosen by two feature flags:
  - no flag: the results come from ``demo.exame``;
  - ``redisCacheExams``: the hash is used as is, and entries older than five
    days are discarded on the way out;
  - ``redisCacheExamsHybrid``: the current values are read from the database
    and only the previous result comes from the hash, so a value written
    after the last refresh is not hidden by a stale cache entry.

Redis itself is never contacted: the write tests pass a double in place of
``redis_client`` and the read tests stand in for ``cache_service.get_hgetall``.
The exam types are prefixed with ``ZZTC`` and every row created here is
removed again, since ``demo.exame`` and ``demo.segmentoexame`` are not part of
the shared cleanup.
"""

import json
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest
from redis.exceptions import RedisError
from sqlalchemy import text

from models.prescription import Patient
from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import (
    create_prescription,
    create_prescription_drug,
    test_counters,
)

_SEGMENT = 1
_DRUG = 3
_SCHEMA = "demo"

# exam types owned by this module
_SODIUM = "ZZTCNA"
_POTASSIUM = "ZZTCK"
_STALE = "ZZTCOLD"
_TYPES = [_SODIUM, _POTASSIUM, _STALE]

# seed admission used by the write tests (patient 5)
_ADMISSION = 5
_ID_PATIENT = 5

# ids reserved for the exam rows created here
_EXAM_ID = 990000


@pytest.fixture(autouse=True)
def exam_reference():
    """Configure this module's exam types on the segment, and clean up after."""
    _delete_rows()

    for position, type_exam in enumerate(_TYPES, start=1):
        session.execute(
            text(
                "INSERT INTO demo.segmentoexame "
                "  (idsegmento, tpexame, abrev, nome, min, max, referencia, "
                "   posicao, ativo, update_by) "
                "VALUES (:segment, :type, :type, :type, 1, 200, 'ZZTC ref', "
                "  :position, true, 1)"
            ),
            {"segment": _SEGMENT, "type": type_exam, "position": position},
        )
    session_commit()

    yield

    _delete_rows()


def _delete_rows():
    """Remove every exam and exam reference this module owns."""
    session.execute(
        text("DELETE FROM demo.exame WHERE tpexame = ANY(:types)"), {"types": _TYPES}
    )
    session.execute(
        text("DELETE FROM demo.segmentoexame WHERE tpexame = ANY(:types)"),
        {"types": _TYPES},
    )
    session_commit()


def _create_exam(id_patient: int, admission_number: int, type_exam: str, value: float, days_ago: int = 0):
    """Insert one result of an exam type, ``days_ago`` days back."""
    global _EXAM_ID
    _EXAM_ID += 1

    session.execute(
        text(
            "INSERT INTO demo.exame "
            "  (fkexame, fkpessoa, nratendimento, dtexame, tpexame, resultado, unidade) "
            "VALUES (:id, :patient, :admission, now() - make_interval(days => :days), "
            "  :type, :value, 'mEq/L')"
        ),
        {
            "id": _EXAM_ID,
            "patient": id_patient,
            "admission": admission_number,
            "days": days_ago,
            "type": type_exam,
            "value": value,
        },
    )
    session_commit()


def _post_exams(client, headers, exams: list[dict], redis_double):
    """Create exams through the API with ``redis_client`` replaced."""
    with patch("services.exams_service.redis_client", redis_double):
        return client.post(
            "/exams/create-multiple",
            json={"admissionNumber": _ADMISSION, "exams": exams},
            headers=headers,
        )


def _written_hash(redis_double) -> dict:
    """Rebuild the hash from the recorded ``hset`` calls."""
    written = {}
    for call in redis_double.hset.call_args_list:
        key, field, value = call.args
        written.setdefault(key, {})[field] = json.loads(value)

    return written


class TestRefresh:
    """The hash written after a manual exam entry."""

    def test_refresh_writes_one_field_per_exam_type(self, client, analyst_headers):
        """Every recent type lands in the patient hash with its value, unit and date"""
        redis_double = MagicMock()
        now = datetime.now()

        response = _post_exams(
            client,
            analyst_headers,
            [
                {"examDate": now.isoformat(), "examType": _SODIUM, "result": 140.0},
                {"examDate": now.isoformat(), "examType": _POTASSIUM, "result": 4.2},
            ],
            redis_double,
        )

        assert response.status_code == 200

        written = _written_hash(redis_double)
        key = f"{_SCHEMA}:{_ID_PATIENT}:exames"
        assert key in written

        assert written[key][_SODIUM]["value"] == pytest.approx(140.0)
        assert written[key][_POTASSIUM]["value"] == pytest.approx(4.2)
        assert written[key][_SODIUM]["date"].startswith(now.date().isoformat())

    def test_refresh_keeps_the_exam_type_as_stored(self, client, analyst_headers):
        """Fields are written uppercased, the way the read side looks them up"""
        redis_double = MagicMock()

        _post_exams(
            client,
            analyst_headers,
            [
                {
                    "examDate": datetime.now().isoformat(),
                    "examType": _SODIUM.lower(),
                    "result": 140.0,
                }
            ],
            redis_double,
        )

        key = f"{_SCHEMA}:{_ID_PATIENT}:exames"
        assert list(_written_hash(redis_double)[key]) == [_SODIUM]

    def test_refresh_carries_the_previous_result(self, client, analyst_headers):
        """The entry of a type holds the result before the latest one"""
        redis_double = MagicMock()
        now = datetime.now()

        _post_exams(
            client,
            analyst_headers,
            [
                {
                    "examDate": (now - timedelta(days=2)).isoformat(),
                    "examType": _SODIUM,
                    "result": 130.0,
                },
                {"examDate": now.isoformat(), "examType": _SODIUM, "result": 140.0},
            ],
            redis_double,
        )

        entry = _written_hash(redis_double)[f"{_SCHEMA}:{_ID_PATIENT}:exames"][_SODIUM]
        assert entry["value"] == pytest.approx(140.0)
        assert entry["prev"] == pytest.approx(130.0)

    def test_refresh_ignores_results_older_than_five_days(
        self, client, analyst_headers
    ):
        """An outdated type is left out of the hash instead of being refreshed"""
        redis_double = MagicMock()
        now = datetime.now()

        _post_exams(
            client,
            analyst_headers,
            [
                {"examDate": now.isoformat(), "examType": _SODIUM, "result": 140.0},
                {
                    "examDate": (now - timedelta(days=30)).isoformat(),
                    "examType": _STALE,
                    "result": 1.0,
                },
            ],
            redis_double,
        )

        written = _written_hash(redis_double)[f"{_SCHEMA}:{_ID_PATIENT}:exames"]
        assert _SODIUM in written
        assert _STALE not in written

    def test_an_unreachable_cache_does_not_lose_the_exam(
        self, client, analyst_headers
    ):
        """A Redis failure is swallowed: the request succeeds and the exam is stored"""
        redis_double = MagicMock()
        redis_double.hset.side_effect = RedisError("connection refused")

        response = _post_exams(
            client,
            analyst_headers,
            [
                {
                    "examDate": datetime.now().isoformat(),
                    "examType": _SODIUM,
                    "result": 140.0,
                }
            ],
            redis_double,
        )

        assert response.status_code == 200

        session_commit()
        stored = session.execute(
            text("SELECT resultado FROM demo.exame WHERE tpexame = :type"),
            {"type": _SODIUM},
        ).scalar()
        assert stored == pytest.approx(140.0)


def _flags(cache: bool = False, hybrid: bool = False):
    """Answer the two cache feature flags without touching the global memory."""
    values = {"redisCacheExams": cache, "redisCacheExamsHybrid": hybrid}

    return patch(
        "services.prescription_view_service.feature_service.has_feature_flag",
        lambda flag: values.get(flag.value, False),
    )


def _cached(payload: dict):
    """Stand in for the Redis hash read by the prescription screen."""
    return patch("services.cache_service.get_hgetall", lambda key: payload)


def _entry(value: float, prev=None, days_ago: int = 0):
    """One hash entry, in the shape the refresh writes."""
    return {
        "value": value,
        "unit": "mEq/L",
        "date": (datetime.now() - timedelta(days=days_ago)).isoformat(),
        "prev": prev,
    }


class TestRead:
    """Which source the prescription screen takes the results from."""

    @pytest.fixture
    def prescription(self):
        """A prescription of a patient owning the exams created by each test."""
        id_prescription = test_counters["id_prescription"]
        admission_number = test_counters["admission_number"]
        test_counters["id_prescription"] += 1
        test_counters["admission_number"] += 1
        id_patient = admission_number

        patient = Patient()
        patient.admissionNumber = admission_number
        patient.idPatient = id_patient
        patient.idHospital = 1
        patient.admissionDate = datetime.now()
        patient.birthdate = datetime(1960, 1, 1)
        patient.gender = "M"
        patient.weight = 70
        patient.height = 170
        session.add(patient)
        session_commit()

        create_prescription(
            id=id_prescription,
            admissionNumber=admission_number,
            idPatient=id_patient,
            idSegment=_SEGMENT,
        )
        create_prescription_drug(
            id=int(f"{id_prescription}001"),
            idPrescription=id_prescription,
            idDrug=_DRUG,
            idSegment=_SEGMENT,
        )
        session_commit()

        return id_prescription, admission_number, id_patient

    def _exams_of(self, client, headers, id_prescription: int) -> dict:
        """Read the prescription and index its exams by key."""
        response = client.get(f"/prescriptions/{id_prescription}", headers=headers)

        assert response.status_code == 200

        return {e["key"]: e["value"] for e in response.get_json()["data"]["exams"]}

    def test_without_the_flag_the_results_come_from_the_database(
        self, client, analyst_headers, prescription
    ):
        """The cache is not consulted, so a cached value cannot be served"""
        id_prescription, admission_number, id_patient = prescription
        _create_exam(id_patient, admission_number, _SODIUM, 140.0)

        with _flags(), _cached({_SODIUM: _entry(999.0)}):
            exams = self._exams_of(client, analyst_headers, id_prescription)

        assert exams[_SODIUM.lower()]["value"] == pytest.approx(140.0)

    def test_the_cache_answers_on_its_own(
        self, client, analyst_headers, prescription
    ):
        """With redisCacheExams the hash replaces the query, values included"""
        id_prescription, admission_number, id_patient = prescription
        _create_exam(id_patient, admission_number, _SODIUM, 140.0)

        cached = {
            _SODIUM: _entry(999.0, prev=111.0),
            # never written to demo.exame: it can only come from the cache
            _POTASSIUM: _entry(3.3),
        }

        with _flags(cache=True), _cached(cached):
            exams = self._exams_of(client, analyst_headers, id_prescription)

        assert exams[_SODIUM.lower()]["value"] == pytest.approx(999.0)
        assert exams[_SODIUM.lower()]["prev"] == pytest.approx(111.0)
        assert exams[_POTASSIUM.lower()]["value"] == pytest.approx(3.3)

    def test_a_stale_cache_entry_is_discarded(
        self, client, analyst_headers, prescription
    ):
        """An entry older than five days is dropped instead of being shown"""
        id_prescription, _, _ = prescription

        cached = {_SODIUM: _entry(140.0), _STALE: _entry(1.0, days_ago=30)}

        with _flags(cache=True), _cached(cached):
            exams = self._exams_of(client, analyst_headers, id_prescription)

        assert exams[_SODIUM.lower()]["value"] == pytest.approx(140.0)
        assert exams[_STALE.lower()]["value"] is None

    def test_the_hybrid_read_prefers_the_stored_value(
        self, client, analyst_headers, prescription
    ):
        """The value comes from the database and only the previous one from the cache"""
        id_prescription, admission_number, id_patient = prescription
        _create_exam(id_patient, admission_number, _SODIUM, 140.0)

        with _flags(cache=True, hybrid=True), _cached(
            {_SODIUM: _entry(999.0, prev=120.0)}
        ):
            exams = self._exams_of(client, analyst_headers, id_prescription)

        assert exams[_SODIUM.lower()]["value"] == pytest.approx(140.0)
        assert exams[_SODIUM.lower()]["prev"] == pytest.approx(120.0)

    def test_the_hybrid_read_survives_a_cache_miss(
        self, client, analyst_headers, prescription
    ):
        """A type absent from the hash keeps its value and loses only the comparison"""
        id_prescription, admission_number, id_patient = prescription
        _create_exam(id_patient, admission_number, _SODIUM, 140.0)
        _create_exam(id_patient, admission_number, _POTASSIUM, 4.2)

        with _flags(cache=True, hybrid=True), _cached(
            {_SODIUM: _entry(140.0, prev=120.0)}
        ):
            exams = self._exams_of(client, analyst_headers, id_prescription)

        assert exams[_POTASSIUM.lower()]["value"] == pytest.approx(4.2)
        assert not exams[_POTASSIUM.lower()]["prev"]

    def test_an_empty_cache_falls_back_to_the_database(
        self, client, analyst_headers, prescription
    ):
        """Nothing cached yet: the results are still read from demo.exame"""
        id_prescription, admission_number, id_patient = prescription
        _create_exam(id_patient, admission_number, _SODIUM, 140.0)

        for flags in (_flags(cache=True), _flags(cache=True, hybrid=True)):
            with flags, _cached(None):
                exams = self._exams_of(client, analyst_headers, id_prescription)

            assert exams[_SODIUM.lower()]["value"] == pytest.approx(140.0)
