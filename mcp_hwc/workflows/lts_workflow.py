from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
import re

from mcp_hwc.cloud_services.compute import extract_first_string, select_named_resource
from mcp_hwc.core.errors import HelperToolError
from mcp_hwc.core.sdk_service import HuaweiCloudSdkService


def normalize_time_ms(
    value: str | int | None,
    *,
    default: datetime,
) -> str:
    if value is None:
        resolved = default
    elif isinstance(value, int):
        if value > 10**12:
            return str(value)
        return str(value * 1000)
    else:
        text = value.strip()
        if not text:
            resolved = default
        elif text.isdigit():
            number = int(text)
            return str(number if number > 10**12 else number * 1000)
        else:
            try:
                resolved = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    "Time values must be epoch seconds, epoch milliseconds, or ISO-8601 strings"
                ) from exc

    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=timezone.utc)
    return str(int(resolved.timestamp() * 1000))


def resolve_lts_log_group(
    service: HuaweiCloudSdkService,
    *,
    log_group_id: str | None,
    log_group_name: str | None,
) -> dict[str, str | None]:
    if log_group_id:
        groups_response = service.call_operation("list_log_groups")
        groups = groups_response["response"].get("log_groups") or []
        for item in groups:
            if not isinstance(item, dict):
                continue
            if extract_first_string(item, "log_group_id", "id") == log_group_id:
                return {
                    "id": log_group_id,
                    "name": extract_first_string(item, "log_group_name", "name"),
                }
        return {"id": log_group_id, "name": log_group_name}

    if not log_group_name:
        raise ValueError("Provide log_group_id or log_group_name")

    groups_response = service.call_operation("list_log_groups")
    groups = [
        item
        for item in groups_response["response"].get("log_groups") or []
        if isinstance(item, dict)
    ]
    selected = select_named_resource(
        groups,
        name=log_group_name,
        id_keys=("log_group_id", "id"),
        name_keys=("log_group_name", "name"),
        label="log group",
    )
    return {
        "id": extract_first_string(selected, "log_group_id", "id"),
        "name": extract_first_string(selected, "log_group_name", "name"),
    }


def resolve_lts_log_stream(
    service: HuaweiCloudSdkService,
    *,
    log_group_id: str,
    log_group_name: str | None,
    log_stream_id: str | None,
    log_stream_name: str | None,
) -> dict[str, str | None]:
    if log_stream_id:
        stream_name = log_stream_name
        if stream_name is None:
            streams_response = service.call_operation(
                "list_log_stream",
                {"log_group_id": log_group_id},
            )
            for item in streams_response["response"].get("log_streams") or []:
                if not isinstance(item, dict):
                    continue
                if extract_first_string(item, "log_stream_id", "id") == log_stream_id:
                    stream_name = extract_first_string(item, "log_stream_name", "name")
                    break
        return {"id": log_stream_id, "name": stream_name}

    if log_group_name:
        params: dict[str, object] = {"log_group_name": log_group_name}
        if log_stream_name:
            params["log_stream_name"] = log_stream_name
        response = service.call_operation("list_log_streams", params)
    else:
        response = service.call_operation(
            "list_log_stream",
            {"log_group_id": log_group_id},
        )

    streams = [
        item
        for item in response["response"].get("log_streams") or []
        if isinstance(item, dict)
    ]
    selected = select_named_resource(
        streams,
        name=log_stream_name,
        id_keys=("log_stream_id", "id"),
        name_keys=("log_stream_name", "name"),
        label="log stream",
    )
    return {
        "id": extract_first_string(selected, "log_stream_id", "id"),
        "name": extract_first_string(selected, "log_stream_name", "name"),
    }


def filter_lts_logs(
    items: list[object],
    *,
    contains_text: str | None,
    regex: str | None,
) -> list[object]:
    compiled_pattern = None
    if regex:
        try:
            compiled_pattern = re.compile(regex, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid regex: {exc}") from exc

    expected_text = contains_text.casefold() if contains_text else None
    filtered = []
    for item in items:
        haystack = json.dumps(item, ensure_ascii=True, sort_keys=True, default=str)
        if expected_text and expected_text not in haystack.casefold():
            continue
        if compiled_pattern and compiled_pattern.search(haystack) is None:
            continue
        filtered.append(item)
    return filtered


def query_lts_logs(
    service: HuaweiCloudSdkService,
    *,
    log_group_id: str | None = None,
    log_group_name: str | None = None,
    log_stream_id: str | None = None,
    log_stream_name: str | None = None,
    start_time: str | int | None = None,
    end_time: str | int | None = None,
    keywords: str | None = None,
    labels: dict[str, str] | None = None,
    query: str | None = None,
    analysis_query: bool = False,
    sql_expression: str | None = None,
    limit: int = 100,
    is_desc: bool = True,
    highlight: bool = False,
    original_content: bool = False,
    contains_text: str | None = None,
    regex: str | None = None,
) -> dict[str, object]:
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if analysis_query and not query:
        raise ValueError("query is required when analysis_query is true")

    now = datetime.now(timezone.utc)
    start_time_ms = normalize_time_ms(
        start_time,
        default=now - timedelta(hours=1),
    )
    end_time_ms = normalize_time_ms(end_time, default=now)

    log_group = resolve_lts_log_group(
        service,
        log_group_id=log_group_id,
        log_group_name=log_group_name,
    )
    if log_group["id"] is None:
        raise HelperToolError("Could not resolve an LTS log group ID")

    log_stream = resolve_lts_log_stream(
        service,
        log_group_id=log_group["id"],
        log_group_name=log_group["name"],
        log_stream_id=log_stream_id,
        log_stream_name=log_stream_name,
    )
    if log_stream["id"] is None:
        raise HelperToolError("Could not resolve an LTS log stream ID")

    if sql_expression:
        result = service.call_operation(
            "list_query_structured_logs",
            {
                "log_group_id": log_group["id"],
                "log_stream_id": log_stream["id"],
                "body": {
                    "start_time": start_time_ms,
                    "end_time": end_time_ms,
                    "sql_expression": sql_expression,
                    "original_content": original_content,
                },
            },
        )
    else:
        body: dict[str, object] = {
            "start_time": start_time_ms,
            "end_time": end_time_ms,
            "limit": limit,
            "is_desc": is_desc,
            "highlight": highlight,
        }
        if labels:
            body["labels"] = labels
        if keywords:
            body["keywords"] = keywords
        if query:
            body["query"] = query
            body["is_analysis_query"] = analysis_query

        result = service.call_operation(
            "list_logs",
            {
                "log_group_id": log_group["id"],
                "log_stream_id": log_stream["id"],
                "body": body,
            },
        )

    response = result["response"]
    raw_logs = response.get("struct_logs")
    if raw_logs is None:
        raw_logs = response.get("logs")
    if raw_logs is None:
        raw_logs = response.get("analysis_logs")
    raw_logs = raw_logs or []
    filtered_logs = filter_lts_logs(
        raw_logs,
        contains_text=contains_text,
        regex=regex,
    )

    result["log_group_id"] = log_group["id"]
    result["log_group_name"] = log_group["name"]
    result["log_stream_id"] = log_stream["id"]
    result["log_stream_name"] = log_stream["name"]
    result["query_window"] = {
        "start_time": start_time_ms,
        "end_time": end_time_ms,
    }
    result["raw_count"] = len(raw_logs)
    result["matched_count"] = len(filtered_logs)
    result["logs"] = filtered_logs
    return result
