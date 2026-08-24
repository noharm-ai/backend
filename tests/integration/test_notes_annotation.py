"""Integration tests for the clinical-note annotation removal feature.

``POST /notes/remove-annotation`` lets a pharmacist drop a wrong allergy or
dialysis annotation that the text-mining step wrote on a clinical note. The
removal is not limited to the note that was clicked: every note of the same
admission carrying the *same* annotation text is cleared, so the annotation
stops showing up on the patient timeline. These tests cover that fan-out, the
boundaries it must respect (other texts, other admissions), the validation
rules and the audit record.
"""

import pytest
from sqlalchemy import text

from models.enums import UserAuditTypeEnum
from models.notes import ClinicalNotes
from services import clinical_notes_service
from tests.conftest import session, session_commit

URL = "/notes/remove-annotation"

# test-generated ids use >= 100000
NOTE_ALLERGY = 100920
NOTE_ALLERGY_SAME_TEXT = 100921
NOTE_ALLERGY_OTHER_TEXT = 100922
NOTE_DIALYSIS = 100923
NOTE_OTHER_ADMISSION = 100924

NOTE_IDS = [
    NOTE_ALLERGY,
    NOTE_ALLERGY_SAME_TEXT,
    NOTE_ALLERGY_OTHER_TEXT,
    NOTE_DIALYSIS,
    NOTE_OTHER_ADMISSION,
]

ADMISSION_NUMBER = 5
OTHER_ADMISSION_NUMBER = 6

ALLERGY_TEXT = "ZZTEST alergia a dipirona"
OTHER_ALLERGY_TEXT = "ZZTEST alergia a penicilina"
DIALYSIS_TEXT = "ZZTEST hemodialise 3x na semana"

INVALID_NOTE_ID = 999999


def _insert_note(id, admission_number, allergy_text=None, dialysis_text=None):
    """Insert a clinical note carrying the given annotation texts"""
    session.execute(
        text(
            "INSERT INTO demo.evolucao "
            "(fkevolucao, nratendimento, texto, dtevolucao, cargo, exame, "
            "alergia, alergiatexto, dialise, dialisetexto) "
            "VALUES (:id, :admission, 'Evolução de teste', now(), "
            "'Farmacêutica', false, :allergy, :allergy_text, "
            ":dialysis, :dialysis_text)"
        ),
        {
            "id": id,
            "admission": admission_number,
            "allergy": 1 if allergy_text else 0,
            "allergy_text": allergy_text,
            "dialysis": 1 if dialysis_text else 0,
            "dialysis_text": dialysis_text,
        },
    )


class _StubRedis:
    """Records the cache commands the annotation removal issues.

    The real client cannot be reached from the test environment, so it is
    replaced: removing an annotation also refreshes the allergy/dialysis cache
    of the admission, and that refresh is part of what these tests assert.
    """

    def __init__(self):
        self.deleted_keys = []

    def delete(self, key):
        self.deleted_keys.append(key)

    def zadd(self, key, mapping):
        pass

    def expire(self, key, ttl):
        pass


@pytest.fixture(autouse=True)
def stub_redis(monkeypatch):
    """Replace the cache client used while refreshing the annotation caches"""
    stub = _StubRedis()
    monkeypatch.setattr(clinical_notes_service, "redis_client", stub)

    return stub


@pytest.fixture
def annotation_notes():
    """Notes covering the removal fan-out and the boundaries it must respect"""
    _insert_note(NOTE_ALLERGY, ADMISSION_NUMBER, allergy_text=ALLERGY_TEXT)
    _insert_note(NOTE_ALLERGY_SAME_TEXT, ADMISSION_NUMBER, allergy_text=ALLERGY_TEXT)
    _insert_note(
        NOTE_ALLERGY_OTHER_TEXT, ADMISSION_NUMBER, allergy_text=OTHER_ALLERGY_TEXT
    )
    _insert_note(NOTE_DIALYSIS, ADMISSION_NUMBER, dialysis_text=DIALYSIS_TEXT)
    _insert_note(
        NOTE_OTHER_ADMISSION, OTHER_ADMISSION_NUMBER, allergy_text=ALLERGY_TEXT
    )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM demo.evolucao WHERE fkevolucao = ANY(:ids)"),
        {"ids": NOTE_IDS},
    )
    session.execute(
        text(
            "DELETE FROM public.usuario_audit "
            "WHERE tp_audit = :audit_type "
            "AND CAST(extra->>'fkevolucao' AS bigint) = ANY(:ids)"
        ),
        {
            "audit_type": UserAuditTypeEnum.REMOVE_CLINICAL_NOTE_ANNOTATION.value,
            "ids": NOTE_IDS,
        },
    )
    session_commit()


def _get_note(id):
    """Read a note back from the database, bypassing the identity map"""
    session.expire_all()
    return session.get(ClinicalNotes, id)


def test_remove_annotation_no_token(client, annotation_notes):
    """POST /notes/remove-annotation — returns 401 without authentication"""
    response = client.post(
        URL,
        json={"idClinicalNotes": NOTE_ALLERGY, "annotationType": "allergy"},
        headers={"Content-Type": "application/json"},
    )

    assert response.status_code == 401


def test_remove_annotation_permission_denied(client, viewer_headers, annotation_notes):
    """POST /notes/remove-annotation — a read-only role cannot remove an annotation"""
    response = client.post(
        URL,
        json={"idClinicalNotes": NOTE_ALLERGY, "annotationType": "allergy"},
        headers=viewer_headers,
    )

    assert response.status_code == 401

    # the annotation is still there
    assert _get_note(NOTE_ALLERGY).allergy == 1


