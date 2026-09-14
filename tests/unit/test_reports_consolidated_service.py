"""Unit tests for services.reports.reports_consolidated_service.

The consolidated reports are not computed by this backend: each of the four
endpoints (patient-day, prescription, economy and intervention) assembles a
payload and hands it to the private backend lambda, which runs the query and
answers with the already consolidated numbers.

So what this service owns — and what is tested here — is the boundary:

* ``_invoke_report_lambda`` — the lambda call itself, the decoding of its
  answer (which may come back double encoded, as a JSON string holding JSON)
  and the translation of a lambda-reported ``error`` into an exception;
* the four report functions — the payload each one builds (command name,
  schema taken from the caller, dates serialised as ISO strings, empty filters
  normalised to ``None``), and the short circuit that returns ``{}`` without
  touching AWS when running under ``ENV=test``.

``utils.aws`` is mocked throughout, so no AWS access happens. The
``@has_permission(READ_REPORTS)`` gate resolves the caller from the JWT
identity, so the JWT lookup and the ``User`` model are patched to inject a
fabricated user inside a Flask request context.
"""

import json
from contextlib import contextmanager
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from exception.authorization_error import AuthorizationError
from mobile import app
from models.enums import NoHarmENV
from models.requests.reports_consolidated_request import (
    EconomyReportRequest,
    InterventionReportRequest,
    PatientDayReportRequest,
    PrescriptionReportRequest,
)
from security.role import Role
from services.reports import reports_consolidated_service

# a role with READ_REPORTS and one without, to exercise the permission gate
REPORT_ROLES = [Role.VIEWER.value]
NO_REPORT_ROLES = [Role.USER_MANAGER.value]

SCHEMA = "demo"


@contextmanager
def acting_as(roles, schema=SCHEMA):
    """Run the block inside a request context authenticated as ``roles``.

    Patches the permission decorator's JWT identity lookup and ``User`` model
    so the decorated service resolves a fabricated user carrying ``roles`` and
    belonging to ``schema``.
    """
    fake_user = MagicMock()
    fake_user.config = {"roles": roles}
    fake_user.schema = schema

    with app.test_request_context():
        with (
            patch(
                "decorators.has_permission_decorator.get_jwt_identity", return_value=1
            ),
            patch("decorators.has_permission_decorator.User") as mock_user_cls,
        ):
            mock_user_cls.find.return_value = fake_user
            yield


@contextmanager
def lambda_answering(payload, env=NoHarmENV.PRODUCTION.value):
    """Mock the lambda client and yield it, with ``ENV`` moved off ``test``.

    ``payload`` is what the lambda writes to its response stream: a dict is
    JSON encoded first, a string is sent as is (which is how a double encoded
    answer is reproduced).
    """
    body = payload if isinstance(payload, str) else json.dumps(payload)

    lambda_client = MagicMock()
    lambda_client.invoke.return_value = {
        "Payload": MagicMock(read=MagicMock(return_value=body.encode("utf-8")))
    }

    with (
        patch.object(Config, "ENV", env),
        patch.object(reports_consolidated_service, "aws") as mock_aws,
    ):
        mock_aws.get_client.return_value = lambda_client
        yield lambda_client


def sent_payload(lambda_client):
    """The payload of the single ``invoke`` call, decoded back into a dict."""
    lambda_client.invoke.assert_called_once()
    return json.loads(lambda_client.invoke.call_args.kwargs["Payload"])


