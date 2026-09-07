"""Integration tests for the discharge summary feature.

``GET /summary/<admission_number>`` assembles everything the discharge summary
screen needs for one admission: the patient header (including the derived
IMC), the recent out-of-range exams, the active allergies, the saved draft and
— the heart of the feature — the ``summaryConfig`` block, where each of the
eight summary topics gets an LLM prompt built from the annotations that the
text-mining step wrote on the admission's clinical notes.

Those annotations are not simply "everything ever written". Each topic reads
its own time window relative to the *first* or the *last* note of the
admission: the admission reason only counts what was written in the first four
days, the discharge condition only what was written in the last day, and so
on. These tests cover that windowing, the de-duplication across notes, the
``clinicalSummary`` composition, the mock mode used to preview prompts, and
the validation/authorization boundaries.
"""

import json

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit

# test-generated ids use the reserved ranges cleaned by tests/conftest.py
ADMISSION = 100501
ID_PATIENT = 100501
ADMISSION_NO_NOTES = 100502
ID_PATIENT_NO_NOTES = 100502

NOTE_FIRST = 100801
NOTE_SECOND_DAY_TWO = 100802
NOTE_EVE_OF_LAST = 100803
NOTE_LAST = 100804
NOTE_IDS = [NOTE_FIRST, NOTE_SECOND_DAY_TWO, NOTE_EVE_OF_LAST, NOTE_LAST]

# the admission spans 2024-01-10 (first note) to 2024-01-20 (last note)
DATE_FIRST = "2024-01-10 08:00:00"
DATE_DAY_TWO = "2024-01-12 08:00:00"
DATE_EVE_OF_LAST = "2024-01-19 08:00:00"
DATE_LAST = "2024-01-20 08:00:00"

DRUG_WITH_SUBSTANCE = 90501
DRUG_WITHOUT_SUBSTANCE = 90502
SUBSTANCE = 90501
SUBSTANCE_NAME = "ZZTEST SUBSTANCIA"

EXAM_OUT_OF_RANGE = "zztestcreat"
EXAM_IN_RANGE = "zztestsod"
EXAM_OUT_OF_RANGE_OLD = "zztestpot"
EXAM_TYPES = [EXAM_OUT_OF_RANGE, EXAM_IN_RANGE, EXAM_OUT_OF_RANGE_OLD]

PROMPT_CONFIG_KIND = "zztest-summary-prompt"
SUMMARY_KEYS = [
    "reason",
    "previousDrugs",
    "diagnosis",
    "dischargeCondition",
    "dischargePlan",
    "procedures",
    "exams",
    "clinicalSummary",
]


def _url(admission_number, mock=False):
    """Build the endpoint URL, optionally asking for the mock prompt preview"""
    return f"/summary/{admission_number}" + ("?mock=true" if mock else "")


def _insert_patient(id_patient, admission_number, weight=None, height=None):
    """Insert a synthetic patient/admission row"""
    session.execute(
        text(
            "INSERT INTO demo.pessoa "
            "(fkpessoa, nratendimento, dtinternacao, dtalta, dtnascimento, "
            "sexo, peso, altura, dtpeso, cor) "
            "VALUES (:id_patient, :admission, '2024-01-10 06:00:00', "
            "'2024-01-21 10:00:00', '1970-05-04', 'F', :weight, :height, "
            "'2024-01-10 06:00:00', 'ZZTEST COR')"
        ),
        {
            "id_patient": id_patient,
            "admission": admission_number,
            "weight": weight,
            "height": height,
        },
    )


def _insert_note(id, admission_number, date, summary):
    """Insert a clinical note carrying the given mined summary annotations"""
    session.execute(
        text(
            "INSERT INTO demo.evolucao "
            "(fkevolucao, nratendimento, texto, dtevolucao, cargo, exame, sumario) "
            "VALUES (:id, :admission, 'Evolução de teste', :date, "
            "'Médico', false, CAST(:summary AS jsonb))"
        ),
        {
            "id": id,
            "admission": admission_number,
            "date": date,
            "summary": json.dumps(summary),
        },
    )


