"""Unit tests for the patient name write-back (``DynamoDBNameService.update_name``).

Patient names live outside NoHarm, in whatever system the tenant runs. The only
strategy that accepts a write is DynamoDB: ``update_name`` builds a partial
``UpdateExpression`` from the fields it was given, so a caller sending just a
phone number must not blank out the stored name.

Two guards sit in front of the write and both are exercised here:

* ``extra_data`` keys are checked against ``EXTRA_DATA_ALLOWED_KEYS`` — an
  arbitrary key would otherwise be written straight into the item;
* a call carrying no field at all is rejected instead of issuing an empty
  ``SET``.

Both guards raise inside the method's own ``try``, so — like every other failure
here — they surface as the standard error response rather than as an exception.
That is what callers see, so that is what these tests assert.
"""

from unittest.mock import patch

import pytest

from services.name_service import DynamoDBNameService

PATIENT_ID = 12345
TABLE = "zztest-names"

# fictitious values: nothing here is, or resembles, a real person's data
A_NAME = "Fulano Beltrano"
A_PHONE = "(00) 90000-0000"


@pytest.fixture
def service():
    """A DynamoDB strategy pointed at a throwaway table name."""
    config = {"getname": {"token": {"url": f"dy:{TABLE}", "params": {}}, "params": {}}}
    return DynamoDBNameService(config, "test_schema")


def _error_response(id_patient=PATIENT_ID):
    return {
        "status": "error",
        "idPatient": id_patient,
        "name": f"Paciente {id_patient}",
    }


class TestUpdateNameExpression:
    """The UpdateExpression carries exactly the fields the caller sent"""

    @patch("services.name_service.aws")
    def test_name_only_updates_the_name_attribute(self, mock_aws, service):
        """A name-only call writes ``nome`` and nothing else"""
        table = mock_aws.get_resource.return_value.Table.return_value

        result = service.update_name(id_patient=PATIENT_ID, name=A_NAME)

        assert result == {"status": "success", "idPatient": PATIENT_ID}
        mock_aws.get_resource.return_value.Table.assert_called_once_with(TABLE)

        kwargs = table.update_item.call_args.kwargs
        assert kwargs["Key"] == {"schema_fkpessoa": str(PATIENT_ID)}
        assert kwargs["UpdateExpression"] == "SET #nome = :nome"
        assert kwargs["ExpressionAttributeNames"] == {"#nome": "nome"}
        assert kwargs["ExpressionAttributeValues"] == {":nome": A_NAME}

    @patch("services.name_service.aws")
    def test_extra_data_only_leaves_the_name_untouched(self, mock_aws, service):
        """Updating only an extra field must not include ``nome`` in the SET"""
        table = mock_aws.get_resource.return_value.Table.return_value

        result = service.update_name(
            id_patient=PATIENT_ID, extra_data={"fone": A_PHONE}
        )

        assert result == {"status": "success", "idPatient": PATIENT_ID}

        kwargs = table.update_item.call_args.kwargs
        assert kwargs["UpdateExpression"] == "SET #k0 = :v0"
        assert kwargs["ExpressionAttributeNames"] == {"#k0": "fone"}
        assert kwargs["ExpressionAttributeValues"] == {":v0": A_PHONE}

    @patch("services.name_service.aws")
    def test_name_and_extra_data_are_written_in_one_call(self, mock_aws, service):
        """Both parts land in a single update_item call"""
        table = mock_aws.get_resource.return_value.Table.return_value

        result = service.update_name(
            id_patient=PATIENT_ID, name=A_NAME, extra_data={"fone": A_PHONE}
        )

        assert result == {"status": "success", "idPatient": PATIENT_ID}
        table.update_item.assert_called_once()

        kwargs = table.update_item.call_args.kwargs
        assert kwargs["UpdateExpression"] == "SET #nome = :nome, #k0 = :v0"
        assert kwargs["ExpressionAttributeNames"] == {"#nome": "nome", "#k0": "fone"}
        assert kwargs["ExpressionAttributeValues"] == {
            ":nome": A_NAME,
            ":v0": A_PHONE,
        }

    @patch("services.name_service.aws")
    def test_an_empty_name_is_a_value_not_an_omission(self, mock_aws, service):
        """``name=""`` clears the stored name; only ``None`` means "leave it" """
        table = mock_aws.get_resource.return_value.Table.return_value

        result = service.update_name(id_patient=PATIENT_ID, name="")

        assert result == {"status": "success", "idPatient": PATIENT_ID}
        assert table.update_item.call_args.kwargs["ExpressionAttributeValues"] == {
            ":nome": ""
        }

    @patch("services.name_service.aws")
    def test_the_patient_id_is_used_as_a_string_key(self, mock_aws, service):
        """The partition key is stored as text, so an int id is stringified"""
        table = mock_aws.get_resource.return_value.Table.return_value

        result = service.update_name(id_patient=7, name=A_NAME)

        assert result == {"status": "success", "idPatient": 7}
        assert table.update_item.call_args.kwargs["Key"] == {"schema_fkpessoa": "7"}


class TestUpdateNameGuards:
    """Nothing is written when the request does not pass the guards"""

    @patch("services.name_service.aws")
    def test_unknown_extra_data_key_is_refused(self, mock_aws, service):
        """A key outside the allow-list never reaches DynamoDB"""
        table = mock_aws.get_resource.return_value.Table.return_value

        result = service.update_name(
            id_patient=PATIENT_ID, name=A_NAME, extra_data={"cpf": "000"}
        )

        assert result == _error_response()
        table.update_item.assert_not_called()

    @patch("services.name_service.aws")
    def test_one_unknown_key_rejects_the_whole_update(self, mock_aws, service):
        """The allowed field is dropped too: the update is all or nothing"""
        table = mock_aws.get_resource.return_value.Table.return_value

        result = service.update_name(
            id_patient=PATIENT_ID,
            extra_data={"fone": A_PHONE, "endereco": "Rua Teste, 1"},
        )

        assert result == _error_response()
        table.update_item.assert_not_called()

    @patch("services.name_service.aws")
    def test_a_call_with_no_field_is_refused(self, mock_aws, service):
        """No name and no extra data means there is nothing to SET"""
        table = mock_aws.get_resource.return_value.Table.return_value

        result = service.update_name(id_patient=PATIENT_ID)

        assert result == _error_response()
        table.update_item.assert_not_called()

    @patch("services.name_service.aws")
    def test_empty_extra_data_is_not_a_field(self, mock_aws, service):
        """An empty dict is falsy, so it cannot stand in for a real update"""
        table = mock_aws.get_resource.return_value.Table.return_value

        result = service.update_name(id_patient=PATIENT_ID, extra_data={})

        assert result == _error_response()
        table.update_item.assert_not_called()

    @patch("services.name_service.aws")
    def test_a_dynamodb_failure_is_reported_as_the_placeholder(
        self, mock_aws, service
    ):
        """An outage must not raise through to the caller"""
        table = mock_aws.get_resource.return_value.Table.return_value
        table.update_item.side_effect = RuntimeError("dynamo is down")

        result = service.update_name(id_patient=PATIENT_ID, name=A_NAME)

        assert result == _error_response()

    @patch("services.name_service.aws")
    def test_a_missing_table_configuration_is_reported_the_same_way(
        self, mock_aws, service
    ):
        """A malformed ``token.url`` cannot name a table — still no exception"""
        service.config["getname"]["token"]["url"] = "dy"

        result = service.update_name(id_patient=PATIENT_ID, name=A_NAME)

        assert result == _error_response()
        mock_aws.get_resource.return_value.Table.assert_not_called()
