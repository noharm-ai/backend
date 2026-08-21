"""Tests: GET /reports/general/<report> and GET /reports/config

The internal-report feature is a thin layer over the S3 cache, and everything
worth pinning down happens *before* the bucket is touched:

* only names in ``ReportEnum`` are reports at all;
* a report listed in the caller's own ``usuario.relatorios["ignore"]`` is
  refused even though the role grants READ_REPORTS -- that per-user opt-out is
  the only place a report is taken away from someone who could otherwise see
  it;
* the resource path is built from the caller's schema, so one client can never
  name another client's file, and a crafted ``filename`` must not escape the
  prefix;
* ``/reports/config`` applies the same ignore list to the report *menu*, and
  ignoring ``CUSTOM`` blanks the external list wholesale.

S3 is stubbed throughout: the tests assert on the resource path the service
asks for, which is the part the backend actually decides.
"""

import json

import pytest
from sqlalchemy import text

from models.enums import MemoryEnum, ReportEnum
from services.reports import reports_cache_service
from tests.conftest import session, session_commit
from utils import status

CONFIG_URL = "/reports/config"

# the user behind every fixture in tests.conftest.get_access
CALLER_ID = 1
CALLER_SCHEMA = "demo"

# a real report name, used whenever the test is not about the name itself
A_REPORT = ReportEnum.RPT_PRESCRIPTION.value

# menu entries seeded into demo.memoria; both kinds are absent from the seed
# dump, so the rows are dropped again rather than restored
INTERNAL_MENU = [ReportEnum.RPT_PRESCRIPTION.value, ReportEnum.RPT_ECONOMY.value]
EXTERNAL_MENU = [
    {"title": "Painel externo", "url": "https://example.invalid/a"},
    {"title": "Painel externo 2", "url": "https://example.invalid/b"},
]


def _report_url(report: str, filename: str = None):
    """URL for the single-report endpoint, optionally naming a history file."""
    url = f"/reports/general/{report}"

    return f"{url}?filename={filename}" if filename is not None else url


def _set_ignored_reports(ignored: list):
    """Write the caller's per-user report opt-out list."""
    session.execute(
        text(
            "UPDATE public.usuario SET relatorios = CAST(:value AS json) WHERE idusuario = :id"
        ),
        {"value": json.dumps({"ignore": ignored}), "id": CALLER_ID},
    )
    session_commit()


def _seed_menu(kind: str, value):
    """Insert one demo.memoria row holding a report menu."""
    session.execute(
        text(
            "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST(:value AS json), now(), :user)"
        ),
        {"kind": kind, "value": json.dumps(value), "user": CALLER_ID},
    )
    session_commit()


def _cleanup():
    """Undo the caller's opt-out list and drop the seeded menus."""
    session.execute(
        text("UPDATE public.usuario SET relatorios = NULL WHERE idusuario = :id"),
        {"id": CALLER_ID},
    )
    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo IN (:external, :internal)"),
        {
            "external": MemoryEnum.REPORTS.value,
            "internal": MemoryEnum.REPORTS_INTERNAL.value,
        },
    )
    session_commit()


@pytest.fixture(autouse=True)
def clean_report_config():
    """The seed dump has neither an opt-out list nor a report menu: keep it so."""
    _cleanup()
    yield
    _cleanup()


@pytest.fixture(autouse=True)
def cache(monkeypatch):
    """Replace S3 with a recorder.

    ``paths`` collects every resource path the service asked about, and
    ``link`` is what ``generate_link`` hands back -- ``None`` standing for "the
    report was never generated for this client".
    """
    recorder = {"paths": [], "link": None, "history": []}

    def _generate_link(resource_path: str):
        recorder["paths"].append(resource_path)
        return recorder["link"]

    monkeypatch.setattr(reports_cache_service, "generate_link", _generate_link)
    monkeypatch.setattr(
        reports_cache_service,
        "list_available_reports",
        lambda schema, report: recorder["history"],  # noqa: ARG005
    )
    # the custom-report list rides along in /reports/config
    monkeypatch.setattr(
        reports_cache_service,
        "list_available_custom_reports",
        lambda schema, id_report: [],  # noqa: ARG005
    )

    return recorder


def _data(response):
    """The payload of a successful api_endpoint response."""
    return json.loads(response.data)["data"]


# --- which names are reports ---------------------------------------------------


def test_unknown_report_name_is_rejected(client, analyst_headers, cache):
    """A name outside ReportEnum is not a report, and S3 is never asked [400]."""
    response = client.get(_report_url("NOT_A_REPORT"), headers=analyst_headers)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"
    assert cache["paths"] == []


