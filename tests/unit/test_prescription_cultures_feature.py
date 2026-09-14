"""Unit tests for the CULTURE feature gate (services.prescription_view_service).

The culture card depends on the antibiogram integration, so it is enabled per
schema. Without the feature the summary lookup must not happen at all: it is a
DynamoDB query on every prescription load, and the card that reads it is not
offered.
"""

from unittest.mock import MagicMock, patch

from flask import g

from mobile import app
from models.enums import FeatureEnum
from services.prescription_view_service import _get_cultures

SUMMARY = [{"drug": "OXACILINA", "items": []}]


def _patient():
    patient = MagicMock()
    patient.idPatient = 1
    return patient


def _user():
    user = MagicMock()
    user.schema = "demo"
    return user


def _call_with_features(features: list):
    """Run _get_cultures with the tenant feature list cached on ``g``."""
    with app.test_request_context():
        g.features = features

        with patch(
            "services.prescription_view_service.culture_service"
        ) as culture_service:
            culture_service.get_culture_summary.return_value = SUMMARY

            result = _get_cultures(patient=_patient(), user_context=_user())

            return result, culture_service.get_culture_summary


def test_summary_is_read_with_the_feature():
    result, get_culture_summary = _call_with_features([FeatureEnum.CULTURE.value])

    assert result == SUMMARY
    get_culture_summary.assert_called_once_with(schema="demo", id_patient=1)


def test_summary_is_not_even_looked_up_without_the_feature():
    """The empty list is what the view and the card endpoint already handle for
    a patient with no culture, so nothing downstream has to know about it."""
    result, get_culture_summary = _call_with_features([FeatureEnum.CONCILIATION.value])

    assert result == []
    get_culture_summary.assert_not_called()
