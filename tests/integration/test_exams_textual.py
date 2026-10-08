"""Tests: the textual exams served by GET /exams/<admission_number>.

Most exams are numbers: a creatinine value with a unit and a reference range.
Some are not — an imaging report, a biopsy, a microbiology description — and
those arrive as free text. NoHarm does not keep them in the exam table at all:
the integration writes them to ``demo.evolucao`` (the clinical-note table) with
``exame = true``, and the exam endpoint folds them back into the same payload
the numeric exams are served in, so the front end draws one list.

That fold is what these tests cover (``exams_service._get_textual_exams`` and
the grouping that follows it in ``get_exams_by_admission``). The parts that
matter clinically:

* **Which notes count.** Only ``exame = true`` rows with text, and only from the
  last 90 days — an old report must not resurface next to today's bloodwork.
* **Which admissions they come from.** A textual exam stays relevant across
  stays, so the lookup is not limited to the admission being viewed: it also
  reads the patient's five most recent admissions. A patient on their sixth stay
  no longer sees the first one.
* **How they are grouped.** One entry per prescriber (slugified into the key),
  with every note by that prescriber as its history, newest first. Notes with no
  prescriber collect under a single "EXAMES TEXTUAIS" bucket.
* **That they travel with the numeric exams**, under the same keys the numeric
  side uses, rather than in a section of their own.

Everything is written through the schema the API reads, so these are end-to-end
reads of the real endpoint.
"""

from datetime import datetime, timedelta

import pytest
from sqlalchemy import text

from tests.conftest import session, session_commit
from tests.utils.utils_test_prescription import test_counters
from utils import status

SEGMENT = 1

# Dates are relative: the 90-day window is measured from "now", so fixed dates
# would start falling out of it as the suite ages.
NOW = datetime.today()
RECENT = NOW - timedelta(days=1)
OLDER = NOW - timedelta(days=2)
OLDEST = NOW - timedelta(days=3)
# Comfortably outside the window, and far enough from the edge that a test run
# straddling midnight cannot flip it.
EXPIRED = NOW - timedelta(days=95)

RADIOLOGIST = "Dr. Fulano Beltrano"
RADIOLOGIST_KEY = "b-dr-fulano-beltrano-"
PATHOLOGIST = "Dra. Ciclana de Tal"
PATHOLOGIST_KEY = "b-dra-ciclana-de-tal-"
UNSIGNED_KEY = "EXAMES TEXTUAIS"

# admissions and patients this module writes, cleaned up by number
_admissions = []
_patients = []
# which patient each written admission belongs to, so a fixture that needs the
# patient id does not have to guess it from the order the counters were drawn
_patient_of = {}

# ids handed out to the evolucao rows written here, kept clear of the ranges the
# notes modules reserve
_next_note_id = 300000


def _next_admission() -> int:
    """Reserve an admission number no other test uses."""
    admission = test_counters["admission_number"]
    test_counters["admission_number"] += 1
    _admissions.append(admission)

    return admission


def _next_patient() -> int:
    """Reserve a patient id no other test uses."""
    id_patient = test_counters["admission_number"]
    test_counters["admission_number"] += 1
    _patients.append(id_patient)

    return id_patient


def _insert_admission(admission: int, id_patient: int, admitted: datetime):
    """Write a demo.pessoa row so the admission belongs to a patient."""
    _patient_of[admission] = id_patient
    session.execute(
        text(
            "INSERT INTO demo.pessoa "
            "(fkhospital, fkpessoa, nratendimento, dtnascimento, dtinternacao) "
            "VALUES (1, :id_patient, :admission, :birthdate, :admitted)"
        ),
        {
            "id_patient": id_patient,
            "admission": admission,
            # an adult: the under-18 branch swaps in the paediatric formulas and
            # is not what these tests are about
            "birthdate": datetime(1980, 1, 1),
            "admitted": admitted,
        },
    )


def _insert_exam_note(
    admission: int,
    date: datetime,
    text_content: str,
    prescriber: str = RADIOLOGIST,
    is_exam: bool = True,
) -> int:
    """Write a demo.evolucao row — ``exame = true`` makes it a textual exam."""
    global _next_note_id
    id_note = _next_note_id
    _next_note_id += 1

    session.execute(
        text(
            "INSERT INTO demo.evolucao "
            "(fkevolucao, nratendimento, texto, dtevolucao, prescritor, exame) "
            "VALUES (:id, :admission, :text, :date, :prescriber, :is_exam)"
        ),
        {
            "id": id_note,
            "admission": admission,
            "text": text_content,
            "date": date,
            "prescriber": prescriber,
            "is_exam": is_exam,
        },
    )

    return id_note


