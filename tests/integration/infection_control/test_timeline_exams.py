"""Tests: the exams the antimicrobial timeline opens with

Each schema chooses the exams the infection control page plots under the
courses, in order (GET/PUT /infection-control/timeline-exams, in its memoria,
written only by WRITE_INFECTION_CONTROL), by reference
(segmentoexame.tpexame_ref). Without a choice the timeline opens with the
default ones (CRP, CKD-EPI or CKD-EPI 2021, leukocytes, temperature). The admission view
sends the list with the timeline. Saving a change keeps the version it
replaced, with who saved each.
"""

import pytest
from sqlalchemy import text

from models.enums import MemoryEnum
from tests.conftest import session, session_commit
from tests.integration.infection_control.helpers import (
    ADULT_SEGMENT,
    _prescribe_today,
)
from utils import status

URL = "/infection-control/timeline-exams"
KIND = MemoryEnum.INFECTION_CONTROL_TIMELINE_EXAMS.value
PREVIOUS_KIND = MemoryEnum.INFECTION_CONTROL_TIMELINE_EXAMS_PREVIOUS.value
DEFAULT = ["pcru", "ckd", "ckd21", "h_conleuc", "temp"]

# the schema's exams mapped to references: PCR and potassium; the global
# catalog names PCR, the potassium keeps the schema's name
SCHEMA_EXAMS = (
    ("PCR_TL_TEST", "PCRU", "Proteína C reativa do hospital"),
    ("K_TL_TEST", "zz_k_tl", "ZZ Potássio do hospital"),
    ("INATIVO_TL_TEST", "zz_inactive_tl", "ZZ Inativo"),
)
GLOBAL_EXAMS = (("pcru", "PCR"), ("h_conleuc", "Leucócitos Absoluto"))


def _delete_settings():
    """Delete the list and the version it replaced"""
    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo IN (:kind, :previous)"),
        {"kind": KIND, "previous": PREVIOUS_KIND},
    )
    session_commit()


@pytest.fixture(autouse=True)
def no_settings():
    """No timeline exams chosen before and after each test"""
    _delete_settings()
    yield
    _delete_settings()


def _delete_exams():
    """Remove the exams the tests map"""
    session.execute(
        text("DELETE FROM demo.segmentoexame WHERE tpexame = ANY(:types)"),
        {"types": [row[0] for row in SCHEMA_EXAMS]},
    )
    session.execute(
        text("DELETE FROM public.exame WHERE tpexame = ANY(:types)"),
        {"types": [row[0] for row in GLOBAL_EXAMS]},
    )
    session_commit()


@pytest.fixture
def mapped_exams():
    """The schema's exams mapped to references (one inactive) and the global
    names of two references"""
    _delete_exams()
    for exam_type, exam_ref, name in SCHEMA_EXAMS:
        session.execute(
            text(
                "INSERT INTO demo.segmentoexame "
                "(idsegmento, tpexame, tpexame_ref, abrev, nome, ativo, update_by) "
                "VALUES (:segment, :exam_type, :exam_ref, :exam_type, :name, "
                ":active, 0)"
            ),
            {
                "segment": ADULT_SEGMENT,
                "exam_type": exam_type,
                "exam_ref": exam_ref,
                "name": name,
                "active": exam_type != "INATIVO_TL_TEST",
            },
        )
    for exam_type, name in GLOBAL_EXAMS:
        session.execute(
            text(
                "INSERT INTO public.exame (tpexame, nome, abrev, unidade, ativo, "
                "created_at, created_by) "
                "VALUES (:exam_type, :name, :name, '-', true, now(), 0)"
            ),
            {"exam_type": exam_type, "name": name},
        )
    session_commit()
    yield
    _delete_exams()


def _get(client, headers):
    """GET the timeline exams, expecting success"""
    response = client.get(URL, headers=headers)
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return response.get_json()["data"]


def _save(client, headers, exams):
    """PUT the timeline exams"""
    return client.put(URL, json={"exams": exams}, headers=headers)


def _saved(client, headers, exams):
    """PUT the timeline exams, expecting success"""
    response = _save(client, headers, exams)
    assert response.status_code == status.HTTP_200_OK, response.get_json()
    return response.get_json()["data"]


def _refs(exams):
    """The references of a list of exams"""
    return [exam["examRef"] for exam in exams]


