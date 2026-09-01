"""Tests: GET /summary/<admissionNumber> — the discharge summary work sheet.

The endpoint gathers everything the discharge summary screen needs for one
admission in a single call. Most of it is plain projection, but three parts
carry real clinical risk and are what these tests pin down:

* **the annotation windows.** Each summary field is mined from the clinical
  notes of the admission, and each one uses a *different* time window anchored
  on either the first or the last note: the admission reason looks 4 days
  forward from the first note, the previous medication 1 day forward, and the
  discharge fields 1 day backward from the last note. Widening a window would
  pull unrelated text into a discharge document; narrowing it would silently
  drop content the pharmacist wrote.

* **the prompt assembly.** The mined text is spliced into the LLM prompt stored
  in global memory by replacing the ``:replace_text`` marker. The splice happens
  inside a JSON string, so quotes in a clinical note have to survive the round
  trip — an unescaped one would corrupt the prompt.

* **the out-of-range exam list.** Only results outside the segment's reference
  range, from the last 7 days, at reference position 30 or better, and only the
  most recent one per exam type.

``drugsUsed``, ``drugsSuspended`` and ``receipt`` are pinned as empty on
purpose: all three currently return early with a "needs refactor" note, and the
test records that the endpoint still answers with the keys the client reads.

All fixture data is created by the tests. Reserved id ranges (see
tests/conftest.py): admissions/patients >= 100000, drugs and substances
>= 90000; clinical notes and exams use >= 100000 and are removed by the
fixtures themselves.
"""

import json
from datetime import datetime

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from utils import status

URL = "/summary"

# Reserved ids, all wiped by the fixtures below (and by clean_test_artifacts).
ADMISSION = 100777
PATIENT_ID = 100777
EMPTY_ADMISSION = 100778  # same patient, no clinical notes
SUBSTANCE_ID = 90777
DRUG_ID = 90777
NOTE_ID_BASE = 100777000
EXAM_ID_BASE = 100777000

# Clinical note dates. The first note anchors the forward-looking windows and
# the last note anchors the backward-looking ones.
FIRST_NOTE = datetime(2026, 1, 10, 8, 0)
LAST_NOTE = datetime(2026, 1, 25, 8, 0)

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

# One note per row: (offset from NOTE_ID_BASE, date, sumario payload).
NOTES = [
    # the first note — inside every forward window
    (
        1,
        FIRST_NOTE,
        {
            "motivo": ["dor toracica"],
            "motivo_text": ["Paciente com dor toracica."],
            "medprevio": ["losartana"],
            "diagnostico": ['IAM "sem supra"'],
            "procedimentos": ["cateterismo"],
            "exames": ["troponina alterada"],
        },
    ),
    # 3 days after the first note: inside the 4-day reason window, outside the
    # 1-day previous-medication window
    (
        2,
        datetime(2026, 1, 13, 8, 0),
        {"motivo": ["dor irradiada"], "medprevio": ["fora da janela"]},
    ),
    # 10 days after the first note: outside every forward window
    (
        3,
        datetime(2026, 1, 20, 8, 0),
        {"motivo": ["reavaliacao tardia"], "medprevio": ["tardio"]},
    ),
    # 3 days before the last note: outside the 1-day backward window
    (
        4,
        datetime(2026, 1, 22, 8, 0),
        {"resumo": ["fora da janela"], "planoalta": ["fora da janela"]},
    ),
    # 1 day before the last note: inside the backward window
    (5, datetime(2026, 1, 24, 12, 0), {"resumo": ["sem intercorrencias"]}),
    # the last note — repeats "cateterismo" to prove values are de-duplicated
    (
        6,
        LAST_NOTE,
        {
            "resumo": ["evolucao estavel"],
            "planoalta": ["retorno em 30 dias"],
            "condicaoalta": ["alta melhorada"],
            "procedimentos": ["cateterismo"],
        },
    ),
]

