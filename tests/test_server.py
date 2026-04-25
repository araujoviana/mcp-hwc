from types import SimpleNamespace

import pytest
from mcp.server.fastmcp.exceptions import ToolError
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_hwc import server
from mcp_hwc.obs_service import ObsServiceError


class FakeObsService:
    def list_buckets(self) -> dict[str, object]:
        return {
            "endpoint": "https://obs.myhuaweicloud.com",
            "bucket_count": 1,
            "buckets": [
                {
                    "name": "alpha",
                    "location": "ap-southeast-1",
                    "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
                    "created_at": None,
                }
            ],
        }

    def create_bucket(
        self,
        bucket_name: str,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "location": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "created": True,
        }

    def list_objects(
        self,
        bucket_name: str,
        prefix: str | None = None,
        max_keys: int = 100,
        marker: str | None = None,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "prefix": prefix,
            "max_keys": max_keys,
            "marker": marker,
            "objects": [{"key": "notes.txt", "size": 4}],
            "common_prefixes": [],
            "is_truncated": False,
            "next_marker": None,
            "location": "ap-southeast-1",
        }

    def get_bucket_location(self, bucket_name: str) -> dict[str, str]:
        return {
            "bucket": bucket_name,
            "location": "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
        }

    def head_bucket(
        self,
        bucket_name: str,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "status": 200,
            "request_id": "req-1",
        }

    def get_object_text(
        self,
        bucket_name: str,
        object_key: str,
        encoding: str = "utf-8",
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "encoding": encoding,
            "size_bytes": 4,
            "text": "demo",
        }

    def head_object(
        self,
        bucket_name: str,
        object_key: str,
        version_id: str | None = None,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "etag": "etag-1",
            "content_length": 4,
            "content_type": "text/plain",
            "last_modified": "2026-01-01T00:00:00.000Z",
            "version_id": version_id,
            "metadata": {},
        }

    def put_text_object(
        self,
        bucket_name: str,
        object_key: str,
        content: str,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "etag": "etag-1",
            "version_id": None,
            "object_url": f"https://example/{bucket_name}/{object_key}",
        }

    def delete_object(
        self,
        bucket_name: str,
        object_key: str,
        version_id: str | None = None,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "version_id": version_id,
            "deleted": True,
        }

    def delete_bucket(
        self,
        bucket_name: str,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "deleted": True,
        }


class FakeSdkService:
    def __init__(self, service_name: str):
        self._service_name = service_name

    def list_operations(
        self,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        return {
            "service": self._service_name,
            "region": "ap-southeast-1",
            "endpoint": f"https://{self._service_name}.ap-southeast-1.myhuaweicloud.com",
            "total_count": 1,
            "returned_count": 1,
            "offset": offset,
            "limit": limit,
            "operations": [f"{self._service_name}_demo_operation"],
        }

    def describe_operation(
        self,
        operation: str,
        max_depth: int = 4,
    ) -> dict[str, object]:
        return {
            "service": self._service_name,
            "operation": operation,
            "request_model": "DemoRequest",
            "request_schema": {"kind": "object", "model": "DemoRequest", "fields": []},
            "request_template": {},
            "notes": "demo",
        }

    def call_operation(
        self,
        operation: str,
        parameters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "service": self._service_name,
            "operation": operation,
            "region": "ap-southeast-1",
            "endpoint": f"https://{self._service_name}.ap-southeast-1.myhuaweicloud.com",
            "response": {"ok": True, "parameters": parameters or {}},
        }


def test_tool_function_calls_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_obs_service", lambda: FakeObsService())

    result = server.obs_list_objects("demo-bucket", prefix="docs/", max_keys=10)

    assert result["bucket"] == "demo-bucket"
    assert result["objects"][0]["key"] == "notes.txt"


def test_tool_errors_are_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    failing_service = SimpleNamespace(
        list_buckets=lambda: (_ for _ in ()).throw(ObsServiceError("boom"))
    )
    monkeypatch.setattr(server, "get_obs_service", lambda: failing_service)

    with pytest.raises(ToolError, match="boom"):
        server.obs_list_buckets()


def test_ecs_tool_function_calls_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "get_ecs_service", lambda *args, **kwargs: FakeSdkService("ecs")
    )

    result = server.ecs_call_operation(
        "create_servers",
        parameters={"body": {"server": {"name": "web-01"}}},
        region="ap-southeast-1",
    )

    assert result["service"] == "ecs"
    assert result["response"]["ok"] is True


def test_ecs_tool_infers_region_from_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_get_ecs_service(*args, **kwargs):
        captured.update(kwargs)
        return FakeSdkService("ecs")

    monkeypatch.setattr(server, "get_ecs_service", fake_get_ecs_service)

    server.ecs_call_operation(
        "create_servers",
        parameters={"body": {"region": "ap-southeast-1"}},
    )

    assert captured["region"] == "ap-southeast-1"


def test_vpc_tool_function_calls_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "get_vpc_service", lambda *args, **kwargs: FakeSdkService("vpc")
    )

    result = server.vpc_list_operations(query="list_vpc", limit=5)

    assert result["service"] == "vpc"
    assert result["operations"][0] == "vpc_demo_operation"


@pytest.mark.anyio
async def test_mcp_session_can_call_obs_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_obs_service", lambda: FakeObsService())

    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as session:
        result = await session.call_tool("obs_list_buckets", {})

    assert result.isError is False
    assert result.structuredContent["bucket_count"] == 1
    assert result.structuredContent["buckets"][0]["name"] == "alpha"


@pytest.mark.anyio
async def test_mcp_session_can_call_rds_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "get_rds_service", lambda *args, **kwargs: FakeSdkService("rds")
    )

    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as session:
        result = await session.call_tool("rds_list_operations", {})

    assert result.isError is False
    assert result.structuredContent["service"] == "rds"
    assert result.structuredContent["operations"][0] == "rds_demo_operation"


@pytest.mark.anyio
async def test_mcp_session_can_call_ims_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "get_ims_service", lambda *args, **kwargs: FakeSdkService("ims")
    )

    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as session:
        result = await session.call_tool("ims_list_operations", {})

    assert result.isError is False
    assert result.structuredContent["service"] == "ims"
    assert result.structuredContent["operations"][0] == "ims_demo_operation"
