from datetime import datetime

from services.prescription_view_service import _build_exams_card


def _make_exam(value, tp_exam_ref=None, date=None):
    return {
        "value": value,
        "alert": False,
        "tp_exam_ref": tp_exam_ref,
        "date": date,
        "name": "Exam",
        "initials": "EX",
        "unit": "",
        "ref": "",
        "min": 0,
        "max": 100,
        "prev": None,
        "delta": None,
        "manual": False,
    }


def _make_exams_json(n, tp_exam_ref=None):
    """Build a list of n exam items all with a real value."""
    return [
        {"key": f"exam_{i}", "value": _make_exam(value=float(i + 1), tp_exam_ref=tp_exam_ref)}
        for i in range(n)
    ]


def test_all_values_present_returns_first_20():
    """25 exams with values → first 20 returned unchanged."""
    exams_json = _make_exams_json(25)
    card = _build_exams_card(exams_json)
    assert len(card) == 20
    assert [item["key"] for item in card] == [f"exam_{i}" for i in range(20)]


def test_null_with_single_fallback_uses_fallback():
    """Exam at position 5 has null value (no date); a fallback with a real date replaces it."""
    exams_json = _make_exams_json(25)
    exams_json[5] = {"key": "exam_5", "value": _make_exam(value=None, tp_exam_ref="ref_abc")}
    exams_json[22] = {"key": "exam_22", "value": _make_exam(value=99.0, tp_exam_ref="ref_abc", date=datetime(2024, 1, 10))}

    card = _build_exams_card(exams_json)
    assert len(card) == 20
    assert card[5]["key"] == "exam_22"
    assert card[5]["value"]["value"] == 99.0


def test_null_with_multiple_fallbacks_picks_most_recent():
    """Three exams share tp_exam_ref with different dates; most recent must be chosen."""
    exams_json = _make_exams_json(10)
    exams_json[3] = {"key": "exam_3", "value": _make_exam(value=None, tp_exam_ref="ref_xyz")}
    exams_json += [
        {"key": "fallback_new", "value": _make_exam(value=10.0, tp_exam_ref="ref_xyz", date=datetime(2024, 6, 1))},
        {"key": "fallback_old", "value": _make_exam(value=20.0, tp_exam_ref="ref_xyz", date=datetime(2023, 1, 1))},
        {"key": "fallback_mid", "value": _make_exam(value=30.0, tp_exam_ref="ref_xyz", date=datetime(2024, 1, 1))},
    ]

    card = _build_exams_card(exams_json)
    assert card[3]["key"] == "fallback_new"
    assert card[3]["value"]["value"] == 10.0


def test_non_null_exam_replaced_by_more_recent_fallback():
    """Current exam has a value and a date, but fallback is more recent → use fallback."""
    exams_json = _make_exams_json(10)
    exams_json[3] = {"key": "exam_3", "value": _make_exam(value=5.0, tp_exam_ref="ref_dates", date=datetime(2023, 1, 1))}
    exams_json.append({"key": "fallback_newer", "value": _make_exam(value=75.0, tp_exam_ref="ref_dates", date=datetime(2024, 6, 1))})

    card = _build_exams_card(exams_json)
    assert card[3]["key"] == "fallback_newer"
    assert card[3]["value"]["value"] == 75.0


def test_non_null_exam_kept_when_fallback_is_older():
    """Current exam has a value and a date; fallback has an older date → keep current."""
    exams_json = _make_exams_json(10)
    exams_json[3] = {"key": "exam_3", "value": _make_exam(value=5.0, tp_exam_ref="ref_dates", date=datetime(2024, 6, 1))}
    exams_json.append({"key": "fallback_older", "value": _make_exam(value=75.0, tp_exam_ref="ref_dates", date=datetime(2023, 1, 1))})

    card = _build_exams_card(exams_json)
    assert card[3]["key"] == "exam_3"
    assert card[3]["value"]["value"] == 5.0


def test_null_with_fallback_no_date_keeps_null_slot():
    """Fallback exists but has no date → no substitution, null slot kept."""
    exams_json = _make_exams_json(10)
    exams_json[3] = {"key": "exam_3", "value": _make_exam(value=None, tp_exam_ref="ref_nodates")}
    exams_json.append({"key": "fallback_no_date", "value": _make_exam(value=50.0, tp_exam_ref="ref_nodates", date=None)})

    card = _build_exams_card(exams_json)
    assert card[3]["key"] == "exam_3"
    assert card[3]["value"]["value"] is None


def test_null_with_no_fallback_keeps_null_slot():
    """Null exam with tp_exam_ref that has no matching non-null exam → kept as-is."""
    exams_json = _make_exams_json(10)
    exams_json[3] = {"key": "exam_3", "value": _make_exam(value=None, tp_exam_ref="ref_orphan")}

    card = _build_exams_card(exams_json)
    assert card[3]["key"] == "exam_3"
    assert card[3]["value"]["value"] is None


def test_null_with_no_tp_exam_ref_keeps_null_slot():
    """Null exam with tp_exam_ref=None → no fallback lookup, kept as-is."""
    exams_json = _make_exams_json(10)
    exams_json[3] = {"key": "exam_3", "value": _make_exam(value=None, tp_exam_ref=None)}

    card = _build_exams_card(exams_json)
    assert card[3]["key"] == "exam_3"
    assert card[3]["value"]["value"] is None