def _cleanup():
    """Drop every row this module wrote — tests.conftest does not know them."""
    if _admissions:
        session.execute(
            text("DELETE FROM demo.evolucao WHERE nratendimento = ANY(:admissions)"),
            {"admissions": _admissions},
        )
        session.execute(
            text("DELETE FROM demo.pessoa WHERE nratendimento = ANY(:admissions)"),
            {"admissions": _admissions},
        )
    session_commit()


@pytest.fixture(autouse=True, scope="module")
def cleanup_module():
    """Leave the schema as it was found, even if a test failed halfway."""
    yield
    _cleanup()


@pytest.fixture
def admission():
    """A fresh admission belonging to a fresh patient."""
    id_patient = _next_patient()
    number = _next_admission()
    _insert_admission(admission=number, id_patient=id_patient, admitted=OLDEST)
    session_commit()

    return number


def _get_exams(client, headers, admission: int) -> dict:
    """GET the exam panel of an admission and return its data payload."""
    response = client.get(f"/exams/{admission}?idSegment={SEGMENT}", headers=headers)

    assert response.status_code == status.HTTP_200_OK

    return response.get_json()["data"]


class TestWhichNotesBecomeExams:
    """The filter that separates a textual exam from an ordinary clinical note."""

    def test_an_exam_note_is_served(self, client, analyst_headers, admission):
        """A note flagged ``exame = true`` shows up in the exam panel."""
        _insert_exam_note(admission, RECENT, "Laudo de tomografia de torax")
        session_commit()

        assert RADIOLOGIST_KEY in _get_exams(client, analyst_headers, admission)

    def test_an_ordinary_note_is_not_an_exam(self, client, analyst_headers, admission):
        """A note without the exam flag belongs to the timeline, not the exam panel."""
        _insert_exam_note(admission, RECENT, "Evolucao de enfermagem", is_exam=False)
        session_commit()

        assert _get_exams(client, analyst_headers, admission) == {}

    def test_a_note_older_than_ninety_days_is_dropped(
        self, client, analyst_headers, admission
    ):
        """The window keeps a stale report from sitting next to today's results."""
        _insert_exam_note(admission, EXPIRED, "Laudo do ano passado")
        session_commit()

        assert _get_exams(client, analyst_headers, admission) == {}

    def test_the_window_keeps_the_recent_note_and_drops_the_old_one(
        self, client, analyst_headers, admission
    ):
        """Only the in-window note survives when the same prescriber has both."""
        _insert_exam_note(admission, EXPIRED, "Laudo expirado")
        _insert_exam_note(admission, RECENT, "Laudo vigente")
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[RADIOLOGIST_KEY]

        assert [h["value"] for h in entry["history"]] == ["Laudo vigente"]

    def test_an_admission_without_exam_notes_answers_empty(
        self, client, analyst_headers, admission
    ):
        """No notes is an empty panel, not an error."""
        assert _get_exams(client, analyst_headers, admission) == {}


