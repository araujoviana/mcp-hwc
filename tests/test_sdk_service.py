import pytest

from huaweicloudsdkcore.auth.credentials import GlobalCredentials
from huaweicloudsdkecs.v2.model.create_servers_response import CreateServersResponse
from huaweicloudsdkrds.v3.model.create_instance_response import CreateInstanceResponse

from mcp_hwc.core.config import CloudApiConfig
from mcp_hwc.core.sdk_service import (
    HuaweiCloudSdkService,
    build_sdk_client,
    list_supported_services,
    resolve_service_spec,
    summarize_service_capabilities,
)


def make_config() -> CloudApiConfig:
    return CloudApiConfig(
        access_key_id="test-ak",
        secret_access_key="test-sk",
        project_id="project-123",
        region="ap-southeast-1",
    )


def test_list_operations_filters_and_pages() -> None:
    service = HuaweiCloudSdkService(make_config(), "ecs")

    result = service.list_operations(query="create_server", limit=5, offset=0)

    assert result["service"] == "ecs"
    assert result["returned_count"] <= 5
    assert all("create_server" in operation for operation in result["operations"])


def test_list_operations_supports_vpc_service() -> None:
    service = HuaweiCloudSdkService(make_config(), "vpc")

    result = service.list_operations(query="list_vpc", limit=10, offset=0)

    assert result["service"] == "vpc"
    assert any("list_vpc" in operation for operation in result["operations"])


def test_describe_operation_supports_ims_service() -> None:
    service = HuaweiCloudSdkService(make_config(), "ims")

    result = service.describe_operation("list_images", max_depth=2)

    assert result["service"] == "ims"
    assert result["request_model"] == "ListImagesRequest"


def test_resolve_service_spec_supports_alias_and_api_version() -> None:
    spec = resolve_service_spec("TaurusDB", api_version="v3")

    assert spec.name == "taurusdb"
    assert spec.implementation_name == "gaussdb"
    assert spec.api_version == "v3"


def test_list_supported_services_includes_requested_families() -> None:
    result = list_supported_services(query="modelarts")

    returned_services = {service["service"] for service in result["services"]}
    assert "modelarts_studio" in returned_services


def test_resolve_service_spec_supports_new_networking_family() -> None:
    spec = resolve_service_spec("vpn")

    assert spec.name == "vpn"
    assert spec.api_version == "v5"


def test_resolve_service_spec_supports_cloud_eye_alias() -> None:
    spec = resolve_service_spec("cloud eye")

    assert spec.name == "ces"
    assert spec.api_version == "v3"


def test_resolve_service_spec_supports_vbs_alias() -> None:
    spec = resolve_service_spec("vbs")

    assert spec.name == "cbr"


def test_resolve_service_spec_supports_geminidb_alias() -> None:
    spec = resolve_service_spec("GeminiDB")

    assert spec.name == "gaussdb_nosql"


def test_list_supported_services_includes_codearts_families() -> None:
    result = list_supported_services(query="codearts")

    returned_services = {service["service"] for service in result["services"]}
    assert "codearts_build" in returned_services
    assert "codearts_repo" in returned_services


def test_summarize_service_capabilities_reports_focus_matches() -> None:
    result = summarize_service_capabilities("cce", focus="node pool")

    assert result["service"] == "cce"
    assert result["operation_count"] > 0
    assert result["operation_breakdown"]["create"] > 0
    assert any("node" in entry["token"] for entry in result["top_resource_tokens"])
    assert any("node_pool" in operation for operation in result["focus_matches"])


def test_list_operations_excludes_sdk_helper_methods() -> None:
    service = HuaweiCloudSdkService(make_config(), "cce")

    result = service.list_operations(limit=500)

    assert "add_file_logger" not in result["operations"]
    assert "create_cluster" in result["operations"]


def test_describe_operation_returns_nested_schema() -> None:
    service = HuaweiCloudSdkService(make_config(), "rds")

    result = service.describe_operation("create_instance", max_depth=3)

    assert result["request_model"] == "CreateInstanceRequest"
    fields = result["request_schema"]["fields"]
    body_field = next(field for field in fields if field["name"] == "body")
    nested_fields = body_field["schema"]["fields"]
    assert any(field["name"] == "name" for field in nested_fields)
    assert any(field["name"] == "datastore" for field in nested_fields)
    assert "body" in result["request_template"]


def test_call_operation_builds_nested_ecs_request() -> None:
    class FakeEcsClient:
        def create_servers(self, request):
            assert request.x_client_token == "token-1"
            assert request.body.server.name == "web-01"
            assert request.body.server.count == 2
            assert request.body.server.metadata == {"role": "web"}
            return CreateServersResponse(job_id="job-123")

    service = HuaweiCloudSdkService(
        make_config(),
        "ecs",
        client_factory=lambda config, spec: FakeEcsClient(),
    )

    result = service.call_operation(
        "create_servers",
        {
            "x_client_token": "token-1",
            "body": {
                "server": {
                    "name": "web-01",
                    "count": 2,
                    "metadata": {"role": "web"},
                }
            },
        },
    )

    assert result["service"] == "ecs"
    assert result["response"]["job_id"] == "job-123"


def test_call_operation_accepts_api_field_names() -> None:
    class FakeRdsClient:
        def create_instance(self, request):
            assert request.x_client_token == "token-2"
            assert request.body.name == "db-01"
            assert request.body.datastore.type == "MySQL"
            assert request.body.volume.size == 40
            return CreateInstanceResponse(job_id="job-456")

    service = HuaweiCloudSdkService(
        make_config(),
        "rds",
        client_factory=lambda config, spec: FakeRdsClient(),
    )

    result = service.call_operation(
        "create_instance",
        {
            "X-Client-Token": "token-2",
            "body": {
                "name": "db-01",
                "datastore": {"type": "MySQL", "version": "8.0"},
                "volume": {"type": "CLOUDSSD", "size": 40},
                "region": "ap-southeast-1",
            },
        },
    )

    assert result["service"] == "rds"
    assert result["response"]["job_id"] == "job-456"


def test_build_sdk_client_uses_global_credentials_for_iam() -> None:
    class FakeBuilder:
        def __init__(self):
            self.credentials = None
            self.region = None

        def with_credentials(self, credentials):
            self.credentials = credentials
            return self

        def with_region(self, region):
            self.region = region
            return self

        def build(self):
            return self

    class FakeClientClass:
        @staticmethod
        def new_builder():
            return FakeBuilder()

    class FakeSpec:
        credential_scope = "global"
        display_name = "Identity and Access Management (IAM)"
        client_class = FakeClientClass

        @staticmethod
        def region_for(region: str):
            return f"region:{region}"

    config = CloudApiConfig(
        access_key_id="test-ak",
        secret_access_key="test-sk",
        region="ap-southeast-1",
    )

    builder = build_sdk_client(config, FakeSpec())

    assert isinstance(builder.credentials, GlobalCredentials)
    assert builder.region == "region:ap-southeast-1"


def test_call_operation_rejects_unknown_fields() -> None:
    service = HuaweiCloudSdkService(make_config(), "ecs")

    with pytest.raises(ValueError, match="Unknown fields"):
        service.call_operation("list_cloud_servers", {"not_a_real_field": "value"})
