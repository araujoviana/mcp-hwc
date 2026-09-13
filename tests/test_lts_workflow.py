from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_hwc.workflows.lts_workflow import (
    filter_lts_logs,
    normalize_time_ms,
    query_lts_logs,
    resolve_lts_log_group,
    resolve_lts_log_stream,
)


def test_normalize_time_ms() -> None:
    from datetime import datetime, timezone

    now = datetime(2025, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    # Default
    assert normalize_time_ms(None, default=now) == str(int(now.timestamp() * 1000))
    # Seconds float
    assert normalize_time_ms(1700000000, default=now) == "1700000000000"
    # Milliseconds int
    assert normalize_time_ms(1700000000000, default=now) == "1700000000000"
    # ISO string
    assert normalize_time_ms("2025-01-01T12:00:00Z", default=now) == str(int(now.timestamp() * 1000))


def test_filter_lts_logs() -> None:
    logs = [
        {"content": "Error: connection timeout", "level": "ERROR"},
        {"content": "Info: user logged in", "level": "INFO"},
        {"content": "Warning: high memory", "level": "WARN"},
    ]
    # Contains text
    res = filter_lts_logs(logs, contains_text="timeout", regex=None)
    assert len(res) == 1
    assert res[0]["level"] == "ERROR"

    # Regex
    res = filter_lts_logs(logs, contains_text=None, regex=r"(error|warn)")
    assert len(res) == 2


def test_query_lts_logs_supports_analysis_logs_and_omits_response() -> None:
    mock_service = MagicMock()
    mock_service.call_operation.side_effect = [
        # list_log_groups
        {"response": {"log_groups": [{"log_group_id": "lg-1", "log_group_name": "app-logs"}]}},
        # list_log_stream
        {"response": {"log_streams": [{"log_stream_id": "ls-1", "log_stream_name": "app-stream"}]}},
        # list_logs
        {
            "response": {
                "count": 2,
                "analysisLogs": [
                    {"content": "line 1: query result", "line": 1},
                    {"content": "line 2: query result", "line": 2},
                ],
            }
        },
    ]

    result = query_lts_logs(
        mock_service,
        log_group_name="app-logs",
        log_stream_name="app-stream",
        query="* | select count(*)",
        analysis_query=True,
    )

    assert result["log_group_id"] == "lg-1"
    assert result["log_stream_id"] == "ls-1"
    assert result["raw_count"] == 2
    assert result["matched_count"] == 2
    assert "response" not in result
    assert result["logs"] == [
        {"content": "line 1: query result", "line": 1},
        {"content": "line 2: query result", "line": 2},
    ]
