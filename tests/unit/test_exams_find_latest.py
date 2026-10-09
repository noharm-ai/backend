"""Unit tests for ``exams_service.find_latest_exams``.

``find_latest_exams`` builds the exam panel the prescription screen shows. It

1. seeds an empty placeholder for every exam active in the segment, folding the
   exam whose initials are ``creatinina`` into the reserved ``cr`` key;
2. formats the patient's latest result for each of those exams, keeping the most
   recent result when more than one exam type maps to creatinine;
3. derives the renal-function estimates from that creatinine — MDRD,
   Cockcroft-Gault, CKD-EPI and CKD-EPI 2021 for adults, Schwartz 1 and 2 for
   patients up to 17 years old — but only for the estimates the segment has
   configured;
4. copies ``tgo``/``tgp``/``plaquetas`` into the extra keys the alert engine
   reads (``tgo``, ``tgp``, ``plqt``);
5. applies the segment reference (min/max/name/alert) to the derived estimates.

The function only reaches the database through ``exams_repository`` and the
``_get_exams_current_results*`` helpers, so both are patched and the assertions
compare against ``utils.examutils``, which owns the clinical formulas.
``find_latest_exams`` is permission-decorated; ``__wrapped__`` calls the
undecorated function with an explicit patient.
"""

from datetime import date
from types import SimpleNamespace
from unittest import mock

import pytest

from services import exams_service
from utils import examutils

_find_latest_exams = exams_service.find_latest_exams.__wrapped__

SCHEMA = "demo"
ID_SEGMENT = 1

# a creatinine high enough that every formula lands below its alert threshold
CREATININE = 1.4
CREATININE_DATE = "2026-01-10T08:00:00"


def _seg_exam(initials, name=None, min_value=0, max_value=100, tp_exam_ref=None):
    """SegmentExam stand-in: only the reference fields the service reads."""
    return SimpleNamespace(
        initials=initials,
        name=name or initials,
        min=min_value,
        max=max_value,
        ref=f"ref {initials}",
        tp_exam_ref=tp_exam_ref,
    )


def _patient(
    birthdate=date(1980, 5, 20), gender="M", skin_color=None, weight=70, height=170
):
    """Patient stand-in carrying the measurements the formulas need."""
    return SimpleNamespace(
        idPatient=1,
        birthdate=birthdate,
        gender=gender,
        skinColor=skin_color,
        weight=weight,
        height=height,
    )


def _result(value, unit=None, date_iso=CREATININE_DATE, prev=None):
    """One entry of the "current results" dict the repository helpers return."""
    return {"value": value, "unit": unit, "date": date_iso, "prev": prev}


def _run(seg_exams, current_results, patient=None, **kwargs):
    """Call find_latest_exams with the database boundaries patched out."""
    with (
        mock.patch.object(
            exams_service.exams_repository,
            "get_exams_reference",
            return_value=seg_exams,
        ),
        mock.patch.object(
            exams_service,
            "_get_exams_current_results_hybrid",
            return_value=current_results,
        ),
    ):
        return _find_latest_exams(
            patient=patient if patient is not None else _patient(),
            idSegment=ID_SEGMENT,
            schema=SCHEMA,
            **kwargs,
        )


def _renal_seg_exams():
    """A segment configured with creatinine plus every derived estimate."""
    return {
        "creat": _seg_exam("creatinina", name="Creatinina"),
        "cr": _seg_exam("creatinina", name="Creatinina"),
        "mdrd": _seg_exam("MDRD", min_value=50, max_value=120),
        "cg": _seg_exam("CG", min_value=50, max_value=120),
        "ckd": _seg_exam("CKD", min_value=50, max_value=120),
        "ckd21": _seg_exam("CKD 2021", min_value=50, max_value=120),
        "swrtz1": _seg_exam("Schwartz 1", min_value=90, max_value=120),
        "swrtz2": _seg_exam("Schwartz 2", min_value=90, max_value=120),
    }


class TestPlaceholders:
    """Every active segment exam shows up, even with no result for the patient."""

    def test_exam_without_result_is_an_empty_placeholder(self):
        """The panel keeps the slot so the screen can render "sem resultado"."""
        exams = _run(
            {"sodio": _seg_exam("Na", name="Sódio", min_value=135, max_value=145)}, {}
        )

        assert exams["sodio"]["value"] is None
        assert exams["sodio"]["date"] is None
        assert exams["sodio"]["name"] == "Sódio"
        assert exams["sodio"]["min"] == 135
        assert exams["sodio"]["max"] == 145

    def test_creatinina_placeholder_uses_the_reserved_cr_key(self):
        """Creatinine is addressed as "cr" regardless of the hospital's exam code."""
        exams = _run({"creat": _seg_exam("creatinina", name="Creatinina")}, {})

        assert "cr" in exams
        assert exams["cr"]["name"] == "Creatinina"

    def test_result_is_formatted_against_the_segment_reference(self):
        """A result outside the configured range is flagged."""
        exams = _run(
            {"sodio": _seg_exam("Na", name="Sódio", min_value=135, max_value=145)},
            {"sodio": _result(160, unit="mEq/L")},
        )

        assert exams["sodio"]["value"] == 160
        assert exams["sodio"]["unit"] == "mEq/L"
        assert exams["sodio"]["alert"] is True


