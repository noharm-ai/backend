"""Test: protocol AI service (generated-trigger validation + review sanitization)"""

import pytest

from exception.validation_error import ValidationError
from services.protocol_ai_service import _assert_valid_trigger, _sanitize_review


def test_valid_trigger_passes():
    _assert_valid_trigger(
        trigger="{{v1}} and not ({{v2}} or {{v1}})", variable_names=["v1", "v2"]
    )


def test_unknown_variable_is_rejected():
    with pytest.raises(ValidationError):
        _assert_valid_trigger(
            trigger="{{v1}} and {{ghost}}", variable_names=["v1"]
        )


def test_unbalanced_parentheses_are_rejected():
    with pytest.raises(ValidationError):
        _assert_valid_trigger(
            trigger="({{v1}} and {{v2}}", variable_names=["v1", "v2"]
        )


def test_disallowed_tokens_are_rejected():
    with pytest.raises(ValidationError):
        _assert_valid_trigger(
            trigger="__import__('os').system('id')", variable_names=["v1"]
        )


def test_sanitize_review_whitelists_fields():
    parsed = {
        "verdict": "weird",
        "summary": "x" * 1000,
        "findings": [
            {"severity": "warning", "message": "a"},
            {"severity": "hallucinated", "message": "b"},
            {"severity": "error", "message": ""},
            "not a dict",
        ],
    }

    result = _sanitize_review(parsed)

    assert result["verdict"] == "attention"
    assert len(result["summary"]) == 600
    assert result["findings"] == [
        {"severity": "warning", "message": "a"},
        {"severity": "info", "message": "b"},
    ]


def test_sanitize_review_keeps_ok_verdict():
    result = _sanitize_review(
        {"verdict": "ok", "summary": "tudo certo", "findings": []}
    )

    assert result == {"verdict": "ok", "summary": "tudo certo", "findings": []}


def test_sanitize_review_rejects_non_dict():
    with pytest.raises(ValidationError):
        _sanitize_review(["not", "a", "dict"])
