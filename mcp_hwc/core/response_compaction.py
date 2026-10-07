"""Shrink SDK call results at the MCP tool boundary.

Applied only where results are handed to the model. Internal workflows call
`HuaweiCloudSdkService.call_operation` directly and need the full result
(pagination, `.get("servers")`), so nothing here may run inside that method.
"""

from __future__ import annotations

from typing import Any

DEFAULT_MAX_ITEMS = 20

_VERBOSE_ONLY_KEYS = frozenset(
    {
        "display_name",
        "implementation",
        "sdk_package_root",
        "api_version",
        "available_api_versions",
        "credential_scope",
        "endpoint",
    }
)

_TRUNCATION_HINT = (
    "Lists were cut to max_items. Narrow with `fields`, add filters/limit/offset in "
    "`parameters`, or pass max_items=0 for everything."
)


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def compact_response(
    value: Any, max_items: int = DEFAULT_MAX_ITEMS
) -> tuple[Any, list[dict[str, object]]]:
    """Strip null/empty values and cap lists. `max_items=0` disables the cap."""
    if max_items < 0:
        raise ValueError("max_items must be >= 0")
    truncations: list[dict[str, object]] = []
    return _compact(value, max_items, "", truncations), truncations


def _compact(value: Any, max_items: int, path: str, truncations: list[dict[str, object]]) -> Any:
    if isinstance(value, dict):
        compacted: dict[str, Any] = {}
        for key, item in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            child = _compact(item, max_items, child_path, truncations)
            if not _is_empty(child):
                compacted[key] = child
        return compacted
    if isinstance(value, list):
        shown = value
        if max_items and len(value) > max_items:
            shown = value[:max_items]
            truncations.append({"path": path or "$", "total": len(value), "shown": max_items})
        return [_compact(item, max_items, f"{path}[]", truncations) for item in shown]
    return value


def slim_call_result(
    result: Any, *, verbose: bool = False, max_items: int = DEFAULT_MAX_ITEMS
) -> Any:
    """Drop envelope metadata and compact `response`. `verbose=True` returns it untouched."""
    if verbose or not isinstance(result, dict):
        return result
    slim = {key: value for key, value in result.items() if key not in _VERBOSE_ONLY_KEYS}
    if "response" in slim:
        response, truncations = compact_response(slim["response"], max_items)
        slim["response"] = response
        if truncations:
            slim["_truncated"] = {"lists": truncations, "hint": _TRUNCATION_HINT}
    return slim
