"""Unit tests for the CULTURE feature gate (services.prescription_view_service).

The culture card depends on the antibiogram integration, so it is enabled per
schema, or per user (config features) while a schema is being rolled out.
Without the feature on either side the summary lookup must not happen at all:
it is a DynamoDB query on every prescription load, and the card that reads it
is not offered.
"""

from unittest.mock import MagicMock, patch

from flask import g

from mobile import app
from models.enums import FeatureEnum
from services import feature_service
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


def _call_with_features(features: list, user_features: list = None):
    """Run _get_cultures with the tenant feature list cached on ``g``.

    ``user_features`` patches ``has_user_feature`` instead of writing to ``g``:
    it short-circuits to an empty list under ENV=test, so the cached value on
    ``g`` is never read here.
    """
    user_features = user_features or []

    with app.test_request_context():
        g.features = features

        with patch(
            "services.prescription_view_service.culture_service"
        ) as culture_service, patch.object(
            feature_service,
            "has_user_feature",
            side_effect=lambda feature: feature.value in user_features,
        ):
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


def test_summary_is_read_with_the_user_feature():
    """A user can carry the feature while the schema does not: the rollout of a
    schema starts with the pharmacists who asked for the card."""
    result, get_culture_summary = _call_with_features(
        [FeatureEnum.CONCILIATION.value], user_features=[FeatureEnum.CULTURE.value]
    )

    assert result == SUMMARY
    get_culture_summary.assert_called_once_with(schema="demo", id_patient=1)