# Reference ranges for the exams below. (tpexame, abrev, min, max, posicao)
# The zzsum prefix is reserved for this module; test_admin_exam.py owns zzt*.
SEGMENT_EXAMS = [
    ("zzsumcr", "ZZCreat", 0.5, 1.5, 1),
    ("zzsumna", "ZZSodio", 135.0, 145.0, 2),
    ("zzsumk", "ZZPotassio", 3.5, 5.0, 3),
    ("zzsumhb", "ZZHb", 12.0, 16.0, 90),  # beyond the position 30 report keeps
]

# (offset, tpexame, result, days ago, unit)
EXAMS = [
    # most recent out-of-range creatinine — the one result that must show up.
    # Upper-cased on purpose: the join lower()s the exam type.
    (1, "ZZSUMCR", 3.5, 1, "mg/dL"),
    # an older out-of-range creatinine, hidden by the most recent one
    (2, "zzsumcr", 2.5, 3, "mg/dL"),
    # inside the reference range
    (3, "zzsumna", 140.0, 1, "mEq/L"),
    # out of range but older than the 7-day window
    (4, "zzsumk", 7.0, 10, "mEq/L"),
    # out of range and recent, but its reference position is past 30
    (5, "zzsumhb", 5.0, 1, "g/dL"),
]


def _prompt_config(marker_prefix):
    """Build a prompt-per-field global memory value.

    Each field gets a chat transcript carrying the ``:replace_text`` marker the
    service replaces with the mined annotation text.
    """
    return {
        key: [{"role": "user", "content": f"{marker_prefix} {key}: :replace_text"}]
        for key in SUMMARY_KEYS
    }


def _insert_global_memory(kind, value):
    """Insert one public.memoria row."""
    session.execute(
        text(
            "INSERT INTO public.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST(:value AS json), now(), 1)"
        ),
        {"kind": kind, "value": _json(value)},
    )


def _insert_schema_memory(kind, value):
    """Insert one demo.memoria row."""
    session.execute(
        text(
            "INSERT INTO demo.memoria (tipo, valor, update_at, update_by) "
            "VALUES (:kind, CAST(:value AS json), now(), 1)"
        ),
        {"kind": kind, "value": _json(value)},
    )


def _json(value):
    """Serialize a fixture value for a json/jsonb column."""
    return json.dumps(value)


