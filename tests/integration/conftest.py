import pytest
from security.role import Role
from tests.conftest import get_access, make_headers


@pytest.fixture
def analyst_headers(client):
    """Headers with PRESCRIPTION_ANALYST role — used by most tests"""
    return make_headers(get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value]))


@pytest.fixture
def viewer_headers(client):
    """Headers with VIEWER role — used to assert 401 responses"""
    return make_headers(get_access(client, roles=[Role.VIEWER.value]))


@pytest.fixture
def user_manager_headers(client):
    """Headers with USER_MANAGER role"""
    return make_headers(get_access(client, roles=[Role.USER_MANAGER.value]))


@pytest.fixture
def config_manager_headers(client):
    """Headers with CONFIG_MANAGER role"""
    return make_headers(get_access(client, roles=[Role.CONFIG_MANAGER.value]))