class TestInvokeReportLambda:
    """Teste reports_consolidated_service - _invoke_report_lambda"""

    def test_invokes_the_backend_lambda_with_the_given_payload(self):
        """A chamada usa a lambda do backend, é síncrona e envia o payload informado"""
        with lambda_answering({"total": 1}) as lambda_client:
            reports_consolidated_service._invoke_report_lambda(
                payload={"command": "x", "year": 2026}, report_name="patient-day"
            )

        assert (
            lambda_client.invoke.call_args.kwargs["FunctionName"]
            == Config.BACKEND_FUNCTION_NAME
        )
        assert lambda_client.invoke.call_args.kwargs["InvocationType"] == (
            "RequestResponse"
        )
        assert sent_payload(lambda_client) == {"command": "x", "year": 2026}

    def test_returns_the_parsed_answer(self):
        """A resposta da lambda é devolvida já convertida em dict"""
        with lambda_answering({"total": 7, "rows": [{"day": 1}]}):
            result = reports_consolidated_service._invoke_report_lambda(
                payload={}, report_name="patient-day"
            )

        assert result == {"total": 7, "rows": [{"day": 1}]}

    def test_parses_a_double_encoded_answer(self):
        """Resposta codificada duas vezes (string JSON contendo JSON) também é convertida"""
        with lambda_answering(json.dumps(json.dumps({"total": 2}))):
            result = reports_consolidated_service._invoke_report_lambda(
                payload={}, report_name="prescription"
            )

        assert result == {"total": 2}

    def test_raises_with_the_report_name_and_the_lambda_message_on_error(self):
        """Erro reportado pela lambda vira exceção com o nome do relatório e a mensagem"""
        with lambda_answering({"error": True, "message": "consulta falhou"}):
            with pytest.raises(Exception) as excinfo:
                reports_consolidated_service._invoke_report_lambda(
                    payload={}, report_name="economy"
                )

        assert "economy" in str(excinfo.value)
        assert "consulta falhou" in str(excinfo.value)

    def test_raises_with_a_default_message_when_the_error_carries_none(self):
        """Erro sem mensagem usa o texto padrão"""
        with lambda_answering({"error": True}):
            with pytest.raises(Exception) as excinfo:
                reports_consolidated_service._invoke_report_lambda(
                    payload={}, report_name="intervention"
                )

        assert "Erro inesperado" in str(excinfo.value)

    def test_does_not_raise_when_the_error_flag_is_false(self):
        """error=False não interrompe: a resposta é devolvida normalmente"""
        with lambda_answering({"error": False, "total": 0}):
            result = reports_consolidated_service._invoke_report_lambda(
                payload={}, report_name="patient-day"
            )

        assert result == {"error": False, "total": 0}


class TestPatientDayReport:
    """Teste reports_consolidated_service - get_patient_day_report"""

    request_data = PatientDayReportRequest(
        year=2026,
        id_department=[1, 2],
        segment=["1"],
        start_date=date(2026, 1, 1),
        end_date=date(2026, 1, 31),
        global_score_start=0,
        global_score_end=10,
        weekdays_only=True,
    )

    def test_builds_the_patient_day_payload(self):
        """O payload leva o comando, o schema do usuário e os filtros informados"""
        with lambda_answering({}) as lambda_client:
            with acting_as(REPORT_ROLES):
                reports_consolidated_service.get_patient_day_report(
                    request_data=self.request_data
                )

        assert sent_payload(lambda_client) == {
            "command": "lambda_query_reports.get_patient_day_report",
            "schema": SCHEMA,
            "year": 2026,
            "id_department": [1, 2],
            "segment": ["1"],
            "start_date": "2026-01-01",
            "end_date": "2026-01-31",
            "global_score_start": 0,
            "global_score_end": 10,
            "weekdays_only": True,
        }

    def test_normalises_empty_filters_to_none(self):
        """Filtros vazios e datas ausentes são enviados como None"""
        with lambda_answering({}) as lambda_client:
            with acting_as(REPORT_ROLES):
                reports_consolidated_service.get_patient_day_report(
                    request_data=PatientDayReportRequest(
                        year=2026, id_department=[], segment=[]
                    )
                )

        payload = sent_payload(lambda_client)
        assert payload["id_department"] is None
        assert payload["segment"] is None
        assert payload["start_date"] is None
        assert payload["end_date"] is None

    def test_uses_the_schema_of_the_caller(self):
        """O schema enviado é o do usuário autenticado"""
        with lambda_answering({}) as lambda_client:
            with acting_as(REPORT_ROLES, schema="outro_hospital"):
                reports_consolidated_service.get_patient_day_report(
                    request_data=PatientDayReportRequest(year=2026)
                )

        assert sent_payload(lambda_client)["schema"] == "outro_hospital"

    def test_returns_the_lambda_answer(self):
        """O resultado da lambda é devolvido ao chamador"""
        with lambda_answering({"total": 3}):
            with acting_as(REPORT_ROLES):
                result = reports_consolidated_service.get_patient_day_report(
                    request_data=PatientDayReportRequest(year=2026)
                )

        assert result == {"total": 3}

    def test_returns_empty_without_calling_aws_under_test_env(self):
        """Com ENV=test o relatório volta vazio e nenhuma lambda é chamada"""
        with lambda_answering({"total": 3}, env=NoHarmENV.TEST.value) as lambda_client:
            with acting_as(REPORT_ROLES):
                result = reports_consolidated_service.get_patient_day_report(
                    request_data=self.request_data
                )

        assert result == {}
        lambda_client.invoke.assert_not_called()

    def test_requires_read_reports_permission(self):
        """Deve negar acesso a quem não tem permissão de leitura de relatórios"""
        with lambda_answering({}):
            with acting_as(NO_REPORT_ROLES):
                with pytest.raises(AuthorizationError):
                    reports_consolidated_service.get_patient_day_report(
                        request_data=self.request_data
                    )


