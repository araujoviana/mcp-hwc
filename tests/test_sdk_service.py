import pytest

from huaweicloudsdkecs.v2.model.create_servers_response import CreateServersResponse
from huaweicloudsdkrds.v3.model.create_instance_response import CreateInstanceResponse

from mcp_hwc.config import CloudApiConfig
from mcp_hwc.sdk_service import HuaweiCloudSdkService


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


def test_call_operation_rejects_unknown_fields() -> None:
    service = HuaweiCloudSdkService(make_config(), "ecs")

    with pytest.raises(ValueError, match="Unknown fields"):
        service.call_operation("list_cloud_servers", {"not_a_real_field": "value"})