@pytest.fixture
def summary_setup():
    """Patient, notes, exams, allergies and prompt configuration of the feature

    The notes are laid out so that every annotation window has a note that
    falls inside it and a note that falls outside it.
    """
    _insert_patient(ID_PATIENT, ADMISSION, weight=70, height=170)
    _insert_patient(ID_PATIENT_NO_NOTES, ADMISSION_NO_NOTES)

    # first note of the admission: opens both the "first days" windows
    _insert_note(
        NOTE_FIRST,
        ADMISSION,
        DATE_FIRST,
        {
            "motivo": ["Dor abdominal"],
            "medprevio": ["Losartana"],
            "diagnostico": ["Apendicite"],
            "procedimentos": ["Apendicectomia"],
            "exames": ["Ultrassom de abdome"],
            "resumo": ["Resumo do primeiro dia"],
            "planoalta": ["Plano do primeiro dia"],
            "condicaoalta": ["Condicao do primeiro dia"],
        },
    )
    # two days in: inside the 4-day reason window, outside the 1-day
    # previous-drugs window
    _insert_note(
        NOTE_SECOND_DAY_TWO,
        ADMISSION,
        DATE_DAY_TWO,
        {
            "motivo": ["Febre persistente"],
            "medprevio": ["Metformina"],
            "diagnostico": ["Apendicite"],
        },
    )
    # eve of the last note: inside the 1-day discharge windows
    _insert_note(
        NOTE_EVE_OF_LAST,
        ADMISSION,
        DATE_EVE_OF_LAST,
        {"resumo": ["Resumo da vespera"]},
    )
    # last note of the admission: closes the discharge windows
    _insert_note(
        NOTE_LAST,
        ADMISSION,
        DATE_LAST,
        {
            "motivo": ["Motivo registrado tardiamente"],
            "resumo": ["Resumo final"],
            "planoalta": ["Plano final"],
            "condicaoalta": ["Alta melhorada"],
            "procedimentos": ["Curativo"],
        },
    )

    session.execute(
        text(
            "INSERT INTO public.substancia (sctid, nome, update_at, update_by) "
            "VALUES (:sctid, :name, now(), 1)"
        ),
        {"sctid": SUBSTANCE, "name": SUBSTANCE_NAME},
    )
    session.execute(
        text(
            "INSERT INTO demo.medicamento (fkmedicamento, nome, sctid) "
            "VALUES (:id, 'ZZTEST MEDICAMENTO', :sctid)"
        ),
        {"id": DRUG_WITH_SUBSTANCE, "sctid": SUBSTANCE},
    )
    session.execute(
        text(
            "INSERT INTO demo.medicamento (fkmedicamento, nome, sctid) "
            "VALUES (:id, 'ZZTEST MEDICAMENTO SEM SUBSTANCIA', null)"
        ),
        {"id": DRUG_WITHOUT_SUBSTANCE},
    )

    # allergy resolved through the substance catalogue
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "(fkpessoa, fkmedicamento, nome_medicamento, ativo, created_by) "
            "VALUES (:id_patient, :drug, 'ZZTEST NOME LOCAL', true, 1)"
        ),
        {"id_patient": ID_PATIENT, "drug": DRUG_WITH_SUBSTANCE},
    )
    # allergy that falls back to the free-text drug name
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "(fkpessoa, fkmedicamento, nome_medicamento, ativo, created_by) "
            "VALUES (:id_patient, null, 'ZZTEST DIPIRONA', true, 1)"
        ),
        {"id_patient": ID_PATIENT},
    )
    # inactive allergy: must not reach the summary
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "(fkpessoa, fkmedicamento, nome_medicamento, ativo, created_by) "
            "VALUES (:id_patient, :drug, 'ZZTEST INATIVA', false, 1)"
        ),
        {"id_patient": ID_PATIENT, "drug": DRUG_WITHOUT_SUBSTANCE},
    )

    for position, (exam_type, abbrev, minimum, maximum) in enumerate(
        [
            (EXAM_OUT_OF_RANGE, "ZZTESTCREAT", 0.5, 1.2),
            (EXAM_IN_RANGE, "ZZTESTSOD", 135, 145),
            (EXAM_OUT_OF_RANGE_OLD, "ZZTESTPOT", 3.5, 5.5),
        ],
        start=1,
    ):
        session.execute(
            text(
                "INSERT INTO demo.segmentoexame "
                "(idsegmento, tpexame, abrev, nome, min, max, referencia, "
                "posicao, ativo, update_by) "
                "VALUES (1, :type, :abbrev, :abbrev, :min, :max, "
                "'ZZTEST referencia', :position, true, 1)"
            ),
            {
                "type": exam_type,
                "abbrev": abbrev,
                "min": minimum,
                "max": maximum,
                "position": position,
            },
        )

    for exam_id, (exam_type, result, days_ago) in enumerate(
        [
            # out of range and inside the 7-day window: the only one shown
            (EXAM_OUT_OF_RANGE, 3.5, 1),
            # inside the reference range: not an alert
            (EXAM_IN_RANGE, 140, 1),
            # out of range but older than the 7-day window
            (EXAM_OUT_OF_RANGE_OLD, 9.9, 30),
        ],
        start=1,
    ):
        session.execute(
            text(
                "INSERT INTO demo.exame "
                "(fkexame, fkpessoa, nratendimento, dtexame, tpexame, "
                "resultado, unidade) "
                "VALUES (:id, :id_patient, :admission, "
                "now() - CAST(:days || ' days' AS interval), :type, "
                ":result, 'ZZTESTUN')"
            ),
            {
                "id": 100900 + exam_id,
                "id_patient": ID_PATIENT,
                "admission": ADMISSION,
                "days": days_ago,
                "type": exam_type,
                "result": result,
            },
        )

    # the feature is driven by two global memory records: the config points at
    # the prompt record, and the prompt record holds one message list per topic
    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES ('summary-config', CAST(:value AS json), now(), 1)"
        ),
        {
            "value": json.dumps(
                {"provider": "claude", "prompt-config": PROMPT_CONFIG_KIND}
            )
        },
    )
    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST(:value AS json), now(), 1)"
        ),
        {
            "kind": PROMPT_CONFIG_KIND,
            "value": json.dumps(
                {
                    key: [{"role": "user", "content": f"{key}: :replace_text"}]
                    for key in SUMMARY_KEYS
                }
            ),
        },
    )

    session_commit()

    yield

    session.execute(
        text("DELETE FROM demo.evolucao WHERE fkevolucao = ANY(:ids)"),
        {"ids": NOTE_IDS},
    )
    session.execute(
        text("DELETE FROM demo.exame WHERE fkpessoa = :id_patient"),
        {"id_patient": ID_PATIENT},
    )
    session.execute(
        text("DELETE FROM demo.segmentoexame WHERE tpexame = ANY(:types)"),
        {"types": EXAM_TYPES},
    )
    session.execute(
        text("DELETE FROM demo.alergia WHERE fkpessoa = :id_patient"),
        {"id_patient": ID_PATIENT},
    )
    session.execute(
        text("DELETE FROM demo.medicamento WHERE fkmedicamento = ANY(:ids)"),
        {"ids": [DRUG_WITH_SUBSTANCE, DRUG_WITHOUT_SUBSTANCE]},
    )
    session.execute(
        text("DELETE FROM public.substancia WHERE sctid = :sctid"),
        {"sctid": SUBSTANCE},
    )
    session.execute(
        text("DELETE FROM public.memoria WHERE tipo IN ('summary-config', :kind)"),
        {"kind": PROMPT_CONFIG_KIND},
    )
    session.execute(
        text("DELETE FROM demo.pessoa WHERE nratendimento = ANY(:admissions)"),
        {"admissions": [ADMISSION, ADMISSION_NO_NOTES]},
    )
    session.execute(
        text("DELETE FROM demo.pessoa_audit WHERE nratendimento = ANY(:admissions)"),
        {"admissions": [ADMISSION, ADMISSION_NO_NOTES]},
    )
    session_commit()


