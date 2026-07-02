import pytest
from mcp_hwc.core.sdk_service import resolve_service_spec, SERVICE_SPECS

def test_dataarts_studio_registration():
    assert "dataarts_studio" in SERVICE_SPECS
    spec = resolve_service_spec("dataarts_studio")
    assert spec.name == "dataarts_studio"
    assert spec.sdk_package_root == "huaweicloudsdkdataartsstudio"
    assert spec.env_key == "DATAARTSSTUDIO"
    assert "v1" in spec.available_api_versions

def test_dataarts_studio_aliases():
    spec1 = resolve_service_spec("dataarts")
    assert spec1.name == "dataarts_studio"

    spec2 = resolve_service_spec("dayu")
    assert spec2.name == "dataarts_studio"
