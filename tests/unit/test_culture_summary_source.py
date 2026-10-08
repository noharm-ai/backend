"""Unit tests for the source of the culture summary.

The antibiogram summary shown on the screening page is not computed by this
backend: the integration writes one row per (collection, drug) into the
DynamoDB table ``noharm_cultura_resumo`` and the backend only reads it back.
Two functions own that boundary and neither was covered by a test:

* ``culture_repository.get_culture_summary_from_dynamodb`` — the query itself:
  the partition key that scopes a read to one patient of one schema (the table
  is shared by every client), the table and region it talks to, the extraction
  of ``Items`` from the answer, and the short circuit that keeps the test
  suite from reaching AWS;
* ``culture_service.get_culture_summary`` — the orchestration: it hands the
  rows to the grouping and, above all, swallows a DynamoDB failure into an
  empty summary. It is called while assembling the prescription view, so an
  outage of the culture table must cost the culture card and not the whole
  screening page.

The grouping itself (``_group_by_drug``) is covered by
``tests/unit/test_culture_service.py``; what is asserted here is only that the
rows read from DynamoDB reach it.

``utils.aws`` is mocked throughout, so no AWS access happens.
"""

from contextlib import contextmanager
from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest
from boto3.dynamodb.conditions import Key

from config import Config
from models.enums import NoHarmENV
from repository import culture_repository
from services import culture_service

SCHEMA = "demo"
PATIENT_ID = 42

TABLE_NAME = "noharm_cultura_resumo"
PARTITION_KEY = "schema_fkpessoa"
REGION = "sa-east-1"


def _row(**overrides):
    """A noharm_cultura_resumo row, numbers as boto3 deserializes them."""
    row = {
        "ativo": True,
        "nomemedicamento": "OXACILINA",
        "microorganismo": "Microorganismo Teste",
        "nomematerial": "Sangue Total",
        "resultado": "Resistente",
        "fkitemexame": Decimal("172435010004"),
        "datacoleta": "2024-03-01T12:17:03",
        "dataliberacao": "2024-03-08T07:17:02",
        "chave": "SANGUE TOTAL#MICROORGANISMO TESTE#OXACILINA",
        "sctid": Decimal("1111"),
        "idclasse": "K1B1",
    }
    row.update(overrides)
    return row


@contextmanager
def table_answering(response, env=NoHarmENV.PRODUCTION.value):
    """Mock the DynamoDB table and yield it, with ``ENV`` moved off ``test``.

    ``response`` is what ``Table.query`` returns. Passing an exception instead
    makes the query raise it, which is how an outage is reproduced.
    """
    table = MagicMock()
    if isinstance(response, Exception):
        table.query.side_effect = response
    else:
        table.query.return_value = response

    with (
        patch.object(Config, "ENV", env),
        patch.object(culture_repository, "aws") as mock_aws,
    ):
        mock_aws.get_resource.return_value.Table.return_value = table
        yield mock_aws, table


def queried_key(table):
    """The key condition of the single ``query`` call."""
    table.query.assert_called_once()
    return table.query.call_args.kwargs["KeyConditionExpression"]


