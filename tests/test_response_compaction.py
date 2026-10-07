import pytest

from mcp_hwc.core.response_compaction import (
    DEFAULT_MAX_ITEMS,
    compact_response,
    slim_call_result,
)


def test_compact_strips_none_and_empty_but_keeps_zero_and_false() -> None:
    value = {"a": None, "b": "", "c": [], "d": {}, "e": 0, "f": False, "g": "x"}

    compacted, truncations = compact_response(value)

    assert compacted == {"e": 0, "f": False, "g": "x"}
    assert truncations == []


def test_compact_strips_nested_empties_recursively() -> None:
    compacted, _ = compact_response({"outer": {"inner": {"gone": None}}, "keep": 1})

    assert compacted == {"keep": 1}


def test_compact_caps_lists_and_reports_truncation() -> None:
    value = {"servers": [{"id": str(i)} for i in range(50)]}

    compacted, truncations = compact_response(value, max_items=20)

    assert len(compacted["servers"]) == 20
    assert truncations == [{"path": "servers", "total": 50, "shown": 20}]


def test_compact_reports_nested_list_path() -> None:
    value = {"items": [{"tags": list(range(5))}]}

    compacted, truncations = compact_response(value, max_items=2)

    assert compacted["items"][0]["tags"] == [0, 1]
    assert truncations == [{"path": "items[].tags", "total": 5, "shown": 2}]


def test_compact_max_items_zero_means_unlimited() -> None:
    compacted, truncations = compact_response({"x": list(range(100))}, max_items=0)

    assert len(compacted["x"]) == 100
    assert truncations == []


def test_compact_rejects_negative_max_items() -> None:
    with pytest.raises(ValueError, match="max_items"):
        compact_response({}, max_items=-1)


def test_compact_keeps_list_positions_when_item_becomes_empty() -> None:
    compacted, _ = compact_response({"x": [{"a": None}, {"a": 1}]})

    assert compacted["x"] == [{}, {"a": 1}]


def _full_result() -> dict[str, object]:
    return {
        "service": "vpc",
        "display_name": "VPC",
        "implementation": "vpc",
        "sdk_package_root": "huaweicloudsdkvpc",
        "api_version": "v2",
        "available_api_versions": ["v2"],
        "operation": "list_vpcs",
        "credential_scope": "basic",
        "region": "ap-southeast-1",
        "endpoint": "https://vpc.example.com",
        "response": {"vpcs": [{"id": "1", "desc": None}]},
    }


def test_slim_drops_verbose_envelope_keys() -> None:
    slim = slim_call_result(_full_result())

    assert slim == {
        "service": "vpc",
        "operation": "list_vpcs",
        "region": "ap-southeast-1",
        "response": {"vpcs": [{"id": "1"}]},
    }


def test_slim_verbose_returns_result_unchanged() -> None:
    full = _full_result()

    assert slim_call_result(full, verbose=True) == full


def test_slim_adds_truncated_hint_with_list_paths() -> None:
    result = _full_result()
    result["response"] = {"vpcs": [{"id": str(i)} for i in range(DEFAULT_MAX_ITEMS + 5)]}

    slim = slim_call_result(result)

    assert len(slim["response"]["vpcs"]) == DEFAULT_MAX_ITEMS
    assert slim["_truncated"]["lists"] == [
        {"path": "vpcs", "total": DEFAULT_MAX_ITEMS + 5, "shown": DEFAULT_MAX_ITEMS}
    ]
    assert "fields" in slim["_truncated"]["hint"]


def test_slim_passes_non_dict_through() -> None:
    assert slim_call_result("raw") == "raw"