class TestGroupingByPrescriber:
    """One entry per prescriber, carrying that prescriber's notes as its history."""

    def test_two_prescribers_make_two_entries(self, client, analyst_headers, admission):
        """Reports are grouped by who signed them."""
        _insert_exam_note(admission, RECENT, "Laudo de imagem")
        _insert_exam_note(
            admission, RECENT, "Laudo de anatomia patologica", prescriber=PATHOLOGIST
        )
        session_commit()

        data = _get_exams(client, analyst_headers, admission)

        assert set(data.keys()) == {RADIOLOGIST_KEY, PATHOLOGIST_KEY}

    def test_the_entry_carries_the_prescriber_name_unchanged(
        self, client, analyst_headers, admission
    ):
        """The key is slugified; the displayed name is the original string."""
        _insert_exam_note(admission, RECENT, "Laudo de imagem")
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[RADIOLOGIST_KEY]

        assert entry["name"] == RADIOLOGIST

    def test_the_entry_is_flagged_as_textual(self, client, analyst_headers, admission):
        """``text: true`` is how the front end knows not to plot this one."""
        _insert_exam_note(admission, RECENT, "Laudo de imagem")
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[RADIOLOGIST_KEY]

        assert entry["text"] is True

    def test_notes_without_a_prescriber_share_one_bucket(
        self, client, analyst_headers, admission
    ):
        """An unsigned report still has to land somewhere, so they collect together."""
        _insert_exam_note(admission, RECENT, "Laudo sem assinatura", prescriber=None)
        _insert_exam_note(
            admission, OLDER, "Outro laudo sem assinatura", prescriber=None
        )
        session_commit()

        data = _get_exams(client, analyst_headers, admission)

        assert list(data.keys()) == [UNSIGNED_KEY]
        assert len(data[UNSIGNED_KEY]["history"]) == 2

    def test_the_unsigned_bucket_has_no_name(self, client, analyst_headers, admission):
        """There is no prescriber to show, so the name stays empty."""
        _insert_exam_note(admission, RECENT, "Laudo sem assinatura", prescriber=None)
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[UNSIGNED_KEY]

        assert entry["name"] is None

    def test_the_unsigned_bucket_is_separate_from_a_signed_one(
        self, client, analyst_headers, admission
    ):
        """An unsigned report is not merged into whoever else reported that day."""
        _insert_exam_note(admission, RECENT, "Laudo assinado")
        _insert_exam_note(admission, RECENT, "Laudo anonimo", prescriber=None)
        session_commit()

        data = _get_exams(client, analyst_headers, admission)

        assert set(data.keys()) == {RADIOLOGIST_KEY, UNSIGNED_KEY}

    def test_the_group_key_is_the_slugified_prescriber(
        self, client, analyst_headers, admission
    ):
        """Pins the key the front end indexes on.

        ``stringutils.slugify`` runs ``remove_accents`` first, which returns
        ``bytes``; the ``str()`` that follows therefore stringifies the repr and
        leaves a ``b-`` prefix and a trailing ``-`` on every key. That is wrong,
        but it is the key the stored data and the front end already use, so it is
        asserted here as-is rather than quietly corrected — changing it is a
        migration, not a test fix.
        """
        _insert_exam_note(admission, RECENT, "Laudo de imagem", prescriber="RAIO X")
        session_commit()

        assert list(_get_exams(client, analyst_headers, admission)) == ["b-raio-x-"]


class TestHistoryAndOrdering:
    """What each entry shows at a glance, and in what order its history reads."""

    def test_history_is_newest_first(self, client, analyst_headers, admission):
        """The panel shows the latest report first, like the numeric exams do."""
        _insert_exam_note(admission, OLDEST, "Laudo mais antigo")
        _insert_exam_note(admission, RECENT, "Laudo mais recente")
        _insert_exam_note(admission, OLDER, "Laudo intermediario")
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[RADIOLOGIST_KEY]

        assert [h["value"] for h in entry["history"]] == [
            "Laudo mais recente",
            "Laudo intermediario",
            "Laudo mais antigo",
        ]

    def test_every_history_item_carries_its_own_date(
        self, client, analyst_headers, admission
    ):
        """Each report keeps the date it was written, not the group's."""
        _insert_exam_note(admission, RECENT, "Laudo recente")
        _insert_exam_note(admission, OLDEST, "Laudo antigo")
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[RADIOLOGIST_KEY]

        assert [h["date"] for h in entry["history"]] == [
            RECENT.isoformat(),
            OLDEST.isoformat(),
        ]

    def test_the_summary_line_is_the_start_of_the_newest_report(
        self, client, analyst_headers, admission
    ):
        """``ref`` is the collapsed preview, so it has to come from the latest note."""
        newest = "Tomografia de torax sem alteracoes relevantes"
        _insert_exam_note(admission, OLDEST, "Laudo antigo que nao deve aparecer")
        _insert_exam_note(admission, RECENT, newest)
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[RADIOLOGIST_KEY]

        assert entry["ref"] == newest[:20]

    def test_the_summary_line_is_capped_at_twenty_characters(
        self, client, analyst_headers, admission
    ):
        """A full report would not fit the collapsed row."""
        long_text = "A" * 500
        _insert_exam_note(admission, RECENT, long_text)
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[RADIOLOGIST_KEY]

        assert entry["ref"] == "A" * 20

    def test_a_short_report_is_not_padded(self, client, analyst_headers, admission):
        """Shorter than the cap means the whole text is the preview."""
        _insert_exam_note(admission, RECENT, "Normal")
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[RADIOLOGIST_KEY]

        assert entry["ref"] == "Normal"

    def test_the_entry_date_is_the_oldest_report_in_the_group(
        self, client, analyst_headers, admission
    ):
        """Pins today's behaviour, which is not what the field name suggests.

        The grouping loop reassigns ``date`` on every note it folds in, and the
        notes arrive newest-first, so the value left standing belongs to the
        *oldest* report — while ``ref`` on the same entry comes from the newest.
        An entry can therefore read "2024-01-01" next to a preview written
        months later. It is asserted rather than fixed because the front end
        sorts on this field today.
        """
        _insert_exam_note(admission, RECENT, "Laudo recente")
        _insert_exam_note(admission, OLDEST, "Laudo antigo")
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[RADIOLOGIST_KEY]

        assert entry["date"] == OLDEST.isoformat()

    def test_a_single_report_dates_the_entry_by_itself(
        self, client, analyst_headers, admission
    ):
        """With one note there is no disagreement between ``date`` and ``ref``."""
        _insert_exam_note(admission, RECENT, "Laudo unico")
        session_commit()

        entry = _get_exams(client, analyst_headers, admission)[RADIOLOGIST_KEY]

        assert entry["date"] == RECENT.isoformat()