class TestPrescriptionReport:
    """Teste reports_consolidated_service - get_prescription_report"""

    def test_builds_the_prescription_payload(self):
        """O payload leva o comando, o schema, os filtros e as opções da prescrição"""
        with lambda_answering({}) as lambda_client:
            with acting_as(REPORT_ROLES):
                reports_consolidated_service.get_prescription_report(
                    request_data=PrescriptionReportRequest(
                        year=2026,
                        id_department=[3],
                        segment=["2"],
                        start_date=date(2026, 2, 1),
                        end_date=date(2026, 2, 28),
                        global_score_start=1,
                        global_score_end=5,
                        weekdays_only=False,
                        consider_empty_prescriptions=True,
                        remove_prescription_at_discharge_date="1",
                    )
                )

        assert sent_payload(lambda_client) == {
            "command": "lambda_query_reports.get_prescription_report",
            "schema": SCHEMA,
            "year": 2026,
            "id_department": [3],
            "segment": ["2"],
            "start_date": "2026-02-01",
            "end_date": "2026-02-28",
            "global_score_start": 1,
            "global_score_end": 5,
            "weekdays_only": False,
            "consider_empty_prescriptions": True,
            "remove_prescription_at_discharge_date": "1",
        }

    def test_defaults_the_prescription_options(self):
        """Sem as opções informadas, prescrições vazias não são consideradas"""
        with lambda_answering({}) as lambda_client:
            with acting_as(REPORT_ROLES):
                reports_consolidated_service.get_prescription_report(
                    request_data=PrescriptionReportRequest(year=2026)
                )

        payload = sent_payload(lambda_client)
        assert payload["consider_empty_prescriptions"] is False
        assert payload["remove_prescription_at_discharge_date"] is None

    def test_returns_empty_without_calling_aws_under_test_env(self):
        """Com ENV=test o relatório volta vazio e nenhuma lambda é chamada"""
        with lambda_answering({"total": 1}, env=NoHarmENV.TEST.value) as lambda_client:
            with acting_as(REPORT_ROLES):
                result = reports_consolidated_service.get_prescription_report(
                    request_data=PrescriptionReportRequest(year=2026)
                )

        assert result == {}
        lambda_client.invoke.assert_not_called()

    def test_requires_read_reports_permission(self):
        """Deve negar acesso a quem não tem permissão de leitura de relatórios"""
        with lambda_answering({}):
            with acting_as(NO_REPORT_ROLES):
                with pytest.raises(AuthorizationError):
                    reports_consolidated_service.get_prescription_report(
                        request_data=PrescriptionReportRequest(year=2026)
                    )


class TestEconomyReport:
    """Teste reports_consolidated_service - get_economy_report"""

    def test_builds_the_economy_payload(self):
        """O payload leva o comando, o schema e os filtros de economia"""
        with lambda_answering({}) as lambda_client:
            with acting_as(REPORT_ROLES):
                reports_consolidated_service.get_economy_report(
                    request_data=EconomyReportRequest(
                        year=2026,
                        department=["UTI"],
                        segment=["1"],
                        start_date=date(2026, 3, 1),
                        end_date=date(2026, 3, 31),
                        economy_type=[1, 2],
                        status=["a"],
                        responsible=["10"],
                        economy_value_type="full",
                    )
                )

        assert sent_payload(lambda_client) == {
            "command": "lambda_query_reports.get_economy_report",
            "schema": SCHEMA,
            "year": 2026,
            "department": ["UTI"],
            "segment": ["1"],
            "start_date": "2026-03-01",
            "end_date": "2026-03-31",
            "economy_type": [1, 2],
            "status": ["a"],
            "responsible": ["10"],
            "economy_value_type": "full",
        }

    def test_normalises_empty_filters_to_none(self):
        """Filtros vazios são enviados como None"""
        with lambda_answering({}) as lambda_client:
            with acting_as(REPORT_ROLES):
                reports_consolidated_service.get_economy_report(
                    request_data=EconomyReportRequest(
                        year=2026,
                        department=[],
                        segment=[],
                        economy_type=[],
                        status=[],
                        responsible=[],
                        economy_value_type="",
                    )
                )

        payload = sent_payload(lambda_client)
        assert payload["department"] is None
        assert payload["segment"] is None
        assert payload["economy_type"] is None
        assert payload["status"] is None
        assert payload["responsible"] is None
        assert payload["economy_value_type"] is None

    def test_returns_empty_without_calling_aws_under_test_env(self):
        """Com ENV=test o relatório volta vazio e nenhuma lambda é chamada"""
        with lambda_answering({"total": 1}, env=NoHarmENV.TEST.value) as lambda_client:
            with acting_as(REPORT_ROLES):
                result = reports_consolidated_service.get_economy_report(
                    request_data=EconomyReportRequest(year=2026)
                )

        assert result == {}
        lambda_client.invoke.assert_not_called()

    def test_requires_read_reports_permission(self):
        """Deve negar acesso a quem não tem permissão de leitura de relatórios"""
        with lambda_answering({}):
            with acting_as(NO_REPORT_ROLES):
                with pytest.raises(AuthorizationError):
                    reports_consolidated_service.get_economy_report(
                        request_data=EconomyReportRequest(year=2026)
                    )