@pytest.fixture(scope="module", autouse=True)
def summary_fixtures():
    """Create the admission, its clinical notes, exams, allergies and configs.

    Module-scoped: every test reads the same admission, and only the global
    memory rows are re-pointed per test (see `sentence_prompt_config`).
    """
    _remove_fixtures()

    # patient / admissions
    session.execute(
        text(
            "INSERT INTO demo.pessoa "
            "  (fkpessoa, nratendimento, dtinternacao, dtalta, dtnascimento, "
            "   sexo, peso, altura, dtpeso, cor) "
            "VALUES (:patient, :admission, '2026-01-10 08:00:00', "
            "        '2026-01-25 10:00:00', '1980-05-10', 'M', 80, 180, "
            "        '2026-01-10 09:00:00', 'B')"
        ),
        {"patient": PATIENT_ID, "admission": ADMISSION},
    )
    session.execute(
        text(
            "INSERT INTO demo.pessoa (fkpessoa, nratendimento, dtinternacao) "
            "VALUES (:patient, :admission, '2026-02-01 08:00:00')"
        ),
        {"patient": PATIENT_ID, "admission": EMPTY_ADMISSION},
    )

    for offset, date, summary in NOTES:
        session.execute(
            text(
                "INSERT INTO demo.evolucao "
                "  (fkevolucao, nratendimento, dtevolucao, texto, exame, sumario) "
                "VALUES (:id, :admission, :date, 'nota', false, "
                "        CAST(:summary AS jsonb))"
            ),
            {
                "id": NOTE_ID_BASE + offset,
                "admission": ADMISSION,
                "date": date,
                "summary": _json(summary),
            },
        )

    for type_exam, abbrev, minimum, maximum, position in SEGMENT_EXAMS:
        session.execute(
            text(
                "INSERT INTO demo.segmentoexame "
                "  (idsegmento, tpexame, abrev, nome, min, max, posicao, ativo, "
                "   update_at, update_by) "
                "VALUES (1, :type_exam, :abbrev, :abbrev, :minimum, :maximum, "
                "        :position, true, now(), 1)"
            ),
            {
                "type_exam": type_exam,
                "abbrev": abbrev,
                "minimum": minimum,
                "maximum": maximum,
                "position": position,
            },
        )

    for offset, type_exam, result, days_ago, unit in EXAMS:
        session.execute(
            text(
                "INSERT INTO demo.exame "
                "  (fkexame, fkpessoa, nratendimento, dtexame, tpexame, "
                "   resultado, unidade) "
                "VALUES (:id, :patient, :admission, "
                "        now() - CAST(:days_ago AS text)::interval, "
                "        :type_exam, :result, :unit)"
            ),
            {
                "id": EXAM_ID_BASE + offset,
                "patient": PATIENT_ID,
                "admission": ADMISSION,
                "days_ago": f"{days_ago} days",
                "type_exam": type_exam,
                "result": result,
                "unit": unit,
            },
        )

    # an allergy named by its substance, one named by free text, one inactive
    # only the name is read back (the allergy list coalesces to it), so the
    # substance is left unclassified rather than borrowing a seed class
    session.execute(
        text(
            "INSERT INTO public.substancia "
            "  (sctid, nome, link, ativo, update_at, update_by) "
            "VALUES (:id, 'ZZDIPIRONA', '', true, now(), 1)"
        ),
        {"id": SUBSTANCE_ID},
    )
    session.execute(
        text(
            "INSERT INTO demo.medicamento (fkmedicamento, nome, sctid, created_at) "
            "VALUES (:id, 'ZZDIPIRONA 500 MG CP', :sctid, now())"
        ),
        {"id": DRUG_ID, "sctid": SUBSTANCE_ID},
    )
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "  (fkpessoa, fkmedicamento, ativo, created_at, created_by) "
            "VALUES (:patient, :drug, true, now(), 1)"
        ),
        {"patient": PATIENT_ID, "drug": DRUG_ID},
    )
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "  (fkpessoa, nome_medicamento, ativo, created_at, created_by) "
            "VALUES (:patient, 'ZZPOEIRA', true, now(), 1)"
        ),
        {"patient": PATIENT_ID},
    )
    session.execute(
        text(
            "INSERT INTO demo.alergia "
            "  (fkpessoa, nome_medicamento, ativo, created_at, created_by) "
            "VALUES (:patient, 'ZZINATIVA', false, now(), 1)"
        ),
        {"patient": PATIENT_ID},
    )

    # the LLM configuration: which prompt set to use, and the prompts themselves
    _insert_global_memory(
        "summary-config", {"provider": "claude", "prompt-config": "summary-prompt"}
    )
    _insert_global_memory("summary-prompt", _prompt_config("PROMPT"))
    _insert_global_memory("summary-prompt-sentence", _prompt_config("FRASE"))

    session_commit()

    yield

    _remove_fixtures()


@pytest.fixture
def sentence_prompt_config():
    """Point summary-config at the sentence prompt set for one test.

    The sentence set reads the ``*_text`` variant of every annotation field, so
    this fixture also switches which clinical-note keys are mined.
    """
    session.execute(
        text(
            "UPDATE public.memoria SET valor = CAST(:value AS json) "
            "WHERE tipo = 'summary-config'"
        ),
        {
            "value": _json(
                {"provider": "claude", "prompt-config": "summary-prompt-sentence"}
            )
        },
    )
    session_commit()

    yield

    session.execute(
        text(
            "UPDATE public.memoria SET valor = CAST(:value AS json) "
            "WHERE tipo = 'summary-config'"
        ),
        {"value": _json({"provider": "claude", "prompt-config": "summary-prompt"})},
    )
    session_commit()


@pytest.fixture
def draft():
    """Store a saved draft for the admission."""
    _insert_schema_memory(f"draft_summary_{ADMISSION}", {"text": "rascunho salvo"})
    session_commit()

    yield {"text": "rascunho salvo"}

    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo = :kind"),
        {"kind": f"draft_summary_{ADMISSION}"},
    )
    session_commit()