class TestAcrossAdmissions:
    """A textual exam stays relevant after discharge, so the lookup spans stays."""

    @pytest.fixture
    def patient_with_six_admissions(self):
        """One patient admitted six times, each stay carrying one exam note.

        ``_get_textual_exams`` takes the patient's five most recent admissions by
        admission date, so the oldest stay of six is the one that must fall out.
        The notes are all recent enough to clear the 90-day window: it is the
        admission limit being tested here, not the date filter.
        """
        id_patient = _next_patient()
        stays = []

        for position in range(6):
            number = _next_admission()
            # admitted oldest-first, so position 0 is the stay that drops out
            _insert_admission(
                admission=number,
                id_patient=id_patient,
                admitted=NOW - timedelta(days=200 - position),
            )
            _insert_exam_note(
                number,
                RECENT - timedelta(minutes=position),
                f"Laudo da estadia {position}",
            )
            stays.append(number)

        session_commit()

        return stays

    def test_a_note_from_an_earlier_stay_is_served(self, client, analyst_headers):
        """Opening the current stay still shows the report filed during the last one."""
        id_patient = _next_patient()
        previous = _next_admission()
        current = _next_admission()
        _insert_admission(previous, id_patient, NOW - timedelta(days=60))
        _insert_admission(current, id_patient, NOW - timedelta(days=2))
        _insert_exam_note(previous, OLDER, "Laudo da internacao anterior")
        _insert_exam_note(current, RECENT, "Laudo da internacao atual")
        session_commit()

        entry = _get_exams(client, analyst_headers, current)[RADIOLOGIST_KEY]

        assert [h["value"] for h in entry["history"]] == [
            "Laudo da internacao atual",
            "Laudo da internacao anterior",
        ]

    def test_another_patients_notes_are_never_mixed_in(self, client, analyst_headers):
        """Two patients in the same hospital must not see each other's reports."""
        mine = _next_admission()
        theirs = _next_admission()
        _insert_admission(mine, _next_patient(), NOW - timedelta(days=2))
        _insert_admission(theirs, _next_patient(), NOW - timedelta(days=2))
        _insert_exam_note(mine, RECENT, "Laudo do meu paciente")
        _insert_exam_note(theirs, RECENT, "Laudo de outro paciente")
        session_commit()

        entry = _get_exams(client, analyst_headers, mine)[RADIOLOGIST_KEY]

        assert [h["value"] for h in entry["history"]] == ["Laudo do meu paciente"]

    def test_only_the_five_most_recent_stays_are_read(
        self, client, analyst_headers, patient_with_six_admissions
    ):
        """The sixth stay back drops off, keeping the panel from growing forever."""
        stays = patient_with_six_admissions
        entry = _get_exams(client, analyst_headers, stays[-1])[RADIOLOGIST_KEY]

        assert "Laudo da estadia 0" not in [h["value"] for h in entry["history"]]

    def test_the_five_kept_stays_are_all_served(
        self, client, analyst_headers, patient_with_six_admissions
    ):
        """Everything inside the limit is shown, not just the current stay."""
        stays = patient_with_six_admissions
        entry = _get_exams(client, analyst_headers, stays[-1])[RADIOLOGIST_KEY]

        assert sorted(h["value"] for h in entry["history"]) == [
            f"Laudo da estadia {position}" for position in range(1, 6)
        ]

    def test_the_admission_being_viewed_is_always_read(self, client, analyst_headers):
        """The current stay counts even when it is not among the five most recent.

        The admission under the cursor is added to the lookup before the
        patient's recent stays are, so a back-dated admission still shows its own
        reports instead of silently serving none.
        """
        id_patient = _next_patient()
        viewed = _next_admission()
        _insert_admission(viewed, id_patient, NOW - timedelta(days=500))
        _insert_exam_note(viewed, RECENT, "Laudo da internacao antiga")

        for position in range(5):
            number = _next_admission()
            _insert_admission(number, id_patient, NOW - timedelta(days=position + 1))

        session_commit()

        entry = _get_exams(client, analyst_headers, viewed)[RADIOLOGIST_KEY]

        assert [h["value"] for h in entry["history"]] == ["Laudo da internacao antiga"]


