"""Unit tests for prescription presence repository"""

from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

from repository.prescription_presence_repository import (
    get_active_viewers,
    is_viewer_fresh,
    record_heartbeat,
)


class TestIsViewerFresh:
    """Test the pure freshness check"""

    def test_fresh_within_window(self):
        now = datetime(2026, 1, 1, 12, 5, 0)
        last_seen = datetime(2026, 1, 1, 12, 1, 0).isoformat()
        assert is_viewer_fresh(last_seen, now=now) is True

    def test_stale_past_window(self):
        now = datetime(2026, 1, 1, 12, 10, 0)
        last_seen = datetime(2026, 1, 1, 12, 0, 0).isoformat()
        assert is_viewer_fresh(last_seen, now=now) is False

    def test_exact_boundary_is_fresh(self):
        now = datetime(2026, 1, 1, 12, 5, 0)
        last_seen = datetime(2026, 1, 1, 12, 0, 0).isoformat()
        assert is_viewer_fresh(last_seen, now=now, max_minutes=5) is True

    def test_missing_last_seen_is_stale(self):
        assert is_viewer_fresh(None) is False
        assert is_viewer_fresh("") is False


class TestRecordHeartbeat:
    """Test heartbeat upsert"""

    @patch("repository.prescription_presence_repository.Config")
    @patch("repository.prescription_presence_repository.boto3")
    def test_record_heartbeat_calls_update_item(self, mock_boto3, mock_config):
        mock_config.ENV = "development"
        mock_config.PRESCRIPTION_PRESENCE_TABLE_NAME = "test-table"

        mock_table = MagicMock()
        mock_table.update_item.return_value = {
            "Attributes": {
                "userId": 1,
                "userName": "Dr. Test",
                "startDate": "2026-01-01T12:00:00",
                "lastSeen": "2026-01-01T12:00:00",
            }
        }
        mock_boto3.resource.return_value.Table.return_value = mock_table

        result = record_heartbeat(
            schema="demo", id_prescription=123, user_id=1, user_name="Dr. Test"
        )

        mock_table.update_item.assert_called_once()
        call_kwargs = mock_table.update_item.call_args.kwargs
        assert call_kwargs["Key"] == {"schema_fkprescricao": "demo:123", "userId": 1}
        assert "if_not_exists(startDate, :now)" in call_kwargs["UpdateExpression"]
        assert call_kwargs["ExpressionAttributeValues"][":userName"] == "Dr. Test"
        assert result["userId"] == 1

    @patch("repository.prescription_presence_repository.Config")
    def test_record_heartbeat_short_circuits_in_test_env(self, mock_config):
        mock_config.ENV = "test"

        result = record_heartbeat(
            schema="demo", id_prescription=123, user_id=1, user_name="Dr. Test"
        )

        assert result["userId"] == 1
        assert result["userName"] == "Dr. Test"

    @patch("repository.prescription_presence_repository.Config")
    @patch("repository.prescription_presence_repository.boto3")
    def test_record_heartbeat_degrades_on_error(self, mock_boto3, mock_config):
        mock_config.ENV = "development"
        mock_config.PRESCRIPTION_PRESENCE_TABLE_NAME = "test-table"
        mock_boto3.resource.side_effect = Exception("boom")

        result = record_heartbeat(
            schema="demo", id_prescription=123, user_id=1, user_name="Dr. Test"
        )

        assert result["userId"] == 1
        assert result["userName"] == "Dr. Test"


class TestGetActiveViewers:
    """Test querying and freshness filtering"""

    @patch("repository.prescription_presence_repository.Config")
    @patch("repository.prescription_presence_repository.boto3")
    def test_filters_out_stale_viewers(self, mock_boto3, mock_config):
        mock_config.ENV = "development"
        mock_config.PRESCRIPTION_PRESENCE_TABLE_NAME = "test-table"

        now = datetime.today()
        fresh_seen = now.isoformat()
        stale_seen = (now - timedelta(minutes=30)).isoformat()

        mock_table = MagicMock()
        mock_table.query.return_value = {
            "Items": [
                {"userId": 1, "userName": "Fresh User", "lastSeen": fresh_seen},
                {"userId": 2, "userName": "Stale User", "lastSeen": stale_seen},
            ]
        }
        mock_boto3.resource.return_value.Table.return_value = mock_table

        viewers = get_active_viewers(schema="demo", id_prescription=123)

        mock_table.query.assert_called_once()
        assert len(viewers) == 1
        assert viewers[0]["userId"] == 1

    @patch("repository.prescription_presence_repository.Config")
    def test_returns_empty_in_test_env(self, mock_config):
        mock_config.ENV = "test"

        assert get_active_viewers(schema="demo", id_prescription=123) == []

    @patch("repository.prescription_presence_repository.Config")
    @patch("repository.prescription_presence_repository.boto3")
    def test_degrades_to_empty_list_on_error(self, mock_boto3, mock_config):
        mock_config.ENV = "development"
        mock_config.PRESCRIPTION_PRESENCE_TABLE_NAME = "test-table"
        mock_boto3.resource.side_effect = Exception("boom")

        assert get_active_viewers(schema="demo", id_prescription=123) == []