def test_remove_annotation_invalid_note(client, analyst_headers, annotation_notes):
    """POST /notes/remove-annotation — returns 400 when the note does not exist"""
    response = client.post(
        URL,
        json={"idClinicalNotes": INVALID_NOTE_ID, "annotationType": "allergy"},
        headers=analyst_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"


def test_remove_annotation_missing_note_id(client, analyst_headers, annotation_notes):
    """POST /notes/remove-annotation — returns 400 when idClinicalNotes is missing"""
    response = client.post(
        URL, json={"annotationType": "allergy"}, headers=analyst_headers
    )

    assert response.status_code == 400


def test_remove_annotation_invalid_type(client, analyst_headers, annotation_notes):
    """POST /notes/remove-annotation — returns 400 for an unsupported annotation type"""
    response = client.post(
        URL,
        json={"idClinicalNotes": NOTE_ALLERGY, "annotationType": "signs"},
        headers=analyst_headers,
    )

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.businessRules"

    # nothing was cleared
    assert _get_note(NOTE_ALLERGY).allergy == 1
    assert _get_note(NOTE_ALLERGY).allergyText == ALLERGY_TEXT


def test_remove_allergy_clears_every_note_with_the_same_text(
    client, analyst_headers, annotation_notes
):
    """POST /notes/remove-annotation — removing an allergy clears every note of the admission sharing that text"""
    response = client.post(
        URL,
        json={"idClinicalNotes": NOTE_ALLERGY, "annotationType": "allergy"},
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert response.get_json()["data"] is True

    for id in (NOTE_ALLERGY, NOTE_ALLERGY_SAME_TEXT):
        note = _get_note(id)
        assert note.allergy == 0
        assert note.allergyText is None


def test_remove_allergy_keeps_other_texts_and_admissions(
    client, analyst_headers, annotation_notes
):
    """POST /notes/remove-annotation — removing an allergy spares other texts and other admissions"""
    response = client.post(
        URL,
        json={"idClinicalNotes": NOTE_ALLERGY, "annotationType": "allergy"},
        headers=analyst_headers,
    )

    assert response.status_code == 200

    # a different allergy on the same admission is untouched
    other_text = _get_note(NOTE_ALLERGY_OTHER_TEXT)
    assert other_text.allergy == 1
    assert other_text.allergyText == OTHER_ALLERGY_TEXT

    # the same allergy text on another admission is untouched
    other_admission = _get_note(NOTE_OTHER_ADMISSION)
    assert other_admission.allergy == 1
    assert other_admission.allergyText == ALLERGY_TEXT


def test_remove_allergy_keeps_dialysis_annotation(
    client, analyst_headers, annotation_notes
):
    """POST /notes/remove-annotation — removing an allergy does not touch dialysis annotations"""
    response = client.post(
        URL,
        json={"idClinicalNotes": NOTE_ALLERGY, "annotationType": "allergy"},
        headers=analyst_headers,
    )

    assert response.status_code == 200

    dialysis_note = _get_note(NOTE_DIALYSIS)
    assert dialysis_note.dialysis == 1
    assert dialysis_note.dialysisText == DIALYSIS_TEXT


def test_remove_dialysis_annotation(
    client, analyst_headers, annotation_notes, stub_redis
):
    """POST /notes/remove-annotation — removing a dialysis annotation clears its flag and text"""
    response = client.post(
        URL,
        json={"idClinicalNotes": NOTE_DIALYSIS, "annotationType": "dialysis"},
        headers=analyst_headers,
    )

    assert response.status_code == 200

    note = _get_note(NOTE_DIALYSIS)
    assert note.dialysis == 0
    assert note.dialysisText is None

    # allergies of the same admission are untouched
    allergy_note = _get_note(NOTE_ALLERGY)
    assert allergy_note.allergy == 1
    assert allergy_note.allergyText == ALLERGY_TEXT

    # the dialysis cache of the admission was rebuilt
    assert f"demo:{ADMISSION_NUMBER}:dialise" in stub_redis.deleted_keys


def test_remove_allergy_refreshes_the_allergy_cache(
    client, analyst_headers, annotation_notes, stub_redis
):
    """POST /notes/remove-annotation — rebuilds the allergy cache of the admission"""
    response = client.post(
        URL,
        json={"idClinicalNotes": NOTE_ALLERGY, "annotationType": "allergy"},
        headers=analyst_headers,
    )

    assert response.status_code == 200
    assert stub_redis.deleted_keys == [f"demo:{ADMISSION_NUMBER}:alergia"]


def test_remove_annotation_creates_audit(client, analyst_headers, annotation_notes):
    """POST /notes/remove-annotation — records the removal, keeping the old text, in the audit table"""
    response = client.post(
        URL,
        json={"idClinicalNotes": NOTE_ALLERGY, "annotationType": "allergy"},
        headers=analyst_headers,
    )

    assert response.status_code == 200

    session_commit()
    audit = session.execute(
        text(
            "SELECT extra FROM public.usuario_audit "
            "WHERE tp_audit = :audit_type "
            "AND CAST(extra->>'fkevolucao' AS bigint) = :id"
        ),
        {
            "audit_type": UserAuditTypeEnum.REMOVE_CLINICAL_NOTE_ANNOTATION.value,
            "id": NOTE_ALLERGY,
        },
    ).fetchall()

    assert len(audit) == 1

    extra = audit[0][0]
    assert extra["type"] == "allergy"
    assert extra["notes"] == ALLERGY_TEXT