class TestCultureSummaryQuery:
    """Teste culture_repository - get_culture_summary_from_dynamodb"""

    def test_reads_the_culture_summary_table(self):
        """A consulta usa a tabela de resumo de culturas, na região da integração"""
        with table_answering({"Items": []}) as (mock_aws, _table):
            culture_repository.get_culture_summary_from_dynamodb(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        mock_aws.get_resource.assert_called_once_with("dynamodb", region_name=REGION)
        mock_aws.get_resource.return_value.Table.assert_called_once_with(TABLE_NAME)

    def test_partition_key_scopes_the_read_to_one_patient_of_one_schema(self):
        """A chave de partição junta schema e paciente: a tabela é compartilhada"""
        with table_answering({"Items": []}) as (_mock_aws, table):
            culture_repository.get_culture_summary_from_dynamodb(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        assert queried_key(table) == Key(PARTITION_KEY).eq(f"{SCHEMA}:{PATIENT_ID}")

    def test_another_schema_never_shares_the_partition_key(self):
        """Dois clientes com o mesmo id de paciente leem partições diferentes"""
        with table_answering({"Items": []}) as (_mock_aws, table):
            culture_repository.get_culture_summary_from_dynamodb(
                schema="other-schema", id_patient=PATIENT_ID
            )

        assert queried_key(table) != Key(PARTITION_KEY).eq(f"{SCHEMA}:{PATIENT_ID}")
        assert queried_key(table) == Key(PARTITION_KEY).eq(
            f"other-schema:{PATIENT_ID}"
        )

    def test_returns_the_items_of_the_answer(self):
        """As linhas da resposta são devolvidas como vieram"""
        rows = [_row(chave="a"), _row(chave="b")]

        with table_answering({"Items": rows}):
            result = culture_repository.get_culture_summary_from_dynamodb(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        assert result == rows

    def test_patient_without_any_collection(self):
        """Uma partição vazia devolve lista vazia"""
        with table_answering({"Items": []}):
            result = culture_repository.get_culture_summary_from_dynamodb(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        assert result == []

    def test_answer_without_items_key(self):
        """Uma resposta sem a chave Items não quebra a leitura"""
        with table_answering({"Count": 0}):
            result = culture_repository.get_culture_summary_from_dynamodb(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        assert result == []

    def test_test_environment_does_not_reach_aws(self):
        """Sob ENV=test a consulta é curto-circuitada antes de tocar a AWS"""
        with table_answering({"Items": [_row()]}, env=NoHarmENV.TEST.value) as (
            mock_aws,
            table,
        ):
            result = culture_repository.get_culture_summary_from_dynamodb(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        assert result == []
        mock_aws.get_resource.assert_not_called()
        table.query.assert_not_called()

    def test_a_dynamodb_failure_reaches_the_caller(self):
        """O repositório não engole a falha: quem trata é o serviço"""
        with table_answering(RuntimeError("dynamo is down")):
            with pytest.raises(RuntimeError):
                culture_repository.get_culture_summary_from_dynamodb(
                    schema=SCHEMA, id_patient=PATIENT_ID
                )


class TestGetCultureSummary:
    """Teste culture_service - get_culture_summary"""

    def test_asks_the_repository_for_the_patient_of_the_schema(self):
        """O schema e o paciente são repassados ao repositório"""
        with patch.object(
            culture_service.culture_repository,
            "get_culture_summary_from_dynamodb",
            return_value=[],
        ) as mock_repository:
            culture_service.get_culture_summary(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        mock_repository.assert_called_once_with(
            schema=SCHEMA, id_patient=PATIENT_ID
        )

    def test_rows_reach_the_grouping(self):
        """As linhas lidas do DynamoDB saem agrupadas por medicamento"""
        with patch.object(
            culture_service.culture_repository,
            "get_culture_summary_from_dynamodb",
            return_value=[_row(), _row(nomemedicamento="VANCOMICINA")],
        ):
            result = culture_service.get_culture_summary(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        assert [drug["drug"] for drug in result] == ["OXACILINA", "VANCOMICINA"]
        assert result[0]["items"][0]["result"] == "Resistente"

    def test_no_culture_at_all(self):
        """Um paciente sem coleta devolve resumo vazio"""
        with patch.object(
            culture_service.culture_repository,
            "get_culture_summary_from_dynamodb",
            return_value=[],
        ):
            result = culture_service.get_culture_summary(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        assert result == []

    @pytest.mark.parametrize(
        "error",
        [
            RuntimeError("dynamo is down"),
            ValueError("unexpected row"),
            Exception("boom"),
        ],
    )
    def test_a_dynamodb_outage_degrades_the_card_instead_of_the_page(self, error):
        """Uma falha no DynamoDB custa o card de culturas, não a tela inteira.

        get_culture_summary é chamada ao montar a visão da prescrição: se a
        exceção subisse, a indisponibilidade da tabela de culturas derrubaria
        a tela de triagem junto.
        """
        with patch.object(
            culture_service.culture_repository,
            "get_culture_summary_from_dynamodb",
            side_effect=error,
        ):
            result = culture_service.get_culture_summary(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        assert result == []

    def test_the_outage_is_logged(self):
        """A falha engolida deixa rastro no log, senão não sobra nada dela"""
        with (
            patch.object(
                culture_service.culture_repository,
                "get_culture_summary_from_dynamodb",
                side_effect=RuntimeError("dynamo is down"),
            ),
            patch.object(culture_service.logger, "backend_logger") as mock_logger,
        ):
            culture_service.get_culture_summary(
                schema=SCHEMA, id_patient=PATIENT_ID
            )

        mock_logger.error.assert_called_once()
        assert "dynamo is down" in mock_logger.error.call_args.args[0]