class TestInterventionReport:
    """Teste reports_consolidated_service - get_intervention_report"""

    def test_builds_the_intervention_payload(self):
        """O payload leva o comando, o schema e os filtros de intervenção"""
        with lambda_answering({}) as lambda_client:
            with acting_as(REPORT_ROLES):
                reports_consolidated_service.get_intervention_report(
                    request_data=InterventionReportRequest(
                        year=2026,
                        department=["UTI"],
                        segment=["1"],
                        start_date=date(2026, 4, 1),
                        end_date=date(2026, 4, 30),
                        status=["s"],
                        responsible=["10"],
                        prescriber=["Fulano Beltrano"],
                        insurance=["Convenio Teste"],
                        reason=["1"],
                    )
                )

        assert sent_payload(lambda_client) == {
            "command": "lambda_query_reports.get_intervention_report",
            "schema": SCHEMA,
            "year": 2026,
            "department": ["UTI"],
            "segment": ["1"],
            "start_date": "2026-04-01",
            "end_date": "2026-04-30",
            "status": ["s"],
            "responsible": ["10"],
            "prescriber": ["Fulano Beltrano"],
            "insurance": ["Convenio Teste"],
            "reason": ["1"],
        }

    def test_normalises_empty_filters_to_none(self):
        """Filtros vazios são enviados como None"""
        with lambda_answering({}) as lambda_client:
            with acting_as(REPORT_ROLES):
                reports_consolidated_service.get_intervention_report(
                    request_data=InterventionReportRequest(
                        year=2026,
                        department=[],
                        segment=[],
                        status=[],
                        responsible=[],
                        prescriber=[],
                        insurance=[],
                        reason=[],
                    )
                )

        payload = sent_payload(lambda_client)
        assert payload["department"] is None
        assert payload["segment"] is None
        assert payload["status"] is None
        assert payload["responsible"] is None
        assert payload["prescriber"] is None
        assert payload["insurance"] is None
        assert payload["reason"] is None

    def test_propagates_a_lambda_error(self):
        """Erro devolvido pela lambda interrompe o relatório"""
        with lambda_answering({"error": True, "message": "sem dados"}):
            with acting_as(REPORT_ROLES):
                with pytest.raises(Exception) as excinfo:
                    reports_consolidated_service.get_intervention_report(
                        request_data=InterventionReportRequest(year=2026)
                    )

        assert "intervention" in str(excinfo.value)

    def test_returns_empty_without_calling_aws_under_test_env(self):
        """Com ENV=test o relatório volta vazio e nenhuma lambda é chamada"""
        with lambda_answering({"total": 1}, env=NoHarmENV.TEST.value) as lambda_client:
            with acting_as(REPORT_ROLES):
                result = reports_consolidated_service.get_intervention_report(
                    request_data=InterventionReportRequest(year=2026)
                )

        assert result == {}
        lambda_client.invoke.assert_not_called()

    def test_requires_read_reports_permission(self):
        """Deve negar acesso a quem não tem permissão de leitura de relatórios"""
        with lambda_answering({}):
            with acting_as(NO_REPORT_ROLES):
                with pytest.raises(AuthorizationError):
                    reports_consolidated_service.get_intervention_report(
                        request_data=InterventionReportRequest(year=2026)
                    )