def test_default_without_a_choice(
    client, infection_controller_headers, infection_control, mapped_exams
):
    """A schema that never chose them shows the default exams, and what it
    can choose from: the references of its active exams, by name"""
    data = _get(client, infection_controller_headers)

    assert data["default"] is True
    assert _refs(data["exams"]) == DEFAULT
    assert data["exams"][0] == {"examRef": "pcru", "name": "PCR", "available": True}
    # a default exam the schema maps nothing to stays, unavailable
    assert data["exams"][3] == {
        "examRef": "h_conleuc",
        "name": "Leucócitos Absoluto",
        "available": False,
    }
    assert data["exams"][1] == {"examRef": "ckd", "name": "ckd", "available": False}
    assert _refs(data["defaultExams"]) == DEFAULT
    assert data["options"] == [
        {"examRef": "pcru", "name": "PCR"},
        {"examRef": "zz_k_tl", "name": "ZZ Potássio do hospital"},
    ]
    assert data["updatedAt"] is None
    assert data["updatedBy"] is None
    assert data["previous"] is None


def test_saves_the_exams_in_order_and_keeps_the_previous_version(
    client, infection_controller_headers, infection_control, mapped_exams
):
    """The exams are kept in the order given (lower case, once each); a
    change keeps the version it replaced, with when and by whom"""
    first = _saved(client, infection_controller_headers, ["ZZ_K_TL", "pcru", "zz_k_tl"])
    assert first["default"] is False
    assert _refs(first["exams"]) == ["zz_k_tl", "pcru"]
    assert first["updatedBy"] is not None
    assert first["previous"] is None

    second = _saved(client, infection_controller_headers, ["pcru"])

    assert _refs(second["exams"]) == ["pcru"]
    assert _refs(second["previous"]["exams"]) == ["zz_k_tl", "pcru"]
    assert second["previous"]["updatedAt"] == first["updatedAt"]
    assert second["previous"]["updatedBy"] == first["updatedBy"]


def test_saving_no_change_writes_nothing(
    client, infection_controller_headers, infection_control, mapped_exams
):
    """The default saved as it is creates no record"""
    data = _saved(client, infection_controller_headers, DEFAULT)

    assert data["default"] is True
    assert (
        session.execute(
            text("SELECT count(*) FROM demo.memoria WHERE tipo = :kind"),
            {"kind": KIND},
        ).scalar()
        == 0
    )


def test_an_empty_list_opens_the_timeline_without_exams(
    client, infection_controller_headers, infection_control, mapped_exams
):
    """Choosing no exam is a choice, not the default"""
    data = _saved(client, infection_controller_headers, [])

    assert data["default"] is False
    assert data["exams"] == []


def test_rejects_an_exam_the_schema_does_not_offer(
    client, infection_controller_headers, infection_control, mapped_exams
):
    """Only the schema's references (active exams) or the default ones"""
    for exams in (["zz_unknown_tl"], ["zz_inactive_tl"]):
        response = _save(client, infection_controller_headers, exams)
        assert response.status_code == status.HTTP_400_BAD_REQUEST

    # a default one the schema maps nothing to may be chosen
    data = _saved(client, infection_controller_headers, ["h_conleuc"])
    assert _refs(data["exams"]) == ["h_conleuc"]


def test_rejects_more_than_ten(
    client, infection_controller_headers, infection_control, mapped_exams
):
    """The timeline opens with ten exams at most"""
    response = _save(
        client, infection_controller_headers, [f"ref{i}" for i in range(11)]
    )
    assert response.status_code == status.HTTP_400_BAD_REQUEST


@pytest.mark.parametrize("headers_fixture", ["analyst_headers", "viewer_headers"])
def test_only_infection_control_writes_it(
    client, request, headers_fixture, infection_control, mapped_exams
):
    """Viewing roles read the list but can't change it; others can't read it"""
    headers = request.getfixturevalue(headers_fixture)

    response = _save(client, headers, ["pcru"])
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    expected = (
        status.HTTP_200_OK
        if headers_fixture == "analyst_headers"
        else status.HTTP_401_UNAUTHORIZED
    )
    assert client.get(URL, headers=headers).status_code == expected


def test_the_generic_memory_endpoints_cant_write_it(
    client, infection_controller_headers, infection_control
):
    """Written only by its own endpoint"""
    for kind in (KIND, PREVIOUS_KIND):
        response = client.put(
            f"/memory/unique/{kind}",
            json={"value": {"exams": ["pcru"]}},
            headers=infection_controller_headers,
        )
        assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_the_admission_view_sends_the_exams(
    client, infection_controller_headers, infection_control, mapped_exams, admission
):
    """The timeline comes with the exams it opens with: none while the schema
    never chose (the page plots its default), or the schema's choice"""
    _prescribe_today(admission)
    url = f"/infection-control/antimicrobial-timeline/{admission}"

    data = client.get(url, headers=infection_controller_headers).get_json()["data"]
    assert data["timelineExams"] is None

    _saved(client, infection_controller_headers, ["zz_k_tl", "pcru"])
    data = client.get(url, headers=infection_controller_headers).get_json()["data"]
    assert data["timelineExams"] == ["zz_k_tl", "pcru"]
