"""Unit tests for ``exams_service.DynamoExam``.

Exams reach the backend from two places: the ``exame`` table in PostgreSQL and
the ``noharm_exame`` DynamoDB table the integration writes to. ``DynamoExam``
is the adapter that makes a raw DynamoDB item look like an ``Exams`` row, so
the rest of ``get_exams_by_admission`` can treat both sources alike.

It has to be forgiving: DynamoDB items are schemaless, results arrive as
strings (or not at all) and the exam date may be a string, a real datetime or
something unparseable. A row that cannot produce a date is later dropped by the
caller, which is why a bad date turns into ``None`` instead of raising.
"""

from datetime import datetime

import pytest

from services.exams_service import DynamoExam


def _item(**overrides):
    """A complete DynamoDB exam item, with the fields under test overridable."""
    item = {
        "fkexame": 555,
        "fkpessoa": 77,
        "fkprescricao": 999,
        "nratendimento": 42,
        "tpexame": "tgo",
        "resultado": "12.5",
        "unidade": "U/L",
        "dtexame": "2026-01-20T08:30:00",
    }
    item.update(overrides)

    return item


class TestIdentifiers:
    """Teste DynamoExam - identifier mapping"""

    def test_maps_every_identifier(self):
        """Each DynamoDB key lands on the attribute name the exam list reads."""
        exam = DynamoExam(_item())

        assert exam.idExame == 555
        assert exam.idPatient == 77
        assert exam.idPrescription == 999
        assert exam.admissionNumber == 42
        assert exam.typeExam == "tgo"
        assert exam.unit == "U/L"

    def test_prescription_and_admission_default_to_zero(self):
        """A result not tied to a prescription/admission still yields a usable row."""
        item = _item()
        del item["fkprescricao"]
        del item["nratendimento"]

        exam = DynamoExam(item)

        assert exam.idPrescription == 0
        assert exam.admissionNumber == 0

    def test_missing_identifiers_are_none(self):
        """Absent keys become None rather than raising."""
        exam = DynamoExam({})

        assert exam.idExame is None
        assert exam.idPatient is None
        assert exam.typeExam is None
        assert exam.unit is None

    def test_created_by_is_always_none(self):
        """Integration results are never manual, so they carry no author."""
        assert DynamoExam(_item()).created_by is None


class TestValue:
    """Teste DynamoExam - result conversion"""

    def test_string_result_becomes_a_float(self):
        """DynamoDB stores the result as a string; the exam list expects a number."""
        exam = DynamoExam(_item(resultado="12.5"))

        assert exam.value == 12.5
        assert isinstance(exam.value, float)

    def test_numeric_result_is_kept(self):
        """An already numeric result survives the conversion."""
        assert DynamoExam(_item(resultado=3)).value == 3.0

    @pytest.mark.parametrize("empty", [None, "", 0])
    def test_falsy_results_become_none(self, empty):
        """A blank result is reported as absent. A numeric zero reads as blank too."""
        assert DynamoExam(_item(resultado=empty)).value is None

    def test_a_zero_written_as_a_string_is_kept(self):
        """A zero written as a string is a real measurement: only a falsy raw value reads as absent."""
        assert DynamoExam(_item(resultado="0")).value == 0.0

    def test_missing_result_is_none(self):
        """A pending exam carries no result at all."""
        item = _item()
        del item["resultado"]

        assert DynamoExam(item).value is None


class TestDate:
    """Teste DynamoExam - exam date parsing"""

    def test_iso_string_is_parsed(self):
        """The usual shape: an ISO timestamp written by the integration."""
        exam = DynamoExam(_item(dtexame="2026-01-20T08:30:00"))

        assert exam.date == datetime(2026, 1, 20, 8, 30)

    def test_datetime_is_kept_as_is(self):
        """An item already deserialized into a datetime is not re-parsed."""
        moment = datetime(2026, 1, 20, 8, 30)

        assert DynamoExam(_item(dtexame=moment)).date is moment

    def test_unparseable_date_becomes_none(self):
        """A malformed date drops the row instead of breaking the whole exam list."""
        assert DynamoExam(_item(dtexame="not a date")).date is None

    def test_missing_date_becomes_none(self):
        """Same for an item with no date at all."""
        item = _item()
        del item["dtexame"]

        assert DynamoExam(item).date is None
