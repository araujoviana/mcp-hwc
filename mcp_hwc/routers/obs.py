from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import mcp_hwc.server as server

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP


def obs_manage_bucket(
    action: Literal["list", "create", "delete", "head", "get_location"],
    bucket_name: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """Manage OBS buckets.

    action='list': lists all buckets, no other params needed.
    action='create'/'delete'/'head': requires bucket_name; region is only used by 'create'
    (region code or alias like 'santiago').
    action='get_location': requires bucket_name, returns the bucket's region.
    """

    def run() -> dict[str, object]:
        svc = server.get_obs_service()
        if action == "list":
            return svc.list_buckets()
        if not bucket_name:
            raise ValueError(f"bucket_name is required for action='{action}'")
        if action == "create":
            return svc.create_bucket(bucket_name=bucket_name, region=region)
        if action == "delete":
            return svc.delete_bucket(bucket_name=bucket_name, region=region)
        if action == "head":
            return svc.head_bucket(bucket_name=bucket_name, region=region)
        if action == "get_location":
            return svc.get_bucket_location(bucket_name)
        raise ValueError(f"Unsupported action '{action}'")

    return server._run_tool_call(run)


def obs_manage_object(
    action: Literal["list", "get_text", "head", "put_text", "delete"],
    bucket_name: str,
    object_key: str | None = None,
    prefix: str | None = None,
    max_keys: int = 100,
    marker: str | None = None,
    content: str | None = None,
    encoding: str = "utf-8",
    version_id: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """Manage OBS objects within a bucket.

    action='list': requires bucket_name; optional prefix/max_keys/marker to page through results.
    action='get_text'/'head'/'delete': requires bucket_name + object_key.
    action='put_text': requires bucket_name + object_key + content (uploads text content).
    """

    def run() -> dict[str, object]:
        svc = server.get_obs_service()
        if action == "list":
            return svc.list_objects(
                bucket_name=bucket_name,
                prefix=prefix,
                max_keys=max_keys,
                marker=marker,
                region=region,
            )
        if not object_key:
            raise ValueError(f"object_key is required for action='{action}'")
        if action == "get_text":
            return svc.get_object_text(
                bucket_name=bucket_name,
                object_key=object_key,
                encoding=encoding,
                region=region,
            )
        if action == "head":
            return svc.head_object(
                bucket_name=bucket_name,
                object_key=object_key,
                version_id=version_id,
                region=region,
            )
        if action == "put_text":
            if content is None:
                raise ValueError("content is required for action='put_text'")
            return svc.put_text_object(
                bucket_name=bucket_name,
                object_key=object_key,
                content=content,
                region=region,
            )
        if action == "delete":
            return svc.delete_object(
                bucket_name=bucket_name,
                object_key=object_key,
                version_id=version_id,
                region=region,
            )
        raise ValueError(f"Unsupported action '{action}'")

    return server._run_tool_call(run)


def obs_transfer(
    action: Literal["upload_file", "download_object"],
    bucket_name: str,
    object_key: str | None = None,
    source_path: str | None = None,
    destination_path: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """Transfer files between local disk and OBS.

    action='upload_file': requires bucket_name + source_path; object_key defaults to the file name.
    action='download_object': requires bucket_name + object_key + destination_path.
    """

    def run() -> dict[str, object]:
        svc = server.get_obs_service()
        if action == "upload_file":
            if not source_path:
                raise ValueError("source_path is required for action='upload_file'")
            return svc.upload_file(
                bucket_name=bucket_name,
                source_path=source_path,
                object_key=object_key,
                region=region,
            )
        if action == "download_object":
            if not object_key or not destination_path:
                raise ValueError(
                    "object_key and destination_path are required for action='download_object'"
                )
            return svc.download_object(
                bucket_name=bucket_name,
                object_key=object_key,
                destination_path=destination_path,
                region=region,
            )
        raise ValueError(f"Unsupported action '{action}'")

    return server._run_tool_call(run)


def register_obs_tools(mcp: FastMCP):
    mcp.tool()(obs_manage_bucket)
    mcp.tool()(obs_manage_object)
    mcp.tool()(obs_transfer)
