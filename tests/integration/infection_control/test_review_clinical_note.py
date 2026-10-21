"""Tests: infection control follow-up, the clinical note a review writes: on the
prescription-day the record points at (ci_atendimento.fkprescricao_ultima),
always a prescription clinical note
(prescricao_evolucao) whatever MULTI_CLINICAL_NOTES says, with an active type,
and saved with the review or not at all"""

from sqlalchemy import text

from models.enums import PrescriptionClinicalNoteStatusEnum
from tests.conftest import session
from tests.integration.infection_control.helpers import (
    ANTIMICROBIAL_DRUG,
    _day,
    _last_prescription_day,
    _prescalc,
    _prescribe,
    _prescribe_today,
    _review,
    _set,
)
from utils import status

NOTE_TEXT = "Paciente Fulano Beltrano em uso de antimicrobiano conforme."


def _clinical_notes(admission_number):
    return session.execute(
        text(
            "SELECT fkprescricao, idtipoevolucao, texto, tp_status, created_by, "
            "fkci_revisao "
            "FROM demo.prescricao_evolucao WHERE nratendimento = :a"
        ),
        {"a": admission_number},
    ).all()


def _reviews(admission_number):
    return session.execute(
        text("SELECT idci_revisao FROM demo.ci_revisao WHERE nratendimento = :a"),
        {"a": admission_number},
    ).all()


def test_review_writes_clinical_note(
    client,
    infection_controller_headers,
    without_multi_clinical_notes,
    clinical_note_types,
    admission,
):
    """The note is a pending prescricao_evolucao row of the record's
    prescription-day, even without MULTI_CLINICAL_NOTES"""
    _prescribe_today(admission)
    record_day = _last_prescription_day(admission)
    # a later prescription-day the job has not reached: the note stays on the
    # record's, with the review
    _prescalc(_prescribe(admission, _day(1), _day(2)))
    assert _last_prescription_day(admission) != record_day

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        clinical_note={
            "idClinicalNoteType": clinical_note_types["active"],
            "text": NOTE_TEXT,
        },
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    notes = _clinical_notes(admission)
    assert len(notes) == 1
    assert notes[0].fkprescricao == record_day
    assert notes[0].idtipoevolucao == clinical_note_types["active"]
    assert notes[0].texto == NOTE_TEXT
    assert notes[0].tp_status == PrescriptionClinicalNoteStatusEnum.PENDING.value
    assert notes[0].created_by is not None
    # it points at the review that wrote it
    assert [notes[0].fkci_revisao] == [r.idci_revisao for r in _reviews(admission)]


def test_review_clinical_note_requires_record_prescription(
    client,
    infection_controller_headers,
    infection_control,
    clinical_note_types,
    admission,
):
    """Without a prescription-day on the record the note has nowhere to go,
    and the whole review is rejected"""
    _prescribe_today(admission)
    _set("ci_atendimento", admission, fkprescricao_ultima=None)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        clinical_note={
            "idClinicalNoteType": clinical_note_types["active"],
            "text": NOTE_TEXT,
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.businessRules"
    assert _clinical_notes(admission) == []
    assert _reviews(admission) == []


def test_follow_up_serves_record_prescription(
    client, infection_controller_headers, infection_control, admission
):
    """The follow-up tells the page where a note would be written"""
    _prescribe_today(admission)

    response = client.get(
        f"/infection-control/admission/{admission}",
        headers=infection_controller_headers,
    )

    assert response.status_code == status.HTTP_200_OK
    assert response.get_json()["data"]["idPrescription"] == str(
        _last_prescription_day(admission)
    )


def test_review_without_clinical_note(
    client, infection_controller_headers, infection_control, admission
):
    """The note is optional"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
    )

    assert response.status_code == status.HTTP_200_OK, response.get_json()
    assert _clinical_notes(admission) == []


def test_review_clinical_note_requires_active_type(
    client,
    infection_controller_headers,
    infection_control,
    clinical_note_types,
    admission,
):
    """An inactive or unknown type rejects the whole review"""
    _prescribe_today(admission)

    for id_type in (clinical_note_types["inactive"], "CI-INEXISTENTE"):
        response = _review(
            client,
            infection_controller_headers,
            admission,
            evaluations=[ANTIMICROBIAL_DRUG],
            clinical_note={"idClinicalNoteType": id_type, "text": NOTE_TEXT},
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.get_json()["code"] == "errors.invalidParams"

    assert _clinical_notes(admission) == []
    assert _reviews(admission) == []


def test_review_clinical_note_requires_text(
    client,
    infection_controller_headers,
    infection_control,
    clinical_note_types,
    admission,
):
    """A blank note rejects the whole review"""
    _prescribe_today(admission)

    response = _review(
        client,
        infection_controller_headers,
        admission,
        evaluations=[ANTIMICROBIAL_DRUG],
        clinical_note={
            "idClinicalNoteType": clinical_note_types["active"],
            "text": "  \n ",
        },
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert _clinical_notes(admission) == []
    assert _reviews(admission) == []


def test_list_clinical_note_types(
    client, infection_controller_headers, infection_control, clinical_note_types
):
    """Only the active types"""
    response = client.get(
        "/infection-control/clinical-note-types", headers=infection_controller_headers
    )

    assert response.status_code == status.HTTP_200_OK
    ids = [t["id"] for t in response.get_json()["data"]]
    assert clinical_note_types["active"] in ids
    assert clinical_note_types["inactive"] not in ids


def test_list_clinical_note_types_requires_permission(
    client, viewer_headers, infection_control
):
    """401 without READ_INFECTION_CONTROL"""
    response = client.get(
        "/infection-control/clinical-note-types", headers=viewer_headers
    )

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_list_clinical_note_types_requires_feature(
    client, infection_controller_headers
):
    """400 when the schema does not have the feature"""
    response = client.get(
        "/infection-control/clinical-note-types", headers=infection_controller_headers
    )

    assert response.status_code == status.HTTP_400_BAD_REQUEST