@pytest.fixture
def summary_draft():
    """A previously saved discharge summary draft for the admission"""
    kind = f"draft_summary_{ADMISSION}"
    session.execute(
        text(
            "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST(:value AS json), now(), 1)"
        ),
        {"kind": kind, "value": json.dumps({"reason": "Rascunho salvo"})},
    )
    session_commit()

    yield

    session.execute(text("DELETE FROM demo.memoria WHERE tipo = :kind"), {"kind": kind})
    session_commit()


@pytest.fixture
def summary_mock_texts():
    """Sample texts used by the prompt preview (``?mock=true``)"""
    for key in SUMMARY_KEYS:
        session.execute(
            text(
                "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
                "VALUES (:kind, CAST(:value AS json), now(), 1)"
            ),
            {
                "kind": f"summary_text_{key}",
                "value": json.dumps({"text": f"ZZTEST exemplo {key}"}),
            },
        )
    session_commit()

    yield

    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo LIKE 'summary!_text!_%' ESCAPE '!'")
    )
    session_commit()


def _get_summary(client, headers, admission_number=ADMISSION, mock=False):
    """Call the endpoint and return the parsed ``data`` payload"""
    response = client.get(_url(admission_number, mock=mock), headers=headers)

    assert response.status_code == 200

    return response.get_json()["data"]


