"""Unit tests for the AI substance inference used by medication reconciliation.

Conciliation items are typed by hand, so they carry no drug id (``idDrug ==
"0"``) and therefore no substance. When the conciliation algorithm is set to ML,
their names are sent to the backend lambda, which answers with a SNOMED substance
id (``sctid``) per name; ``DrugList.infer_substance_ml`` writes what comes back
onto each item as ``sctid_infer``, and the prescription view renders it as a
suggestion.

Two boundaries are covered here:

- ``admin_ai_service.get_substance_by_drug_name``, the lambda call itself,
  including the guard that keeps the test environment offline;
- ``DrugList.infer_substance_ml``, which decides what is asked about and what is
  annotated — items that already have a drug id must be left alone.

The lambda is mocked, so no AWS access or database is involved.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from config import Config
from models.enums import NoHarmENV
from services.admin import admin_ai_service
from utils.drug_list import DrugList


def _lambda_returning(payload: dict) -> MagicMock:
    """A lambda client whose invocation answers with the given payload."""
    client = MagicMock()
    client.invoke.return_value = {
        "Payload": MagicMock(read=lambda: json.dumps(payload).encode("utf-8"))
    }
    return client


@pytest.fixture
def production_env(monkeypatch):
    """Leave the test-environment short circuit, so the lambda path is reached."""
    monkeypatch.setattr(Config, "ENV", NoHarmENV.PRODUCTION.value)


class TestGetSubstanceByDrugName:
    """Tests for admin_ai_service.get_substance_by_drug_name (lambda boundary)."""

    def test_test_environment_never_reaches_aws(self):
        """Under ENV=test the inference is skipped and no client is created."""
        with patch("services.admin.admin_ai_service.aws.get_client") as get_client:
            assert admin_ai_service.get_substance_by_drug_name(
                drug_names=["Dipirona 500mg"]
            ) == {}

        get_client.assert_not_called()

    def test_empty_name_list_is_not_sent(self, production_env):  # noqa: ARG002
        """Nothing to infer means no lambda invocation at all."""
        with patch("services.admin.admin_ai_service.aws.get_client") as get_client:
            assert admin_ai_service.get_substance_by_drug_name(drug_names=[]) == {}

        get_client.assert_not_called()

    def test_names_are_handed_to_the_backend_lambda(self, production_env):  # noqa: ARG002
        """The request carries the inference command and every name asked about."""
        client = _lambda_returning({"Dipirona 500mg": 26472009})

        with patch(
            "services.admin.admin_ai_service.aws.get_client", return_value=client
        ):
            result = admin_ai_service.get_substance_by_drug_name(
                drug_names=["Dipirona 500mg", "Losartana 50mg"]
            )

        assert result == {"Dipirona 500mg": 26472009}

        assert client.invoke.call_args.kwargs["FunctionName"] == (
            Config.BACKEND_FUNCTION_NAME
        )
        # the answer is needed to annotate the list, so this call is synchronous
        assert client.invoke.call_args.kwargs["InvocationType"] == "RequestResponse"
        assert json.loads(client.invoke.call_args.kwargs["Payload"]) == {
            "command": "lambda_substances.get_substance_by_name",
            "drug_names": ["Dipirona 500mg", "Losartana 50mg"],
        }

    def test_an_empty_answer_is_returned_as_is(self, production_env):  # noqa: ARG002
        """A lambda that recognizes nothing yields no inference."""
        client = _lambda_returning({})

        with patch(
            "services.admin.admin_ai_service.aws.get_client", return_value=client
        ):
            result = admin_ai_service.get_substance_by_drug_name(
                drug_names=["Nome Inexistente"]
            )

        assert result == {}


class TestInferSubstanceMl:
    """Tests for DrugList.infer_substance_ml (what is asked and what is annotated)."""

    def _items(self):
        """Two conciliation items without a drug id, plus one prescribed drug."""
        return [
            {"idDrug": "0", "drug": "Dipirona 500mg"},
            {"idDrug": "0", "drug": "Losartana 50mg"},
            {"idDrug": "123", "drug": "Omeprazol 20mg"},
        ]

    def test_only_unidentified_items_are_sent_for_inference(self):
        """Items that already carry a drug id are not asked about."""
        with patch.object(
            admin_ai_service, "get_substance_by_drug_name", return_value={}
        ) as infer:
            DrugList.infer_substance_ml(pDrugs=self._items())

        assert infer.call_args.kwargs["drug_names"] == [
            "Dipirona 500mg",
            "Losartana 50mg",
        ]

    def test_matched_names_are_annotated_with_the_substance(self):
        """A name the inference recognizes gets its sctid as a suggestion."""
        with patch.object(
            admin_ai_service,
            "get_substance_by_drug_name",
            return_value={"Dipirona 500mg": 26472009},
        ):
            result = DrugList.infer_substance_ml(pDrugs=self._items())

        assert result[0]["sctid_infer"] == 26472009

    def test_unmatched_names_are_left_without_a_suggestion(self):
        """A name the inference does not recognize stays untouched."""
        with patch.object(
            admin_ai_service,
            "get_substance_by_drug_name",
            return_value={"Dipirona 500mg": 26472009},
        ):
            result = DrugList.infer_substance_ml(pDrugs=self._items())

        assert "sctid_infer" not in result[1]

    def test_identified_drugs_are_never_annotated(self):
        """An item with a drug id keeps its substance, even on a name collision."""
        items = [
            {"idDrug": "0", "drug": "Dipirona 500mg"},
            {"idDrug": "123", "drug": "Dipirona 500mg"},
        ]

        with patch.object(
            admin_ai_service,
            "get_substance_by_drug_name",
            return_value={"Dipirona 500mg": 26472009},
        ):
            result = DrugList.infer_substance_ml(pDrugs=items)

        assert result[0]["sctid_infer"] == 26472009
        assert "sctid_infer" not in result[1]

    def test_every_item_is_kept_in_order(self):
        """Annotating the list never drops or reorders what the view renders."""
        with patch.object(
            admin_ai_service, "get_substance_by_drug_name", return_value={}
        ):
            result = DrugList.infer_substance_ml(pDrugs=self._items())

        assert [item["drug"] for item in result] == [
            "Dipirona 500mg",
            "Losartana 50mg",
            "Omeprazol 20mg",
        ]

    def test_a_list_without_conciliation_items_asks_for_nothing(self):
        """With every drug identified, the inference is called with an empty list."""
        items = [{"idDrug": "123", "drug": "Omeprazol 20mg"}]

        with patch.object(
            admin_ai_service, "get_substance_by_drug_name", return_value={}
        ) as infer:
            result = DrugList.infer_substance_ml(pDrugs=items)

        assert infer.call_args.kwargs["drug_names"] == []
        assert result == items