@pytest.mark.parametrize("report", [r.value for r in ReportEnum])
def test_every_enum_member_is_accepted(client, analyst_headers, report):
    """Every shipped report name reaches the cache lookup [200 OK]."""
    response = client.get(_report_url(report), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK


# --- the per-user opt-out list -------------------------------------------------


def test_ignored_report_is_refused(client, analyst_headers, cache):
    """The role grants READ_REPORTS, but this user opted out of this report [401]."""
    _set_ignored_reports([A_REPORT])

    response = client.get(_report_url(A_REPORT), headers=analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.get_json()["code"] == "errors.invalidPermission"
    assert cache["paths"] == []


def test_ignoring_one_report_leaves_the_others_alone(client, analyst_headers):
    """The opt-out is per report, not a blanket revocation [200 OK]."""
    _set_ignored_reports([ReportEnum.RPT_ECONOMY.value])

    response = client.get(_report_url(A_REPORT), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK


def test_an_empty_opt_out_list_ignores_nothing(client, analyst_headers):
    """``{"ignore": []}`` is the shipped default and must not lock anyone out [200]."""
    _set_ignored_reports([])

    response = client.get(_report_url(A_REPORT), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK


# --- cache hit and miss --------------------------------------------------------


def test_a_report_never_generated_is_reported_as_uncached(
    client, analyst_headers, cache
):
    """No file in the bucket yet: say so, and do not list a history [200 OK]."""
    cache["link"] = None

    response = client.get(_report_url(A_REPORT), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _data(response) == {"cached": False}


def test_a_generated_report_returns_its_link_and_history(
    client, analyst_headers, cache
):
    """With a file present the caller gets the presigned link plus older runs."""
    cache["link"] = "https://cache.invalid/signed"
    cache["history"] = [{"name": "20240102", "updateAt": "2024-01-02T00:00:00"}]

    response = client.get(_report_url(A_REPORT), headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK
    assert _data(response) == {
        "cached": True,
        "url": "https://cache.invalid/signed",
        "availableReports": cache["history"],
    }


# --- the resource path is the tenant boundary ---------------------------------


def test_the_resource_path_is_scoped_to_the_callers_schema(
    client, analyst_headers, cache
):
    """The path is derived from the JWT schema, never from the request [200 OK]."""
    client.get(_report_url(A_REPORT), headers=analyst_headers)

    assert cache["paths"] == [f"reports/{CALLER_SCHEMA}/{A_REPORT}/current.gz"]


def test_a_named_history_file_is_fetched_instead_of_current(
    client, analyst_headers, cache
):
    """``filename`` selects an older run inside the same prefix [200 OK]."""
    client.get(_report_url(A_REPORT, filename="20240102"), headers=analyst_headers)

    assert cache["paths"] == [f"reports/{CALLER_SCHEMA}/{A_REPORT}/20240102.gz"]


@pytest.mark.parametrize(
    "filename",
    [
        "../../../etc/passwd",
        "..%2f..%2fother",
        "sub\\current",
        "with space",
    ],
)
def test_a_filename_that_leaves_the_prefix_is_rejected(
    client, analyst_headers, cache, filename
):
    """Traversal, encoded traversal and stray characters never reach S3 [400]."""
    response = client.get(
        _report_url(A_REPORT, filename=filename), headers=analyst_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidFilename"
    assert cache["paths"] == []


# --- the report menu ----------------------------------------------------------


def test_config_returns_both_menus_and_the_custom_list(client, analyst_headers):
    """With nothing ignored the caller sees every configured entry [200 OK]."""
    _seed_menu(MemoryEnum.REPORTS.value, EXTERNAL_MENU)
    _seed_menu(MemoryEnum.REPORTS_INTERNAL.value, INTERNAL_MENU)

    response = client.get(CONFIG_URL, headers=analyst_headers)

    assert response.status_code == status.HTTP_200_OK

    data = _data(response)
    assert data["internal"] == INTERNAL_MENU
    assert data["external"] == EXTERNAL_MENU
    assert data["custom"] == []


def test_config_hides_the_reports_the_user_opted_out_of(client, analyst_headers):
    """Internal entries match by name, external ones by title [200 OK]."""
    _seed_menu(MemoryEnum.REPORTS.value, EXTERNAL_MENU)
    _seed_menu(MemoryEnum.REPORTS_INTERNAL.value, INTERNAL_MENU)
    _set_ignored_reports([ReportEnum.RPT_ECONOMY.value, "Painel externo"])

    data = _data(client.get(CONFIG_URL, headers=analyst_headers))

    assert data["internal"] == [ReportEnum.RPT_PRESCRIPTION.value]
    assert [r["title"] for r in data["external"]] == ["Painel externo 2"]


def test_ignoring_custom_drops_every_external_report(client, analyst_headers):
    """CUSTOM in the opt-out list blanks the whole external menu [200 OK]."""
    _seed_menu(MemoryEnum.REPORTS.value, EXTERNAL_MENU)
    _seed_menu(MemoryEnum.REPORTS_INTERNAL.value, INTERNAL_MENU)
    _set_ignored_reports(["CUSTOM"])

    data = _data(client.get(CONFIG_URL, headers=analyst_headers))

    assert data["external"] == []
    # only the external menu is affected
    assert data["internal"] == INTERNAL_MENU


def test_config_is_empty_when_no_menu_is_configured(client, analyst_headers):
    """A schema with no memoria rows gets empty lists, not an error [200 OK]."""
    data = _data(client.get(CONFIG_URL, headers=analyst_headers))

    assert data == {"external": [], "internal": [], "custom": []}


# --- permission ---------------------------------------------------------------


def test_a_role_without_read_reports_cannot_fetch_a_report(
    client, user_manager_headers, cache
):
    """USER_MANAGER holds no READ_REPORTS, so the report is out of reach [401]."""
    response = client.get(_report_url(A_REPORT), headers=user_manager_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert cache["paths"] == []


def test_a_role_without_read_reports_cannot_read_the_menu(client, user_manager_headers):
    """The menu is gated by the same permission as the reports it lists [401]."""
    response = client.get(CONFIG_URL, headers=user_manager_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED
