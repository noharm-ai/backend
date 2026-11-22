"""Unit tests for services.organization_service (docs/agents/organizations.md).

The access rules of an ORGANIZATION_MANAGER: which schemas a usuario_extra
config grants, directly (the fixed ``schemas`` list) or through an
organization (``organization: {"id", "allSchemas"}``). The organization's
schemas come from ``organization_repository``, mocked here: the rules are
pure Python and the integration side is covered by
tests/integration/test_organization_schemas.py.
"""

from unittest.mock import patch

import pytest

from security.role import Role
from services import organization_service

MANAGER = Role.ORGANIZATION_MANAGER.value
NAVIGATOR = Role.NAVIGATOR.value

ORG_SCHEMAS = [
    {"name": "hospital_a", "friendlyName": "Hospital A"},
    {"name": "hospital_b", "friendlyName": "Hospital B"},
]


@pytest.fixture
def org_repository():
    """Mock the repository answering the schemas of organization 7"""
    with patch(
        "services.organization_service.organization_repository"
        ".get_organization_schemas",
        return_value=[dict(s) for s in ORG_SCHEMAS],
    ) as mock:
        yield mock


class TestGetOrganizationGrant:
    """get_organization_grant: the grant counts only when well formed and the
    config carries ORGANIZATION_MANAGER"""

    def test_valid_grant(self):
        """A manager with an int id and allSchemas true gets the full grant"""
        config = {"roles": [MANAGER], "organization": {"id": 7, "allSchemas": True}}

        assert organization_service.get_organization_grant(config) == {
            "id": 7,
            "allSchemas": True,
        }

    def test_all_schemas_defaults_to_false(self):
        """Without allSchemas the grant keeps only the fixed list"""
        config = {"roles": [MANAGER], "organization": {"id": 7}}

        assert organization_service.get_organization_grant(config) == {
            "id": 7,
            "allSchemas": False,
        }

    @pytest.mark.parametrize("value", ["true", 1, "yes", None, [True]])
    def test_all_schemas_must_be_exactly_true(self, value):
        """allSchemas counts only as the boolean true; any other value reads as False"""
        config = {"roles": [MANAGER], "organization": {"id": 7, "allSchemas": value}}

        assert organization_service.get_organization_grant(config)["allSchemas"] is False

    @pytest.mark.parametrize("config", [None, [], "config", 7])
    def test_config_not_a_dict(self, config):
        """A missing or malformed config grants nothing"""
        assert organization_service.get_organization_grant(config) is None

    @pytest.mark.parametrize(
        "roles", [None, [], [NAVIGATOR], MANAGER, {"role": MANAGER}]
    )
    def test_requires_the_manager_role(self, roles):
        """A NAVIGATOR, a former manager or malformed roles get no grant"""
        config = {"roles": roles, "organization": {"id": 7, "allSchemas": True}}

        assert organization_service.get_organization_grant(config) is None

    def test_missing_roles(self):
        """A config without roles gets no grant"""
        config = {"organization": {"id": 7, "allSchemas": True}}

        assert organization_service.get_organization_grant(config) is None

    @pytest.mark.parametrize("organization", [None, 7, "7", [7], True])
    def test_organization_not_a_dict(self, organization):
        """A malformed organization key grants nothing"""
        config = {"roles": [MANAGER], "organization": organization}

        assert organization_service.get_organization_grant(config) is None

    @pytest.mark.parametrize("raw_id", [None, "7", 7.0, True, False, [7]])
    def test_id_must_be_an_int(self, raw_id):
        """The id must be an int (a bool, though an int in Python, is refused)"""
        config = {
            "roles": [MANAGER],
            "organization": {"id": raw_id, "allSchemas": True},
        }

        assert organization_service.get_organization_grant(config) is None

    def test_manager_among_other_roles(self):
        """The manager role counts next to other roles"""
        config = {
            "roles": [NAVIGATOR, MANAGER],
            "organization": {"id": 7, "allSchemas": True},
        }

        assert organization_service.get_organization_grant(config)["id"] == 7