class TestCreatinineSelection:
    """Which result fills ``cr`` when several exam types map to creatinine."""

    def test_result_fills_the_cr_slot(self):
        """The creatinine result is copied into the reserved key."""
        exams = _run(
            {
                "creat": _seg_exam("creatinina", name="Creatinina"),
                "cr": _seg_exam("creatinina"),
            },
            {"creat": _result(CREATININE, unit="mg/dL")},
        )

        assert exams["cr"]["value"] == CREATININE
        assert exams["cr"]["date"] == CREATININE_DATE

    def test_most_recent_result_wins(self):
        """With two creatinine exams the newer measurement is the one used."""
        seg_exams = {
            "creat": _seg_exam("creatinina", name="Creatinina"),
            "creat2": _seg_exam("creatinina", name="Creatinina (lab externo)"),
            "cr": _seg_exam("creatinina"),
        }
        exams = _run(
            seg_exams,
            {
                "creat": _result(1.0, date_iso="2026-01-01T08:00:00"),
                "creat2": _result(2.0, date_iso="2026-01-09T08:00:00"),
            },
        )

        assert exams["cr"]["value"] == 2.0
        assert exams["cr"]["date"] == "2026-01-09T08:00:00"

    def test_older_result_does_not_replace_a_newer_one(self):
        """Dict order must not decide which creatinine the estimates use."""
        seg_exams = {
            "creat": _seg_exam("creatinina", name="Creatinina"),
            "creat2": _seg_exam("creatinina", name="Creatinina (lab externo)"),
            "cr": _seg_exam("creatinina"),
        }
        exams = _run(
            seg_exams,
            {
                "creat": _result(2.0, date_iso="2026-01-09T08:00:00"),
                "creat2": _result(1.0, date_iso="2026-01-01T08:00:00"),
            },
        )

        assert exams["cr"]["value"] == 2.0
        assert exams["cr"]["date"] == "2026-01-09T08:00:00"


class TestAdultRenalFunction:
    """Estimates derived for patients older than 17."""

    def test_all_configured_estimates_are_derived(self):
        """MDRD, CG, CKD-EPI and CKD-EPI 2021 match the shared formulas."""
        patient = _patient(birthdate=date(1980, 5, 20), gender="M")
        exams = _run(
            _renal_seg_exams(), {"creat": _result(CREATININE)}, patient=patient
        )

        assert (
            exams["mdrd"]["value"]
            == examutils.mdrd_calc(
                CREATININE, patient.birthdate, patient.gender, patient.skinColor
            )["value"]
        )
        assert (
            exams["cg"]["value"]
            == examutils.cg_calc(
                CREATININE, patient.birthdate, patient.gender, patient.weight
            )["value"]
        )
        assert (
            exams["ckd"]["value"]
            == examutils.ckd_calc(
                CREATININE,
                patient.birthdate,
                patient.gender,
                patient.skinColor,
                patient.height,
                patient.weight,
            )["value"]
        )
        assert (
            exams["ckd21"]["value"]
            == examutils.ckd_calc_21(CREATININE, patient.birthdate, patient.gender)[
                "value"
            ]
        )

    def test_schwartz_is_not_derived_for_an_adult(self):
        """The paediatric formulas stay empty placeholders."""
        exams = _run(_renal_seg_exams(), {"creat": _result(CREATININE)})

        assert exams["swrtz1"]["value"] is None
        assert exams["swrtz2"]["value"] is None

    def test_only_configured_estimates_are_derived(self):
        """An estimate the segment does not activate is never added to the panel."""
        seg_exams = {
            "creat": _seg_exam("creatinina", name="Creatinina"),
            "cr": _seg_exam("creatinina"),
            "ckd21": _seg_exam("CKD 2021", min_value=50, max_value=120),
        }
        exams = _run(seg_exams, {"creat": _result(CREATININE)})

        assert exams["ckd21"]["value"] is not None
        assert "mdrd" not in exams
        assert "cg" not in exams
        assert "ckd" not in exams

    def test_overridden_weight_and_height_are_used(self):
        """The weight/height the caller passes win over the patient record."""
        patient = _patient(weight=70, height=170)
        exams = _run(
            _renal_seg_exams(),
            {"creat": _result(CREATININE)},
            patient=patient,
            weight=50,
            height=150,
        )

        assert (
            exams["cg"]["value"]
            == examutils.cg_calc(CREATININE, patient.birthdate, patient.gender, 50)[
                "value"
            ]
        )
        assert (
            exams["ckd"]["value"]
            == examutils.ckd_calc(
                CREATININE,
                patient.birthdate,
                patient.gender,
                patient.skinColor,
                150,
                50,
            )["value"]
        )

    def test_female_patient_uses_the_female_coefficients(self):
        """Gender changes the result, so it must reach the formulas."""
        male = _run(
            _renal_seg_exams(),
            {"creat": _result(CREATININE)},
            patient=_patient(gender="M"),
        )
        female = _run(
            _renal_seg_exams(),
            {"creat": _result(CREATININE)},
            patient=_patient(gender="F"),
        )

        assert female["mdrd"]["value"] != male["mdrd"]["value"]
        assert female["cg"]["value"] != male["cg"]["value"]

    def test_estimates_without_creatinine_stay_empty(self):
        """No creatinine result means no renal function estimate."""
        exams = _run(_renal_seg_exams(), {})

        assert exams["mdrd"]["value"] is None
        assert exams["cg"]["value"] is None
        assert exams["ckd"]["value"] is None


