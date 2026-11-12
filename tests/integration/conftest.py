import pytest

from security.role import Role
from tests.conftest import get_access, make_headers


@pytest.fixture
def analyst_headers(client):
    """Headers with PRESCRIPTION_ANALYST role — used by most tests"""
    return make_headers(get_access(client, roles=[Role.PRESCRIPTION_ANALYST.value]))


@pytest.fixture
def infection_controller_headers(client):
    """Headers with INFECTION_CONTROLLER role"""
    return make_headers(get_access(client, roles=[Role.INFECTION_CONTROLLER.value]))


@pytest.fixture
def viewer_headers(client):
    """Headers with VIEWER role — used to assert 401 responses"""
    return make_headers(get_access(client, roles=[Role.VIEWER.value]))


@pytest.fixture
def navigator_headers(client):
    """Headers with NAVIGATOR role"""
    return make_headers(get_access(client, roles=[Role.NAVIGATOR.value]))


@pytest.fixture
def navigation_viewer_headers(client):
    """Headers with NAVIGATION_VIEWER role — read-only navigator"""
    return make_headers(get_access(client, roles=[Role.NAVIGATION_VIEWER.value]))


@pytest.fixture
def analyst_navigation_viewer_headers(client):
    """Headers with PRESCRIPTION_ANALYST + NAVIGATION_VIEWER.

    NAVIGATION_VIEWER is granted on usuario_extra and added to the user's own
    roles, so READ_NAV must not unlock any navigation write next to them.
    """
    return make_headers(
        get_access(
            client,
            roles=[Role.PRESCRIPTION_ANALYST.value, Role.NAVIGATION_VIEWER.value],
        )
    )


@pytest.fixture
def training_headers(client):
    """Headers with TRAINING role — user used to record training videos"""
    return make_headers(get_access(client, roles=[Role.TRAINING.value]))


@pytest.fixture
def user_manager_headers(client):
    """Headers with USER_MANAGER role"""
    return make_headers(get_access(client, roles=[Role.USER_MANAGER.value]))


@pytest.fixture
def config_manager_headers(client):
    """Headers with CONFIG_MANAGER role"""
    return make_headers(get_access(client, roles=[Role.CONFIG_MANAGER.value]))


@pytest.fixture
def regulator_headers(client):
    """Headers with REGULATOR role"""
    return make_headers(get_access(client, roles=[Role.REGULATOR.value]))


@pytest.fixture
def admin_headers(client):
    """Headers with ADMIN role"""
    return make_headers(
        get_access(
            client,
            email="user@admin.com",
            password="useradmin",
        )
    )


@pytest.fixture
def curator_headers(client):
    """Headers with CURATOR role"""
    return make_headers(
        get_access(
            client,
            email="user@curator.com",
            password="usercurator",
        )
    )
