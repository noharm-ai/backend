"""Utility module for creating static user contexts with JWT authentication."""

import logging
from contextlib import contextmanager
from flask_jwt_extended import create_access_token, verify_jwt_in_request

from mobile import app
from models.main import db, User
from exception.validation_error import ValidationError
from exception.authorization_error import AuthorizationError
from utils import status


def _handle_validation_error(e: ValidationError, user_context: User):
    """Handle ValidationError with consistent logging and response format."""
    db.session.rollback()

    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")
    logger.warning(
        "(%s) VALIDATION4xx: %s",
        user_context.schema if user_context else "undefined",
        str(e),
    )
    logger.warning("schema: %s", user_context.schema if user_context else "undefined")

    return {
        "status": "error",
        "message": str(e),
        "code": e.code,
    }, e.httpStatus


def _handle_authorization_error(user_context: User):
    """Handle AuthorizationError with consistent logging and response format."""
    db.session.rollback()

    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")
    logger.warning(
        "(%s) VALIDATION4xx: static usuário inválido",
        user_context.schema if user_context else "undefined",
    )
    logger.warning("schema: %s", user_context.schema if user_context else "undefined")

    return {
        "status": "error",
        "message": "Usuário inválido",
        "code": "errors.unauthorized",
    }, status.HTTP_401_UNAUTHORIZED


def _handle_exception(e: Exception, user_context: User):
    """Handle Exception with consistent logging and response format."""
    db.session.rollback()

    logging.basicConfig()
    logger = logging.getLogger("noharm.backend")
    logger.error(str(e))
    logger.warning("schema: %s", user_context.schema if user_context else "undefined")

    return {
        "status": "error",
        "message": "Erro inesperado",
        "code": "errors.unexpectedError",
    }, status.HTTP_500_INTERNAL_SERVER_ERROR


@contextmanager
def static_user_context(schema: str):
    """
    Context manager for creating static user context with JWT authentication.

    This context manager handles:
    - Flask app context setup
    - Static user creation with STATIC_USER role
    - JWT token generation and verification
    - Request context with proper Authorization headers

    Args:
        schema (str): The database schema to use for the static user

    Yields:
        User: A configured static user context object

    Example:
        with static_user_context("my_schema") as user_context:
            # Use user_context for operations requiring static authentication
            some_service.do_something(user_context=user_context)
    """
    with app.app_context():
        # Create static user context
        user_context = User()
        user_context.id = 0
        user_context.schema = schema
        user_context.config = {"roles": ["STATIC_USER"]}

        # Create JWT claims and access token
        claims = {"schema": schema, "config": user_context.config}
        access_token = create_access_token(
            identity=user_context.id, additional_claims=claims
        )

        # Set up request context with authorization headers
        with app.test_request_context(
            headers={"Authorization": f"Bearer {access_token}"}
        ):
            verify_jwt_in_request()
            yield user_context


def execute_with_static_context(schema: str, operation_func, params: dict):
    """
    Execute a function with static user context and automatic exception handling.

    Args:
        schema (str): The database schema to use for the static user
        operation_func: The function to execute with the static context
        params: Arguments to pass to the operation function

    Returns:
        The result of the operation function, or error response tuple if exception occurred
    """
    with static_user_context(schema) as user_context:
        params["user_context"] = user_context

        try:
            result = operation_func(**params)

            db.session.commit()
            db.session.close()
            db.session.remove()

            return {"status": "success", "data": result}, status.HTTP_200_OK
        except ValidationError as e:
            return _handle_validation_error(e, user_context)
        except AuthorizationError:
            return _handle_authorization_error(user_context)
        except Exception as e:
            return _handle_exception(e, user_context)