# A numeric exam type configured for the test segment, so a textual exam can be
# seen arriving in the same payload as an ordinary result. Kept clear of the
# types test_exams.py reserves for its creatinina fixtures.
NUMERIC_TYPE = "zzttgo"
NUMERIC_EXAM_ID = 910001


def _clean_numeric_exam():
    """Drop the configured numeric exam type and its result."""
    session.execute(
        text("DELETE FROM demo.exame WHERE fkexame = :id"), {"id": NUMERIC_EXAM_ID}
    )
    session.execute(
        text(
            "DELETE FROM demo.segmentoexame WHERE idsegmento = :seg AND tpexame = :tp"
        ),
        {"seg": SEGMENT, "tp": NUMERIC_TYPE},
    )
    session_commit()


class TestServedAlongsideNumericExams:
    """Textual exams share the payload with the numeric ones, under the same keys."""

    @pytest.fixture
    def numeric_exam(self, admission):
        """One configured numeric exam type with a result on the test admission."""
        # a previous run killed before teardown would leave these behind and the
        # inserts below would then collide on the primary key
        _clean_numeric_exam()

        session.execute(
            text(
                "INSERT INTO demo.segmentoexame "
                "(idsegmento, tpexame, abrev, nome, min, max, referencia, posicao, "
                "ativo, update_by) "
                "VALUES (:seg, :tp, 'TGO', 'TGO', 0, 50, '', 1, true, 1)"
            ),
            {"seg": SEGMENT, "tp": NUMERIC_TYPE},
        )
        session.execute(
            text(
                "INSERT INTO demo.exame "
                "(fkexame, fkpessoa, nratendimento, dtexame, tpexame, resultado, unidade) "
                "VALUES (:id, :patient, :admission, :date, :tp, 42, 'U/L')"
            ),
            {
                "id": NUMERIC_EXAM_ID,
                "patient": _patient_of[admission],
                "admission": admission,
                "date": RECENT,
                "tp": NUMERIC_TYPE,
            },
        )
        session_commit()

        yield admission

        _clean_numeric_exam()

    def test_both_kinds_arrive_in_one_payload(
        self, client, analyst_headers, numeric_exam
    ):
        """The front end draws a single list, so the service merges before answering."""
        _insert_exam_note(numeric_exam, RECENT, "Laudo de imagem")
        session_commit()

        data = _get_exams(client, analyst_headers, numeric_exam)

        assert NUMERIC_TYPE in data
        assert RADIOLOGIST_KEY in data

    def test_the_numeric_exam_is_not_flagged_as_textual(
        self, client, analyst_headers, numeric_exam
    ):
        """``text`` is what tells the two kinds apart once they are merged."""
        _insert_exam_note(numeric_exam, RECENT, "Laudo de imagem")
        session_commit()

        data = _get_exams(client, analyst_headers, numeric_exam)

        assert data[NUMERIC_TYPE].get("text") is not True
        assert data[RADIOLOGIST_KEY]["text"] is True

    def test_a_numeric_exam_is_served_without_any_textual_one(
        self, client, analyst_headers, numeric_exam
    ):
        """The merge must not depend on there being textual exams to merge in."""
        data = _get_exams(client, analyst_headers, numeric_exam)

        assert list(data.keys()) == [NUMERIC_TYPE]


class TestAccess:
    """Who may read the exam panel."""

    def test_an_unauthenticated_request_is_refused(self, client, admission):
        """The panel carries patient data, so it is never anonymous."""
        response = client.get(f"/exams/{admission}?idSegment={SEGMENT}")

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_a_role_without_read_prescription_is_refused(
        self, client, user_manager_headers, admission
    ):
        """Managing users does not grant a look at someone's reports."""
        _insert_exam_note(admission, RECENT, "Laudo de imagem")
        session_commit()

        response = client.get(
            f"/exams/{admission}?idSegment={SEGMENT}", headers=user_manager_headers
        )

        assert response.status_code == status.HTTP_401_UNAUTHORIZED

    def test_an_unknown_admission_is_rejected(self, client, analyst_headers):
        """A number that belongs to no admission is a bad request, not an empty panel."""
        response = client.get(
            f"/exams/999999999?idSegment={SEGMENT}", headers=analyst_headers
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
