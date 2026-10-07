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
