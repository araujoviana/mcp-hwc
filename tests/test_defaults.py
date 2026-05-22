import pytest

from mcp_hwc.defaults import resolve_service_defaults


def test_resolve_service_defaults_normalizes_region_and_balanced_intent() -> None:
    result = resolve_service_defaults(
        "ecs",
        region="Santiago",
        intent="balanced",
        exposure="public",
    )

    assert result["service"] == "ecs"
    assert result["region"] == "la-south-2"
    assert result["defaults"]["public_access"] is True
    assert result["defaults"]["root_volume"]["size_gb"] >= 60
    assert result["workflow_tool"] == "ecs_create_vm"
    assert result["minimal_tool_input"]["region"] == "la-south-2"


def test_resolve_service_defaults_auto_preserves_ecs_public_access() -> None:
    result = resolve_service_defaults("ecs", exposure="auto")

    assert result["defaults"]["public_access"] is True


def test_resolve_service_defaults_supports_geminidb_alias() -> None:
    result = resolve_service_defaults("GeminiDB")

    assert result["service"] == "gaussdb_nosql"


def test_resolve_service_defaults_rejects_invalid_intent() -> None:
    with pytest.raises(ValueError, match="Unsupported intent"):
        resolve_service_defaults("ecs", intent="tiny")