@pytest.fixture
def mock_texts():
    """Store the canned per-field texts the ``mock`` mode splices in."""
    for key in SUMMARY_KEYS:
        _insert_schema_memory(f"summary_text_{key}", {"text": f"texto mock {key}"})
    session_commit()

    yield

    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo LIKE 'summary!_text!_%' ESCAPE '!'")
    )
    session_commit()


def _remove_fixtures():
    """Delete everything the module fixture creates, so a re-run is clean."""
    session.execute(
        text("DELETE FROM demo.evolucao WHERE nratendimento IN (:one, :two)"),
        {"one": ADMISSION, "two": EMPTY_ADMISSION},
    )
    session.execute(
        text("DELETE FROM demo.exame WHERE fkpessoa = :patient"),
        {"patient": PATIENT_ID},
    )
    session.execute(
        text("DELETE FROM demo.segmentoexame WHERE tpexame IN :types").bindparams(
            types=tuple(type_exam for type_exam, *_ in SEGMENT_EXAMS)
        )
    )
    session.execute(
        text("DELETE FROM demo.alergia WHERE fkpessoa = :patient"),
        {"patient": PATIENT_ID},
    )
    session.execute(
        text("DELETE FROM demo.medicamento WHERE fkmedicamento = :id"),
        {"id": DRUG_ID},
    )
    session.execute(
        text("DELETE FROM public.substancia WHERE sctid = :id"), {"id": SUBSTANCE_ID}
    )
    session.execute(
        text("DELETE FROM demo.pessoa WHERE nratendimento IN (:one, :two)"),
        {"one": ADMISSION, "two": EMPTY_ADMISSION},
    )
    session.execute(
        text("DELETE FROM demo.pessoa_audit WHERE nratendimento IN (:one, :two)"),
        {"one": ADMISSION, "two": EMPTY_ADMISSION},
    )
    session.execute(
        text(
            "DELETE FROM public.memoria WHERE tipo IN "
            "('summary-config', 'summary-prompt', 'summary-prompt-sentence')"
        )
    )
    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo LIKE 'summary!_text!_%' ESCAPE '!'")
    )
    session.execute(
        text("DELETE FROM demo.memoria WHERE tipo = :kind"),
        {"kind": f"draft_summary_{ADMISSION}"},
    )
    session_commit()


def _get(client, headers, admission_number=ADMISSION, mock=None):
    """Call the endpoint, adding the ``mock`` flag only when asked for."""
    return client.get(
        f"{URL}/{admission_number}",
        query_string={"mock": mock} if mock is not None else {},
        headers=headers,
    )


def _data(client, headers, **kwargs):
    """Call the endpoint and return the payload of a successful response."""
    response = _get(client, headers, **kwargs)

    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"]


def _audit(data, key):
    """The mined values behind one summary field, order-independent."""
    return set(data["summaryConfig"][key]["audit"])


def _prompt_text(data, key):
    """The single prompt message rendered for one summary field."""
    return data["summaryConfig"][key]["prompt"][0]["content"]


# --------------------------------------------------------------------------
# access
# --------------------------------------------------------------------------


def test_summary_requires_the_discharge_summary_permission(client, analyst_headers):
    """GET /summary/id - 401 for a role without READ_DISCHARGE_SUMMARY"""
    response = _get(client, analyst_headers)

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_summary_is_open_to_the_navigator(client, navigator_headers):
    """GET /summary/id - NAVIGATOR carries READ_DISCHARGE_SUMMARY"""
    response = _get(client, navigator_headers)

    assert response.status_code == status.HTTP_200_OK


def test_an_unknown_admission_is_rejected(client, navigator_headers):
    """GET /summary/id - an admission with no patient row is refused [400]"""
    response = _get(client, navigator_headers, admission_number=999999)

    assert response.status_code == status.HTTP_400_BAD_REQUEST
    assert response.get_json()["code"] == "errors.invalidRecord"


# --------------------------------------------------------------------------
# patient block
# --------------------------------------------------------------------------


