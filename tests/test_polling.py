from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcp_hwc.core.errors import HelperToolError
from mcp_hwc.utils.polling import (
    extract_path_value,
    parse_path_segments,
    wait_condition_matches,
    wait_for_service_value,
)


def test_parse_path_segments() -> None:
    assert parse_path_segments("response.status") == ["response", "status"]
    assert parse_path_segments("response.servers[0].id") == ["response", "servers", 0, "id"]
    with pytest.raises(ValueError, match="response_path cannot be empty"):
        parse_path_segments("")


def test_extract_path_value() -> None:
    data = {"response": {"servers": [{"id": "s-1", "name": "vm1"}]}}
    assert extract_path_value(data, "response.servers[0].id") == "s-1"
    assert extract_path_value(data, "response.servers[0].name") == "vm1"


def test_wait_for_service_value_success() -> None:
    mock_service = MagicMock()
    mock_service.call_operation.return_value = {"response": {"status": "SUCCESS"}}

    result = wait_for_service_value(
        mock_service,
        operation="show_job",
        parameters={"job_id": "j-1"},
        response_path="response.status",
        expected_value="SUCCESS",
        timeout_seconds=5,
        interval_seconds=1,
    )
    assert result["response"]["status"] == "SUCCESS"


def test_wait_for_service_value_fails_fast_on_failure_state() -> None:
    mock_service = MagicMock()
    mock_service.call_operation.return_value = {"response": {"status": "FAIL"}}

    with pytest.raises(HelperToolError, match="entered terminal failure state: 'FAIL'"):
        wait_for_service_value(
            mock_service,
            operation="show_job",
            parameters={"job_id": "j-1"},
            response_path="response.status",
            expected_value="SUCCESS",
            timeout_seconds=60,
            interval_seconds=1,
        )


def test_wait_condition_matches_one_of() -> None:
    candidates = ("", "Active", "Synchronized")
    assert wait_condition_matches("", expected_value=candidates, match_mode="one_of")
    assert wait_condition_matches("Synchronized", expected_value=candidates, match_mode="one_of")
    assert not wait_condition_matches("ScalingUp", expected_value=candidates, match_mode="one_of")
    assert not wait_condition_matches(None, expected_value=candidates, match_mode="one_of")
    with pytest.raises(ValueError, match="one_of match_mode requires a sequence"):
        wait_condition_matches("x", expected_value="x", match_mode="one_of")


def test_extract_path_value_missing_ok_returns_none() -> None:
    assert extract_path_value({}, "response.status", missing_ok=True) is None
    assert extract_path_value({"response": None}, "response.status", missing_ok=True) is None
    assert extract_path_value({"response": {}}, "response.status", missing_ok=True) is None
    # default remains strict
    with pytest.raises(HelperToolError):
        extract_path_value({}, "response.status")


def test_wait_for_service_value_one_of_ready_node_pool() -> None:
    mock_service = MagicMock()
    mock_service.call_operation.return_value = {"response": {"status": {"phase": "Synchronized"}}}

    result = wait_for_service_value(
        mock_service,
        operation="show_node_pool",
        parameters={"cluster_id": "c-1", "node_pool_id": "np-1"},
        response_path="response.status.phase",
        expected_value=("", "Active", "Synchronized"),
        match_mode="one_of",
        timeout_seconds=5,
        interval_seconds=1,
    )
    assert result == {"response": {"status": {"phase": "Synchronized"}}}