class TestGetExtraSchemas:
    """get_extra_schemas: the fixed list plus, with allSchemas, the
    organization's current schemas"""

    @pytest.mark.parametrize("config", [None, [], "config"])
    def test_config_not_a_dict(self, config, org_repository):
        """A missing or malformed config grants no schema"""
        assert organization_service.get_extra_schemas(config) == []
        org_repository.assert_not_called()

    def test_no_schemas_key(self, org_repository):
        """A config without schemas nor organization grants nothing"""
        assert organization_service.get_extra_schemas({"roles": [NAVIGATOR]}) == []
        org_repository.assert_not_called()

    @pytest.mark.parametrize("schemas", [None, "hospital_a", {"name": "hospital_a"}])
    def test_malformed_schemas_list(self, schemas, org_repository):
        """A fixed list that is not a list is ignored"""
        assert organization_service.get_extra_schemas({"schemas": schemas}) == []

    def test_fixed_list_only(self, org_repository):
        """Without an organization grant only the fixed list counts"""
        fixed = [{"name": "hospital_c", "friendlyName": "Hospital C"}]

        result = organization_service.get_extra_schemas(
            {"roles": [NAVIGATOR], "schemas": fixed}
        )

        assert result == fixed
        org_repository.assert_not_called()

    def test_fixed_list_is_not_mutated(self, org_repository):
        """The config's own list is never extended in place"""
        fixed = [{"name": "hospital_c", "friendlyName": "Hospital C"}]
        config = {
            "roles": [MANAGER],
            "organization": {"id": 7, "allSchemas": True},
            "schemas": fixed,
        }

        organization_service.get_extra_schemas(config)

        assert fixed == [{"name": "hospital_c", "friendlyName": "Hospital C"}]

    def test_organization_without_all_schemas(self, org_repository):
        """allSchemas false keeps the fixed list and never reads the organization"""
        fixed = [{"name": "hospital_a", "friendlyName": "Hospital A"}]
        config = {
            "roles": [MANAGER],
            "organization": {"id": 7, "allSchemas": False},
            "schemas": fixed,
        }

        assert organization_service.get_extra_schemas(config) == fixed
        org_repository.assert_not_called()

    def test_all_schemas_reads_the_organization(self, org_repository):
        """allSchemas adds every schema of the organization"""
        config = {
            "roles": [MANAGER],
            "organization": {"id": 7, "allSchemas": True},
            "schemas": [],
        }

        assert organization_service.get_extra_schemas(config) == ORG_SCHEMAS
        org_repository.assert_called_once_with(7)

    def test_all_schemas_without_the_manager_role(self, org_repository):
        """A left-behind organization key without the role reads no organization"""
        config = {
            "roles": [NAVIGATOR],
            "organization": {"id": 7, "allSchemas": True},
            "schemas": [],
        }

        assert organization_service.get_extra_schemas(config) == []
        org_repository.assert_not_called()

    def test_all_schemas_merges_without_duplicates(self, org_repository):
        """A schema in both lists appears once, the fixed entry kept first"""
        fixed = [
            {"name": "hospital_b", "friendlyName": "Nome fixo"},
            {"name": "hospital_c", "friendlyName": "Hospital C"},
        ]
        config = {
            "roles": [MANAGER],
            "organization": {"id": 7, "allSchemas": True},
            "schemas": fixed,
        }

        result = organization_service.get_extra_schemas(config)

        assert result == [
            {"name": "hospital_b", "friendlyName": "Nome fixo"},
            {"name": "hospital_c", "friendlyName": "Hospital C"},
            {"name": "hospital_a", "friendlyName": "Hospital A"},
        ]

    def test_all_schemas_drops_malformed_fixed_entries(self, org_repository):
        """A fixed entry that is not a dict is dropped and does not hide a schema"""
        config = {
            "roles": [MANAGER],
            "organization": {"id": 7, "allSchemas": True},
            "schemas": ["hospital_a"],
        }

        result = organization_service.get_extra_schemas(config)

        assert result == ORG_SCHEMAS

    def test_fixed_list_drops_malformed_entries(self, org_repository):
        """Without an organization, the entries that are not dicts are dropped
        too: the callers (login, switch, support tickets) read each as a dict"""
        fixed = [{"name": "hospital_c", "friendlyName": "Hospital C"}]
        config = {"roles": [NAVIGATOR], "schemas": ["hospital_a", None, 7] + fixed}

        assert organization_service.get_extra_schemas(config) == fixed

    def test_all_schemas_with_an_empty_organization(self, org_repository):
        """An organization without schemas leaves the fixed list as it is"""
        org_repository.return_value = []
        fixed = [{"name": "hospital_c", "friendlyName": "Hospital C"}]
        config = {
            "roles": [MANAGER],
            "organization": {"id": 7, "allSchemas": True},
            "schemas": fixed,
        }

        assert organization_service.get_extra_schemas(config) == fixed
