import pytest

from mcp_hwc.core.defaults import resolve_service_defaults


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


def test_resolve_service_defaults_sfs_has_workflow_tool() -> None:
    result = resolve_service_defaults("sfs", region="sa-brazil-1")
    assert result["workflow_tool"] == "sfs_create_accessible_share"
    assert result["deployment_style"] == "file-storage"


def test_resolve_service_defaults_cce_has_minimal_input() -> None:
    result = resolve_service_defaults("cce", region="la-south-2")
    assert result["minimal_tool_input"]["region"] == "la-south-2"
    assert "public_api" in result["minimal_tool_input"]


def test_resolve_service_defaults_new_services_have_defaults() -> None:
    for service in ["vpc", "eip", "elb", "nat", "dds", "dms", "kms", "dns", "waf", "cdn"]:
        result = resolve_service_defaults(service)
        assert result["deployment_style"], f"{service} missing deployment_style"
        assert "defaults" in result


def test_resolve_service_defaults_exposure_overrides_public_access() -> None:
    assert resolve_service_defaults("elb", exposure="private")["defaults"]["public_access"] is False
    assert resolve_service_defaults("dds", exposure="public")["defaults"]["public_access"] is True
    assert resolve_service_defaults("dms", exposure="auto")["defaults"]["public_access"] is False