def _audit(data, key):
    """Annotations that fed the prompt of one summary topic, order-independent"""
    return sorted(data["summaryConfig"][key]["audit"])


def test_summary_no_token(client, summary_setup):
    """GET /summary/<admission> — returns 401 without authentication"""
    response = client.get(_url(ADMISSION), headers={"Accept": "application/json"})

    assert response.status_code == 401


def test_summary_permission_denied(client, viewer_headers, summary_setup):
    """GET /summary/<admission> — a role without READ_DISCHARGE_SUMMARY is rejected"""
    response = client.get(_url(ADMISSION), headers=viewer_headers)

    assert response.status_code == 401


def test_summary_unknown_admission(client, navigator_headers, summary_setup):
    """GET /summary/<admission> — an admission that does not exist is rejected"""
    response = client.get(_url(999999999), headers=navigator_headers)

    assert response.status_code == 400
    assert response.get_json()["code"] == "errors.invalidRecord"


def test_summary_patient_header(client, navigator_headers, summary_setup):
    """GET /summary/<admission> — returns the patient header with the derived IMC"""
    patient = _get_summary(client, navigator_headers)["patient"]

    assert patient["idPatient"] == str(ID_PATIENT)
    assert patient["admissionNumber"] == ADMISSION
    assert patient["admissionDate"].startswith("2024-01-10")
    assert patient["dischargeDate"].startswith("2024-01-21")
    assert patient["birthdate"] == "1970-05-04"
    assert patient["gender"] == "F"
    assert patient["weight"] == 70
    assert patient["height"] == 170
    assert patient["weightDate"].startswith("2024-01-10")
    assert patient["color"] == "ZZTEST COR"
    # 70 kg / (1.70 m)^2
    assert patient["imc"] == 24.22


def test_summary_imc_is_none_without_weight_and_height(
    client, navigator_headers, summary_setup
):
    """GET /summary/<admission> — the IMC is omitted when weight/height are unknown"""
    patient = _get_summary(client, navigator_headers, ADMISSION_NO_NOTES)["patient"]

    assert patient["weight"] is None
    assert patient["height"] is None
    assert patient["imc"] is None


def test_summary_lists_only_active_allergies(client, navigator_headers, summary_setup):
    """GET /summary/<admission> — active allergies only, named by substance when known"""
    allergies = _get_summary(client, navigator_headers)["allergies"]

    names = sorted(a["name"] for a in allergies)

    # the substance name wins over the local drug name of the same allergy
    assert names == ["ZZTEST DIPIRONA", SUBSTANCE_NAME]
    assert "ZZTEST INATIVA" not in names
    assert "ZZTEST NOME LOCAL" not in names


def test_summary_exams_are_recent_and_out_of_range(
    client, navigator_headers, summary_setup
):
    """GET /summary/<admission> — only out-of-range exams of the last 7 days show up"""
    exams = _get_summary(client, navigator_headers)["exams"]

    assert [e["name"] for e in exams] == ["ZZTESTCREAT"]
    assert exams[0]["result"] == 3.5
    assert exams[0]["measureUnit"] == "ZZTESTUN"
    assert exams[0]["date"] is not None


def test_summary_reason_window_covers_the_first_four_days(
    client, navigator_headers, summary_setup
):
    """GET /summary/<admission> — the admission reason reads the first four days"""
    data = _get_summary(client, navigator_headers)

    # written on the first note and two days later: both inside the window
    assert _audit(data, "reason") == ["Dor abdominal", "Febre persistente"]
    # written ten days after the first note: outside the window
    assert "Motivo registrado tardiamente" not in _audit(data, "reason")


