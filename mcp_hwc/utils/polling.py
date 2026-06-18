from __future__ import annotations

from typing import TYPE_CHECKING
import time

from mcp_hwc.core.errors import HelperToolError

if TYPE_CHECKING:
    from mcp_hwc.core.sdk_service import HuaweiCloudSdkService


DEFAULT_POLL_INTERVAL_SECONDS = 60
MIN_POLL_INTERVAL_SECONDS = 60


def parse_path_segments(path: str) -> list[str | int]:
    if not path.strip():
        raise ValueError("response_path cannot be empty")

    segments: list[str | int] = []
    for chunk in path.split("."):
        if not chunk:
            raise ValueError(f"Invalid response_path: {path}")

        cursor = 0
        while cursor < len(chunk):
            if chunk[cursor] == "[":
                end = chunk.find("]", cursor)
                if end == -1:
                    raise ValueError(f"Invalid response_path: {path}")
                index_text = chunk[cursor + 1 : end].strip()
                if not index_text.isdigit():
                    raise ValueError(f"Invalid response_path index: {path}")
                segments.append(int(index_text))
                cursor = end + 1
                continue

            next_bracket = chunk.find("[", cursor)
            token_end = next_bracket if next_bracket != -1 else len(chunk)
            token = chunk[cursor:token_end]
            if not token:
                raise ValueError(f"Invalid response_path: {path}")
            segments.append(token)
            cursor = token_end

    return segments


def extract_path_value(payload: object, path: str) -> object:
    current = payload
    for segment in parse_path_segments(path):
        if isinstance(segment, int):
            if not isinstance(current, list):
                raise HelperToolError(
                    f"response_path segment [{segment}] requires a list value"
                )
            if segment >= len(current):
                raise HelperToolError(
                    f"response_path index [{segment}] is out of range"
                )
            current = current[segment]
            continue

        if not isinstance(current, dict):
            raise HelperToolError(
                f"response_path segment '{segment}' requires an object value"
            )
        if segment not in current:
            raise HelperToolError(f"response_path segment '{segment}' was not found")
        current = current[segment]

    return current


def wait_condition_matches(
    value: object,
    *,
    expected_value: object | None,
    match_mode: str,
) -> bool:
    if match_mode == "truthy":
        return bool(value)
    if match_mode == "equals":
        return value == expected_value
    if match_mode == "contains":
        if isinstance(value, str):
            return isinstance(expected_value, str) and expected_value in value
        if isinstance(value, list):
            return expected_value in value
        if isinstance(value, dict):
            return isinstance(expected_value, str) and expected_value in value
        raise ValueError("contains match_mode only supports string, list, or object values")
    raise ValueError("match_mode must be one of: equals, contains, truthy")


def resolve_poll_interval(interval_seconds: int) -> int:
    if interval_seconds <= 0:
        raise ValueError("interval_seconds must be greater than zero")
    return max(interval_seconds, MIN_POLL_INTERVAL_SECONDS)


def sleep_before_next_poll(deadline: float, interval_seconds: int) -> None:
    remaining_seconds = deadline - time.monotonic()
    if remaining_seconds <= 0:
        return
    time.sleep(min(interval_seconds, remaining_seconds))


def wait_for_service_value(
    service: "HuaweiCloudSdkService",
    *,
    operation: str,
    parameters: dict[str, object] | None,
    response_path: str,
    expected_value: object | None = None,
    match_mode: str = "equals",
    timeout_seconds: int = 1200,
    interval_seconds: int = DEFAULT_POLL_INTERVAL_SECONDS,
) -> dict[str, object]:
    if timeout_seconds <= 0:
        raise ValueError("timeout_seconds must be greater than zero")
    effective_interval = resolve_poll_interval(interval_seconds)
    deadline = time.monotonic() + timeout_seconds
    while True:
        result = service.call_operation(operation, parameters)
        value = extract_path_value(result, response_path)
        if wait_condition_matches(
            value,
            expected_value=expected_value,
            match_mode=match_mode,
        ):
            return result
        if time.monotonic() >= deadline:
            raise HelperToolError(
                f"Timed out waiting for {service._spec.name}.{operation} {response_path}; last value was {value!r}"
            )
        sleep_before_next_poll(deadline, effective_interval)
