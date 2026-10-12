"""Unit tests for services.user_service.validate_return_integration.

When a schema has the return integration enabled (``integracao_retorno``),
NoHarm writes the pharmacist's work back to the hospital system, and the
hospital needs to know *who* did it. So, before a prescription is checked
(``prescription_check_service``) or a clinical note is recorded on a
prescription (``prescription_service``), the user must carry the external id
the hospital knows them by. This gate is what enforces it:

* a schema without the return integration lets everyone through, and the user
  record is not even looked up;
* with the return integration, a user with an external id goes through;
* a user without one — or a user record that cannot be found — is refused,
  with a message that tells them how to fix it: a user who can manage users
  (``WRITE_USERS``) is told to fill it in themselves, everyone else to ask the
  user manager.

The seed schemas all have the return integration off, so the refusal branches
were never exercised. The database session is mocked here: each model queried
answers with the record the scenario needs.
"""

from unittest.mock import MagicMock, patch

import pytest

from decorators.has_permission_decorator import Permission
from exception.validation_error import ValidationError
from models.appendix import SchemaConfig
from models.main import User
from services import user_service
from utils import status

SCHEMA = "demo"
USER_ID = 42


def _user_context():
    """The authenticated user asking for the action."""
    user_context = MagicMock()
    user_context.id = USER_ID
    user_context.schema = SCHEMA
    return user_context


def _mock_session(mock_db, return_integration, current_user):
    """Answer the schema config and the user lookups with the given records."""
    schema_config = MagicMock()
    schema_config.return_integration = return_integration

    answers = {SchemaConfig: schema_config, User: current_user}

    def query(model):
        chain = MagicMock()
        chain.filter.return_value.first.return_value = answers[model]
        return chain

    mock_db.session.query.side_effect = query


def _user(external):
    """A user record with the given external id."""
    user = MagicMock()
    user.external = external
    return user


def _queried_models(mock_db):
    """The models the gate queried, in order."""
    return [c.args[0] for c in mock_db.session.query.call_args_list]


class TestReturnIntegrationDisabled:
    """A schema that does not write back to the hospital system."""

    @patch.object(user_service, "db")
    def test_user_without_external_id_goes_through(self, mock_db):
        """Without the return integration, the external id is not required."""
        _mock_session(mock_db, return_integration=False, current_user=_user(None))

        user_service.validate_return_integration(
            user_context=_user_context(), user_permissions=[]
        )

        # the user record is not even looked up
        assert _queried_models(mock_db) == [SchemaConfig]


class TestReturnIntegrationEnabled:
    """A schema that writes the pharmacist's work back to the hospital."""

    @patch.object(user_service, "db")
    def test_user_with_external_id_goes_through(self, mock_db):
        """A user the hospital knows by an external id is let through."""
        _mock_session(mock_db, return_integration=True, current_user=_user("EXT-0001"))

        user_service.validate_return_integration(
            user_context=_user_context(), user_permissions=[]
        )

        assert _queried_models(mock_db) == [SchemaConfig, User]

    @pytest.mark.parametrize("external", [None, ""])
    @patch.object(user_service, "db")
    def test_user_without_external_id_is_told_to_ask_the_manager(
        self, mock_db, external
    ):
        """Without WRITE_USERS, the user is sent to whoever manages users."""
        _mock_session(mock_db, return_integration=True, current_user=_user(external))

        with pytest.raises(ValidationError) as error:
            user_service.validate_return_integration(
                user_context=_user_context(),
                user_permissions=[Permission.WRITE_PRESCRIPTION],
            )

        assert error.value.code == "errors.businessError"
        assert error.value.httpStatus == status.HTTP_400_BAD_REQUEST
        assert "Solicite ao usuário responsável" in str(error.value)

    @patch.object(user_service, "db")
    def test_user_manager_without_external_id_is_told_to_fill_it_in(self, mock_db):
        """With WRITE_USERS, the user is sent to the user registry instead."""
        _mock_session(mock_db, return_integration=True, current_user=_user(None))

        with pytest.raises(ValidationError) as error:
            user_service.validate_return_integration(
                user_context=_user_context(),
                user_permissions=[
                    Permission.WRITE_PRESCRIPTION,
                    Permission.WRITE_USERS,
                ],
            )

        assert error.value.code == "errors.businessError"
        assert error.value.httpStatus == status.HTTP_400_BAD_REQUEST
        assert "menu cadastro de usuários" in str(error.value)

    @patch.object(user_service, "db")
    def test_missing_user_record_is_refused(self, mock_db):
        """A user that cannot be found has no external id either."""
        _mock_session(mock_db, return_integration=True, current_user=None)

        with pytest.raises(ValidationError) as error:
            user_service.validate_return_integration(
                user_context=_user_context(), user_permissions=[]
            )

        assert error.value.code == "errors.businessError"
        assert "ID externo" in str(error.value)
