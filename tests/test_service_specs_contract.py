import importlib

import pytest

from mcp_hwc.core.config import CloudApiConfig
from mcp_hwc.core.sdk_service import SERVICE_SPECS, HuaweiCloudSdkService

_VERSION_CASES = [
    (name, version) for name, spec in SERVICE_SPECS.items() for version in spec.versions
]


def _config() -> CloudApiConfig:
    return CloudApiConfig(
        access_key_id="test-ak",
        secret_access_key="test-sk",
        project_id="project-123",
        region="ap-southeast-1",
    )


@pytest.mark.parametrize(
    ("name", "version"), _VERSION_CASES, ids=[f"{n}-{v}" for n, v in _VERSION_CASES]
)
def test_spec_version_points_at_installed_sdk(name: str, version: str) -> None:
    vspec = SERVICE_SPECS[name].versions[version]

    client_module = importlib.import_module(vspec.client_module)
    assert hasattr(client_module, vspec.client_class_name)
    importlib.import_module(vspec.model_package)
    if vspec.region_module:
        region_module = importlib.import_module(vspec.region_module)
        assert hasattr(region_module, vspec.region_class_name)


def test_service_names_and_aliases_do_not_collide() -> None:
    owner: dict[str, str] = {}
    collisions = []
    for name, spec in SERVICE_SPECS.items():
        for key in (name, *spec.aliases):
            previous = owner.setdefault(key.lower(), name)
            if previous != name:
                collisions.append(f"{key!r}: {previous} vs {name}")
    assert not collisions, collisions


def _balanced(text: str) -> bool:
    depth = 0
    for char in text:
        depth += (char == "{") - (char == "}")
        if depth < 0:
            return False
    return depth == 0


@pytest.mark.parametrize("name", sorted(SERVICE_SPECS))
def test_every_operation_describes_with_balanced_dense_signature(name: str) -> None:
    service = HuaweiCloudSdkService(_config(), name)
    failures = []
    for operation in service._operations():
        try:
            signature = service.describe_operation(operation)["dense_signature"]
        except Exception as exc:  # noqa: BLE001 - collect every failure for one report
            failures.append(f"{operation}: {type(exc).__name__}: {exc}")
            continue
        if not signature.strip() or not _balanced(signature):
            failures.append(f"{operation}: malformed dense_signature")
    assert not failures, f"{len(failures)} failing operations, first 10: {failures[:10]}"


@pytest.mark.parametrize(
    ("name", "region", "expected"),
    [
        # Global services: one region-free host regardless of region.
        ("cdn", "la-south-2", "https://cdn.myhuaweicloud.com"),
        ("organizations", "sa-brazil-1", "https://organizations.myhuaweicloud.com"),
        ("cc", "la-south-2", "https://cc.myhuaweicloud.com"),
        ("ga", "la-south-2", "https://ga.myhuaweicloud.com"),
        ("geip", "la-south-2", "https://eip.myhuaweicloud.com"),
        ("aad", "la-south-2", "https://aad.myhuaweicloud.com"),
        ("ucs", "la-south-2", "https://ucs.myhuaweicloud.com"),
        # Config/RMS is global even though the SDK lists a few sovereign regional hosts.
        ("config", "la-south-2", "https://rms.myhuaweicloud.com"),
        # Static SDK entries still win (EU sovereign cloud).
        ("cdn", "eu-west-101", "https://cdn.myhuaweicloud.eu"),
        # Regional services are unaffected.
        ("ecs", "la-south-2", "https://ecs.la-south-2.myhuaweicloud.com"),
    ],
)
def test_endpoint_resolution_for_global_and_regional_services(
    name: str, region: str, expected: str
) -> None:
    assert SERVICE_SPECS[name].resolve().endpoint_for_region(region) == expected


def test_global_endpoint_prefers_intl_host_outside_china() -> None:
    assert SERVICE_SPECS["tms"].resolve().endpoint_for_region("la-south-2") == (
        "https://tms-intl.myhuaweicloud.com"
    )


def test_sovereign_only_global_host_keeps_regional_template() -> None:
    # rfs lists aos.myhuaweicloud.eu for the EU cloud; other regions are regional.
    assert SERVICE_SPECS["rfs"].resolve().endpoint_for_region("la-south-2") == (
        "https://rfs.la-south-2.myhuaweicloud.com"
    )


@pytest.mark.parametrize(
    ("name", "version"), _VERSION_CASES, ids=[f"{n}-{v}" for n, v in _VERSION_CASES]
)
def test_credential_scope_matches_sdk_declaration(name: str, version: str) -> None:
    client_class = SERVICE_SPECS[name].versions[version].client_class
    declared = client_class.new_builder()._credential_type
    sdk_scope = "global" if "GlobalCredentials" in (declared or []) else "basic"
    assert SERVICE_SPECS[name].credential_scope == sdk_scope


# China-only services: their SDKs list only a .cn host or a single cn-* host.
_CHINA_ONLY_SERVICES = {"koomessage", "oroas"}


@pytest.mark.parametrize("name", sorted(set(SERVICE_SPECS) - _CHINA_ONLY_SERVICES))
def test_every_service_resolves_an_endpoint_for_latam_regions(name: str) -> None:
    spec = SERVICE_SPECS[name].resolve()
    for region in ("la-south-2", "sa-brazil-1"):
        assert spec.endpoint_for_region(region).startswith("https://")


@pytest.mark.parametrize("name", sorted(_CHINA_ONLY_SERVICES))
def test_china_only_service_explains_missing_region(name: str) -> None:
    with pytest.raises(ValueError, match="the SDK only lists: cn-"):
        SERVICE_SPECS[name].resolve().endpoint_for_region("la-south-2")