def test_the_patient_block_carries_the_admission_identity(client, navigator_headers):
    """GET /summary/id - patient identity, dates and measurements are projected"""
    patient = _data(client, navigator_headers)["patient"]

    # ids are stringified so a bigint survives the trip to the browser
    assert patient["idPatient"] == str(PATIENT_ID)
    assert patient["admissionNumber"] == ADMISSION
    assert patient["gender"] == "M"
    assert patient["color"] == "B"
    assert patient["weight"] == 80
    assert patient["height"] == 180
    assert patient["admissionDate"].startswith("2026-01-10")
    assert patient["dischargeDate"].startswith("2026-01-25")
    assert patient["weightDate"].startswith("2026-01-10")
    assert patient["birthdate"].startswith("1980-05-10")


def test_the_imc_is_derived_from_weight_and_height(client, navigator_headers):
    """GET /summary/id - IMC is computed from the patient's weight and height"""
    patient = _data(client, navigator_headers)["patient"]

    # 80 kg / 1.80 m² — height is stored in centimetres
    assert patient["imc"] == 24.69


def test_the_imc_is_omitted_without_a_height(client, navigator_headers):
    """GET /summary/id - IMC is None when a measurement is missing"""
    patient = _data(client, navigator_headers, admission_number=EMPTY_ADMISSION)[
        "patient"
    ]

    assert patient["imc"] is None
    assert patient["dischargeDate"] is None
    assert patient["birthdate"] is None


# --------------------------------------------------------------------------
# annotation windows
# --------------------------------------------------------------------------


def test_the_reason_looks_four_days_forward_from_the_first_note(
    client, navigator_headers
):
    """GET /summary/id - the admission reason spans the first 4 days"""
    data = _data(client, navigator_headers)

    # the note 3 days in is kept, the one 10 days in is not
    assert _audit(data, "reason") == {"dor toracica", "dor irradiada"}


def test_the_previous_medication_looks_only_one_day_forward(client, navigator_headers):
    """GET /summary/id - previous medication spans a single day from the first note"""
    data = _data(client, navigator_headers)

    # the same notes feed the reason, but this window is 3 days narrower
    assert _audit(data, "previousDrugs") == {"losartana"}


def test_the_discharge_fields_look_one_day_back_from_the_last_note(
    client, navigator_headers
):
    """GET /summary/id - discharge fields span the last day of the admission"""
    data = _data(client, navigator_headers)

    assert _audit(data, "dischargePlan") == {"retorno em 30 dias"}
    assert _audit(data, "dischargeCondition") == {"alta melhorada"}


def test_unwindowed_fields_read_the_whole_admission(client, navigator_headers):
    """GET /summary/id - diagnosis, procedures and exams have no time window"""
    data = _data(client, navigator_headers)

    assert _audit(data, "diagnosis") == {'IAM "sem supra"'}
    assert _audit(data, "exams") == {"troponina alterada"}


def test_a_value_repeated_across_notes_is_listed_once(client, navigator_headers):
    """GET /summary/id - repeated annotations are de-duplicated"""
    data = _data(client, navigator_headers)

    # "cateterismo" is written on both the first and the last note
    assert data["summaryConfig"]["procedures"]["audit"] == ["cateterismo"]


def test_the_clinical_summary_joins_reason_procedures_and_evolution(
    client, navigator_headers
):
    """GET /summary/id - the clinical summary concatenates three other fields"""
    data = _data(client, navigator_headers)

    summary_audit = _audit(data, "clinicalSummary")

    assert summary_audit == (
        _audit(data, "reason")
        | _audit(data, "procedures")
        | {"evolucao estavel", "sem intercorrencias"}
    )


def test_an_admission_without_notes_yields_empty_annotations(
    client, navigator_headers
):
    """GET /summary/id - every field is empty when the admission has no notes"""
    data = _data(client, navigator_headers, admission_number=EMPTY_ADMISSION)

    for key in SUMMARY_KEYS:
        assert data["summaryConfig"][key]["audit"] == []
        assert _prompt_text(data, key).endswith(f"{key}: ")


# --------------------------------------------------------------------------
# prompt assembly
# --------------------------------------------------------------------------