class TestChildRenalFunction:
    """Estimates derived for patients up to 17 years old."""

    def test_schwartz_formulas_are_derived(self):
        """Schwartz 1 and 2 match the shared formulas."""
        patient = _patient(birthdate=date(2020, 3, 1), weight=20, height=110)
        exams = _run(_renal_seg_exams(), {"creat": _result(0.4)}, patient=patient)

        assert (
            exams["swrtz2"]["value"]
            == examutils.schwartz2_calc(0.4, patient.height)["value"]
        )
        assert (
            exams["swrtz1"]["value"]
            == examutils.schwartz1_calc(
                0.4, patient.birthdate, patient.gender, patient.height
            )["value"]
        )

    def test_adult_formulas_are_not_derived(self):
        """MDRD/CG/CKD are not valid for children and stay empty."""
        patient = _patient(birthdate=date(2020, 3, 1), weight=20, height=110)
        exams = _run(_renal_seg_exams(), {"creat": _result(0.4)}, patient=patient)

        assert exams["mdrd"]["value"] is None
        assert exams["cg"]["value"] is None
        assert exams["ckd"]["value"] is None
        assert exams["ckd21"]["value"] is None

    def test_schwartz_uses_the_overridden_height(self):
        """The height the caller passes drives the paediatric estimate."""
        patient = _patient(birthdate=date(2020, 3, 1), weight=20, height=110)
        exams = _run(
            _renal_seg_exams(), {"creat": _result(0.4)}, patient=patient, height=95
        )

        assert exams["swrtz2"]["value"] == examutils.schwartz2_calc(0.4, 95)["value"]


class TestDerivedExamReference:
    """The segment reference is applied to the derived estimates too."""

    def test_reference_fields_come_from_the_segment(self):
        """Name, initials and range of a derived exam are the configured ones."""
        exams = _run(_renal_seg_exams(), {"creat": _result(CREATININE)})

        assert exams["ckd21"]["initials"] == "CKD 2021"
        assert exams["ckd21"]["min"] == 50
        assert exams["ckd21"]["max"] == 120
        assert exams["ckd21"]["ref"] == "ref CKD 2021"

    def test_estimate_below_the_configured_minimum_alerts(self):
        """A low clearance is flagged against the segment range, not the formula's."""
        exams = _run(_renal_seg_exams(), {"creat": _result(6.0)})

        assert exams["ckd21"]["value"] < 50
        assert exams["ckd21"]["alert"] is True

    def test_estimate_without_value_does_not_alert(self):
        """An estimate that could not be computed is not an abnormal result."""
        exams = _run(_renal_seg_exams(), {})

        assert exams["ckd21"]["alert"] is False


class TestExtraExams:
    """``tgo``/``tgp``/``plaquetas`` are copied to the keys the alerts read."""

    @pytest.mark.parametrize(
        ("initials", "extra_key"),
        [("tgo", "tgo"), ("tgp", "tgp"), ("plaquetas", "plqt")],
    )
    def test_extra_key_is_added(self, initials, extra_key):
        """The alert engine looks the exam up by its fixed key."""
        exams = _run(
            {
                "exam1": _seg_exam(
                    initials, name=initials.upper(), min_value=0, max_value=40
                )
            },
            {"exam1": _result(80, unit="U/L")},
        )

        assert exams[extra_key]["value"] == 80
        assert exams[extra_key]["alert"] is True

    def test_other_exams_get_no_extra_key(self):
        """Only the three mapped exams are duplicated."""
        exams = _run({"sodio": _seg_exam("Na", name="Sódio")}, {"sodio": _result(140)})

        assert set(exams) == {"sodio"}


class TestResultSource:
    """Which "current results" helper the read strategy picks."""

    def test_incomplete_read_skips_the_hybrid_helper(self):
        """The prescription recalculation path reads without the hybrid cache."""
        with (
            mock.patch.object(
                exams_service.exams_repository, "get_exams_reference", return_value={}
            ),
            mock.patch.object(
                exams_service, "_get_exams_current_results_hybrid"
            ) as hybrid,
            mock.patch.object(
                exams_service, "_get_exams_current_results", return_value={}
            ) as plain,
        ):
            _find_latest_exams(
                patient=_patient(),
                idSegment=ID_SEGMENT,
                schema=SCHEMA,
                is_complete=False,
                cache=False,
            )

        hybrid.assert_not_called()
        plain.assert_called_once()
        assert plain.call_args.kwargs["cache"] is False
        assert plain.call_args.kwargs["schema"] == SCHEMA