def test_summary_previous_drugs_window_covers_the_first_day(
    client, navigator_headers, summary_setup
):
    """GET /summary/<admission> — previous drugs read only the first day"""
    data = _get_summary(client, navigator_headers)

    assert _audit(data, "previousDrugs") == ["Losartana"]
    # recorded on day two, already outside the one-day window
    assert "Metformina" not in _audit(data, "previousDrugs")


def test_summary_discharge_annotations_window_covers_the_last_day(
    client, navigator_headers, summary_setup
):
    """GET /summary/<admission> — discharge topics read backwards from the last note"""
    data = _get_summary(client, navigator_headers)

    # the last note and its eve are inside the window, the first note is not
    assert _audit(data, "dischargeCondition") == ["Alta melhorada"]
    assert _audit(data, "dischargePlan") == ["Plano final"]
    assert "Condicao do primeiro dia" not in _audit(data, "dischargeCondition")
    assert "Plano do primeiro dia" not in _audit(data, "dischargePlan")


def test_summary_unwindowed_topics_read_the_whole_admission(
    client, navigator_headers, summary_setup
):
    """GET /summary/<admission> — diagnosis, procedures and exams span every note"""
    data = _get_summary(client, navigator_headers)

    # written on two different notes, reported once
    assert _audit(data, "diagnosis") == ["Apendicite"]
    # first and last note, ten days apart, both kept
    assert _audit(data, "procedures") == ["Apendicectomia", "Curativo"]
    assert _audit(data, "exams") == ["Ultrassom de abdome"]


def test_summary_clinical_summary_joins_reason_procedures_and_summary(
    client, navigator_headers, summary_setup
):
    """GET /summary/<admission> — the clinical summary composes three other topics"""
    data = _get_summary(client, navigator_headers)

    expected = (
        _audit(data, "reason")
        + _audit(data, "procedures")
        # the "resumo" annotations, which have no topic of their own
        + ["Resumo da vespera", "Resumo final"]
    )

    assert _audit(data, "clinicalSummary") == sorted(expected)
    # the first-day summary is outside the one-day window of the last note
    assert "Resumo do primeiro dia" not in _audit(data, "clinicalSummary")


def test_summary_prompt_carries_the_annotation_text(
    client, navigator_headers, summary_setup
):
    """GET /summary/<admission> — the placeholder is replaced by the annotations"""
    data = _get_summary(client, navigator_headers)

    prompt = data["summaryConfig"]["previousDrugs"]["prompt"]

    assert prompt == [{"role": "user", "content": "previousDrugs: Losartana"}]
    assert sorted(data["summaryConfig"].keys()) == sorted(SUMMARY_KEYS)


def test_summary_mock_prompt_uses_the_sample_text(
    client, navigator_headers, summary_setup, summary_mock_texts
):
    """GET /summary/<admission>?mock=true — prompts preview the stored sample text"""
    data = _get_summary(client, navigator_headers, mock=True)

    prompt = data["summaryConfig"]["previousDrugs"]["prompt"]

    assert prompt == [
        {"role": "user", "content": "previousDrugs: ZZTEST exemplo previousDrugs"}
    ]
    # the audit trail still reports the real annotations of the admission
    assert _audit(data, "previousDrugs") == ["Losartana"]


def test_summary_without_notes_has_empty_annotations(
    client, navigator_headers, summary_setup
):
    """GET /summary/<admission> — an admission with no notes yields empty topics"""
    data = _get_summary(client, navigator_headers, ADMISSION_NO_NOTES)

    for key in SUMMARY_KEYS:
        assert data["summaryConfig"][key]["audit"] == []
        assert data["summaryConfig"][key]["prompt"] == [
            {"role": "user", "content": f"{key}: "}
        ]


def test_summary_returns_no_draft_when_none_was_saved(
    client, navigator_headers, summary_setup
):
    """GET /summary/<admission> — the draft is null until one is saved"""
    assert _get_summary(client, navigator_headers)["draft"] is None


def test_summary_returns_the_saved_draft(
    client, navigator_headers, summary_setup, summary_draft
):
    """GET /summary/<admission> — a saved draft comes back with the summary"""
    assert _get_summary(client, navigator_headers)["draft"] == {
        "reason": "Rascunho salvo"
    }
