"""Integration tests for the /help-text endpoints (help_text_service).

The help texts live in the shared ``public.texto_ajuda`` table (not a tenant
schema), so each test uses a distinctive key and the ``clean_help_text``
fixture removes it afterwards.
"""

import pytest
from sqlalchemy import text

from tests.conftest import get_access, make_headers, session, session_commit

from security.role import Role

HELP_KEY = "zztest_help_key"


@pytest.fixture
def clean_help_text():
    """Remove the test help-text row before and after the test."""

    def _delete():
        session.execute(
            text("DELETE FROM public.texto_ajuda WHERE chave = :key"),
            {"key": HELP_KEY},
        )
        session_commit()

    _delete()
    yield
    _delete()


def test_get_help_text_missing_key(client, analyst_headers, clean_help_text):
    """Reading an unknown key returns the key with a null content [200 OK]."""
    response = client.get(f"/help-text/{HELP_KEY}", headers=analyst_headers)

    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["key"] == HELP_KEY
    assert data["content"] is None


def test_update_help_text_creates_record(client, curator_headers, clean_help_text):
    """A PUT with WRITE_HELP_TEXT creates the record and it is then readable."""
    response = client.put(
        f"/help-text/{HELP_KEY}",
        headers=curator_headers,
        json={"content": "first version"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["content"] == "first version"

    # the newly created content is returned by a subsequent GET
    read = client.get(f"/help-text/{HELP_KEY}", headers=curator_headers)
    assert read.status_code == 200
    assert read.get_json()["data"]["content"] == "first version"


def test_update_help_text_overwrites_existing(
    client, curator_headers, clean_help_text
):
    """A second PUT on the same key replaces the previous content (upsert)."""
    client.put(
        f"/help-text/{HELP_KEY}",
        headers=curator_headers,
        json={"content": "first version"},
    )

    response = client.put(
        f"/help-text/{HELP_KEY}",
        headers=curator_headers,
        json={"content": "second version"},
    )

    assert response.status_code == 200
    assert response.get_json()["data"]["content"] == "second version"

    read = client.get(f"/help-text/{HELP_KEY}", headers=curator_headers)
    assert read.get_json()["data"]["content"] == "second version"


def test_update_help_text_clears_content(client, curator_headers, clean_help_text):
    """Omitting content clears it to null while keeping the record."""
    client.put(
        f"/help-text/{HELP_KEY}",
        headers=curator_headers,
        json={"content": "to be cleared"},
    )

    response = client.put(f"/help-text/{HELP_KEY}", headers=curator_headers, json={})

    assert response.status_code == 200
    assert response.get_json()["data"]["content"] is None


def test_get_help_text_permission_denied(client, clean_help_text):
    """Without READ_BASIC_FEATURES the read is rejected [401 UNAUTHORIZED]."""
    headers = make_headers(get_access(client, roles=[Role.DISPENSING_MANAGER.value]))
    response = client.get(f"/help-text/{HELP_KEY}", headers=headers)

    assert response.status_code == 401


def test_update_help_text_permission_denied(
    client, analyst_headers, clean_help_text
):
    """Without WRITE_HELP_TEXT the update is rejected and nothing is stored."""
    response = client.put(
        f"/help-text/{HELP_KEY}",
        headers=analyst_headers,
        json={"content": "should not persist"},
    )

    assert response.status_code == 401

    # confirm the rejected write left no record behind
    row = session.execute(
        text("SELECT conteudo FROM public.texto_ajuda WHERE chave = :key"),
        {"key": HELP_KEY},
    ).first()
    assert row is None