def test_the_mined_text_is_spliced_into_the_configured_prompt(
    client, navigator_headers
):
    """GET /summary/id - :replace_text is replaced by the mined annotations"""
    data = _data(client, navigator_headers)

    assert set(data["summaryConfig"].keys()) == set(SUMMARY_KEYS)
    assert _prompt_text(data, "previousDrugs") == "PROMPT previousDrugs: losartana"


def test_a_quote_in_a_note_survives_the_prompt_splice(client, navigator_headers):
    """GET /summary/id - quotes are escaped so the prompt JSON stays valid"""
    data = _data(client, navigator_headers)

    # spliced into a JSON string and parsed back, so the quotes come out intact
    assert _prompt_text(data, "diagnosis") == 'PROMPT diagnosis: IAM "sem supra"'


def test_the_sentence_config_mines_the_text_variant_of_each_field(
    client, navigator_headers, sentence_prompt_config
):
    """GET /summary/id - the sentence prompt set reads the *_text annotations"""
    data = _data(client, navigator_headers)

    # motivo_text holds the full sentence, motivo only the keyword
    assert _audit(data, "reason") == {"Paciente com dor toracica."}
    assert _prompt_text(data, "reason") == "FRASE reason: Paciente com dor toracica."


def test_mock_mode_splices_the_stored_sample_texts(
    client, navigator_headers, mock_texts
):
    """GET /summary/id?mock - the canned texts replace the mined annotations"""
    data = _data(client, navigator_headers, mock="true")

    assert _prompt_text(data, "reason") == "PROMPT reason: texto mock reason"
    # the audit trail still shows what was really written in the notes
    assert _audit(data, "reason") == {"dor toracica", "dor irradiada"}


# --------------------------------------------------------------------------
# exams
# --------------------------------------------------------------------------


def test_only_the_latest_out_of_range_recent_exam_is_reported(
    client, navigator_headers
):
    """GET /summary/id - exams are filtered by range, recency and position"""
    exams = _data(client, navigator_headers)["exams"]

    # in-range sodium, the 10-day-old potassium and the position-90 haemoglobin
    # are all dropped; of the two creatinines only the most recent survives
    assert [e["name"] for e in exams] == ["ZZCreat"]
    assert exams[0]["result"] == 3.5
    assert exams[0]["measureUnit"] == "mg/dL"
    assert exams[0]["date"] is not None


def test_an_admission_of_a_patient_without_exams_reports_none(
    client, navigator_headers
):
    """GET /summary/id - an unknown admission of the same patient still lists exams

    The exam list is keyed by patient, not by admission, so the second
    admission of the same patient sees the same result.
    """
    exams = _data(client, navigator_headers, admission_number=EMPTY_ADMISSION)["exams"]

    assert [e["name"] for e in exams] == ["ZZCreat"]


# --------------------------------------------------------------------------
# allergies
# --------------------------------------------------------------------------


def test_active_allergies_are_named_by_substance_or_free_text(
    client, navigator_headers
):
    """GET /summary/id - active allergies only, substance name preferred"""
    allergies = _data(client, navigator_headers)["allergies"]

    # ZZDIPIRONA comes from the substance behind the drug, ZZPOEIRA is free
    # text, and the inactive ZZINATIVA is not reported
    assert {a["name"] for a in allergies} == {"ZZDIPIRONA", "ZZPOEIRA"}


# --------------------------------------------------------------------------
# draft and the keys pending a refactor
# --------------------------------------------------------------------------


def test_the_draft_is_null_until_one_is_saved(client, navigator_headers):
    """GET /summary/id - no stored draft means a null draft"""
    assert _data(client, navigator_headers)["draft"] is None


def test_a_saved_draft_is_returned(client, navigator_headers, draft):
    """GET /summary/id - the draft stored for the admission is returned"""
    assert _data(client, navigator_headers)["draft"] == draft


def test_the_drug_and_receipt_keys_are_still_answered(client, navigator_headers):
    """GET /summary/id - drugsUsed, drugsSuspended and receipt are empty for now

    All three queries were disabled pending a refactor; the keys stay in the
    payload so the screen keeps rendering.
    """
    data = _data(client, navigator_headers)

    assert data["drugsUsed"] == []
    assert data["drugsSuspended"] == []
    assert data["receipt"] == []
