from __future__ import annotations

from functools import lru_cache
from typing import Callable, TypeVar
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from .config import CloudApiConfig, ConfigError, ObsConfig
from .obs_service import ObsService, ObsServiceError
from .sdk_service import HuaweiCloudSdkError, HuaweiCloudSdkService

T = TypeVar("T")

mcp = FastMCP("huawei-cloud")


@lru_cache(maxsize=1)
def get_obs_service() -> ObsService:
    return ObsService.from_config(ObsConfig.from_env())


@lru_cache(maxsize=None)
def get_sdk_service(
    service_name: str,
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> HuaweiCloudSdkService:
    return HuaweiCloudSdkService(
        CloudApiConfig.from_env(
            service_name,
            region=region,
            project_id=project_id,
            endpoint=endpoint,
        ),
        service_name,
    )


def get_ecs_service(
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> HuaweiCloudSdkService:
    return get_sdk_service("ecs", region, project_id, endpoint)


def get_rds_service(
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> HuaweiCloudSdkService:
    return get_sdk_service("rds", region, project_id, endpoint)


def get_vpc_service(
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> HuaweiCloudSdkService:
    return get_sdk_service("vpc", region, project_id, endpoint)


def get_ims_service(
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> HuaweiCloudSdkService:
    return get_sdk_service("ims", region, project_id, endpoint)


def clear_caches() -> None:
    get_obs_service.cache_clear()
    get_sdk_service.cache_clear()


def _run_tool_call(call: Callable[[], T]) -> T:
    try:
        return call()
    except (ConfigError, ObsServiceError, HuaweiCloudSdkError, ValueError) as exc:
        raise ToolError(str(exc)) from exc


def _resolve_sdk_region(
    region: str | None,
    parameters: dict[str, object] | None,
    endpoint: str | None,
) -> str | None:
    if region:
        return region

    if parameters:
        direct_region = parameters.get("region") or parameters.get("region_id")
        if isinstance(direct_region, str) and direct_region.strip():
            return direct_region

        body = parameters.get("body")
        if isinstance(body, dict):
            nested_region = body.get("region") or body.get("region_id")
            if isinstance(nested_region, str) and nested_region.strip():
                return nested_region

    if endpoint:
        host = urlparse(endpoint).netloc.lower()
        parts = host.split(".")
        if len(parts) >= 4 and parts[-2:] == ["myhuaweicloud", "com"]:
            return parts[-3]

    return None


@mcp.tool()
def obs_list_buckets() -> dict[str, object]:
    """List OBS buckets accessible to the configured credentials."""
    return _run_tool_call(lambda: get_obs_service().list_buckets())


@mcp.tool()
def obs_create_bucket(
    bucket_name: str,
    region: str | None = None,
) -> dict[str, object]:
    """Create an OBS bucket in the requested region code or alias like 'santiago'."""
    return _run_tool_call(
        lambda: get_obs_service().create_bucket(
            bucket_name=bucket_name,
            region=region,
        )
    )


@mcp.tool()
def obs_list_objects(
    bucket_name: str,
    prefix: str | None = None,
    max_keys: int = 100,
    marker: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """List objects in an OBS bucket, optionally filtered by prefix."""
    return _run_tool_call(
        lambda: get_obs_service().list_objects(
            bucket_name=bucket_name,
            prefix=prefix,
            max_keys=max_keys,
            marker=marker,
            region=region,
        )
    )


@mcp.tool()
def obs_get_bucket_location(bucket_name: str) -> dict[str, str | None]:
    """Get the region/location for an OBS bucket."""
    return _run_tool_call(lambda: get_obs_service().get_bucket_location(bucket_name))


@mcp.tool()
def obs_head_bucket(
    bucket_name: str,
    region: str | None = None,
) -> dict[str, object]:
    """Check bucket metadata and reachability."""
    return _run_tool_call(
        lambda: get_obs_service().head_bucket(
            bucket_name=bucket_name,
            region=region,
        )
    )


@mcp.tool()
def obs_get_text_object(
    bucket_name: str,
    object_key: str,
    encoding: str = "utf-8",
    region: str | None = None,
) -> dict[str, object]:
    """Read an OBS object into memory and decode it as text."""
    return _run_tool_call(
        lambda: get_obs_service().get_object_text(
            bucket_name=bucket_name,
            object_key=object_key,
            encoding=encoding,
            region=region,
        )
    )


@mcp.tool()
def obs_head_object(
    bucket_name: str,
    object_key: str,
    version_id: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """Read object metadata without downloading the object body."""
    return _run_tool_call(
        lambda: get_obs_service().head_object(
            bucket_name=bucket_name,
            object_key=object_key,
            version_id=version_id,
            region=region,
        )
    )


@mcp.tool()
def obs_put_text_object(
    bucket_name: str,
    object_key: str,
    content: str,
    region: str | None = None,
) -> dict[str, object]:
    """Upload text content into an OBS object."""
    return _run_tool_call(
        lambda: get_obs_service().put_text_object(
            bucket_name=bucket_name,
            object_key=object_key,
            content=content,
            region=region,
        )
    )


@mcp.tool()
def obs_delete_object(
    bucket_name: str,
    object_key: str,
    version_id: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """Delete an OBS object."""
    return _run_tool_call(
        lambda: get_obs_service().delete_object(
            bucket_name=bucket_name,
            object_key=object_key,
            version_id=version_id,
            region=region,
        )
    )


@mcp.tool()
def obs_delete_bucket(
    bucket_name: str,
    region: str | None = None,
) -> dict[str, object]:
    """Delete an OBS bucket."""
    return _run_tool_call(
        lambda: get_obs_service().delete_bucket(
            bucket_name=bucket_name,
            region=region,
        )
    )


@mcp.tool()
def ecs_list_operations(
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, object]:
    """List ECS operations exposed by the Huawei Cloud Python SDK."""
    return _run_tool_call(
        lambda: get_ecs_service().list_operations(
            query=query,
            limit=limit,
            offset=offset,
        )
    )


@mcp.tool()
def ecs_describe_operation(
    operation: str,
    max_depth: int = 4,
) -> dict[str, object]:
    """Describe the request schema for an ECS operation."""
    return _run_tool_call(
        lambda: get_ecs_service().describe_operation(
            operation=operation,
            max_depth=max_depth,
        )
    )


@mcp.tool()
def ecs_call_operation(
    operation: str,
    parameters: dict[str, object] | None = None,
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> dict[str, object]:
    """Execute any ECS SDK operation with a structured request payload and region code or alias."""
    return _run_tool_call(
        lambda: get_ecs_service(
            region=_resolve_sdk_region(region, parameters, endpoint),
            project_id=project_id,
            endpoint=endpoint,
        ).call_operation(
            operation=operation,
            parameters=parameters,
        )
    )


@mcp.tool()
def rds_list_operations(
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, object]:
    """List RDS operations exposed by the Huawei Cloud Python SDK."""
    return _run_tool_call(
        lambda: get_rds_service().list_operations(
            query=query,
            limit=limit,
            offset=offset,
        )
    )


@mcp.tool()
def rds_describe_operation(
    operation: str,
    max_depth: int = 4,
) -> dict[str, object]:
    """Describe the request schema for an RDS operation."""
    return _run_tool_call(
        lambda: get_rds_service().describe_operation(
            operation=operation,
            max_depth=max_depth,
        )
    )


@mcp.tool()
def rds_call_operation(
    operation: str,
    parameters: dict[str, object] | None = None,
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> dict[str, object]:
    """Execute any RDS SDK operation with a structured request payload and region code or alias."""
    return _run_tool_call(
        lambda: get_rds_service(
            region=_resolve_sdk_region(region, parameters, endpoint),
            project_id=project_id,
            endpoint=endpoint,
        ).call_operation(
            operation=operation,
            parameters=parameters,
        )
    )


@mcp.tool()
def vpc_list_operations(
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, object]:
    """List VPC operations exposed by the Huawei Cloud Python SDK."""
    return _run_tool_call(
        lambda: get_vpc_service().list_operations(
            query=query,
            limit=limit,
            offset=offset,
        )
    )


@mcp.tool()
def vpc_describe_operation(
    operation: str,
    max_depth: int = 4,
) -> dict[str, object]:
    """Describe the request schema for a VPC operation."""
    return _run_tool_call(
        lambda: get_vpc_service().describe_operation(
            operation=operation,
            max_depth=max_depth,
        )
    )


@mcp.tool()
def vpc_call_operation(
    operation: str,
    parameters: dict[str, object] | None = None,
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> dict[str, object]:
    """Execute any VPC SDK operation with a structured request payload and region code or alias."""
    return _run_tool_call(
        lambda: get_vpc_service(
            region=_resolve_sdk_region(region, parameters, endpoint),
            project_id=project_id,
            endpoint=endpoint,
        ).call_operation(
            operation=operation,
            parameters=parameters,
        )
    )


@mcp.tool()
def ims_list_operations(
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> dict[str, object]:
    """List IMS operations exposed by the Huawei Cloud Python SDK."""
    return _run_tool_call(
        lambda: get_ims_service().list_operations(
            query=query,
            limit=limit,
            offset=offset,
        )
    )


@mcp.tool()
def ims_describe_operation(
    operation: str,
    max_depth: int = 4,
) -> dict[str, object]:
    """Describe the request schema for an IMS operation."""
    return _run_tool_call(
        lambda: get_ims_service().describe_operation(
            operation=operation,
            max_depth=max_depth,
        )
    )


@mcp.tool()
def ims_call_operation(
    operation: str,
    parameters: dict[str, object] | None = None,
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> dict[str, object]:
    """Execute any IMS SDK operation with a structured request payload and region code or alias."""
    return _run_tool_call(
        lambda: get_ims_service(
            region=_resolve_sdk_region(region, parameters, endpoint),
            project_id=project_id,
            endpoint=endpoint,
        ).call_operation(
            operation=operation,
            parameters=parameters,
        )
    )


def main() -> None:
    mcp.run(transport="stdio")
