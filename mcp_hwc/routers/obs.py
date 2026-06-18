from __future__ import annotations
from typing import TYPE_CHECKING
import mcp_hwc.server as server
from mcp_hwc.schemas.operations import ObsBucketSchema

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

def obs_list_buckets() -> dict[str, object]:
    """List OBS buckets accessible to the configured credentials."""
    return server._run_tool_call(lambda: server.get_obs_service().list_buckets())

def obs_create_bucket(
    args: ObsBucketSchema
) -> dict[str, object]:
    """Create an OBS bucket in the requested region code or alias like 'santiago'."""
    return server._run_tool_call(
        lambda: server.get_obs_service().create_bucket(
            bucket_name=args.bucket_name,
            region=args.region,
        )
    )

def obs_list_objects(
    bucket_name: str,
    prefix: str | None = None,
    max_keys: int = 100,
    marker: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """List objects in an OBS bucket, optionally filtered by prefix."""
    return server._run_tool_call(
        lambda: server.get_obs_service().list_objects(
            bucket_name=bucket_name,
            prefix=prefix,
            max_keys=max_keys,
            marker=marker,
            region=region,
        )
    )

def obs_get_bucket_location(bucket_name: str) -> dict[str, str | None]:
    """Get the region/location for an OBS bucket."""
    return server._run_tool_call(lambda: server.get_obs_service().get_bucket_location(bucket_name))

def obs_head_bucket(
    bucket_name: str,
    region: str | None = None,
) -> dict[str, object]:
    """Check bucket metadata and reachability."""
    return server._run_tool_call(
        lambda: server.get_obs_service().head_bucket(
            bucket_name=bucket_name,
            region=region,
        )
    )

def obs_get_text_object(
    bucket_name: str,
    object_key: str,
    encoding: str = "utf-8",
    region: str | None = None,
) -> dict[str, object]:
    """Read an OBS object into memory and decode it as text."""
    return server._run_tool_call(
        lambda: server.get_obs_service().get_object_text(
            bucket_name=bucket_name,
            object_key=object_key,
            encoding=encoding,
            region=region,
        )
    )

def obs_head_object(
    bucket_name: str,
    object_key: str,
    version_id: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """Read object metadata without downloading the object body."""
    return server._run_tool_call(
        lambda: server.get_obs_service().head_object(
            bucket_name=bucket_name,
            object_key=object_key,
            version_id=version_id,
            region=region,
        )
    )

def obs_put_text_object(
    bucket_name: str,
    object_key: str,
    content: str,
    region: str | None = None,
) -> dict[str, object]:
    """Upload text content into an OBS object."""
    return server._run_tool_call(
        lambda: server.get_obs_service().put_text_object(
            bucket_name=bucket_name,
            object_key=object_key,
            content=content,
            region=region,
        )
    )

def obs_upload_file(
    bucket_name: str,
    source_path: str,
    object_key: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """Upload a local file into OBS, defaulting the object key to the file name."""
    return server._run_tool_call(
        lambda: server.get_obs_service().upload_file(
            bucket_name=bucket_name,
            source_path=source_path,
            object_key=object_key,
            region=region,
        )
    )

def obs_download_object(
    bucket_name: str,
    object_key: str,
    destination_path: str,
    region: str | None = None,
) -> dict[str, object]:
    """Download an OBS object to a local file path."""
    return server._run_tool_call(
        lambda: server.get_obs_service().download_object(
            bucket_name=bucket_name,
            object_key=object_key,
            destination_path=destination_path,
            region=region,
        )
    )

def obs_delete_object(
    bucket_name: str,
    object_key: str,
    version_id: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """Delete an OBS object."""
    return server._run_tool_call(
        lambda: server.get_obs_service().delete_object(
            bucket_name=bucket_name,
            object_key=object_key,
            version_id=version_id,
            region=region,
        )
    )

def obs_delete_bucket(
    bucket_name: str,
    region: str | None = None,
) -> dict[str, object]:
    """Delete an OBS bucket."""
    return server._run_tool_call(
        lambda: server.get_obs_service().delete_bucket(
            bucket_name=bucket_name,
            region=region,
        )
    )

def register_obs_tools(mcp: FastMCP):
    from mcp_hwc.core.tool_manager import tool_manager, Toolset

    ts = Toolset("obs", "Tools for Object Storage Service (OBS) operations.")
    ts.add_tool(obs_list_buckets)
    ts.add_tool(obs_create_bucket)
    ts.add_tool(obs_list_objects)
    ts.add_tool(obs_get_bucket_location)
    ts.add_tool(obs_head_bucket)
    ts.add_tool(obs_get_text_object)
    ts.add_tool(obs_head_object)
    ts.add_tool(obs_put_text_object)
    ts.add_tool(obs_upload_file)
    ts.add_tool(obs_download_object)
    ts.add_tool(obs_delete_object)
    ts.add_tool(obs_delete_bucket)

    tool_manager.register_toolset(ts)
