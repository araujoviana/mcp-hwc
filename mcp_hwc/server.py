from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from functools import lru_cache
import io
import json
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
from typing import Callable, TypeVar
from urllib.parse import urlparse
import zipfile

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from .cli_service import DEFAULT_TOOL_IMAGES, CliService, CliServiceError, ContainerMount
from .config import CloudApiConfig, ConfigError, ObsConfig
from .defaults import resolve_service_defaults
from .obs_service import ObsService, ObsServiceError
from .sdk_service import (
    HuaweiCloudSdkError,
    HuaweiCloudSdkService,
    SERVICE_SPECS,
    list_supported_services,
    resolve_service_spec,
    summarize_service_capabilities,
)
from .ssh_service import SshService, SshServiceError

T = TypeVar("T")


class HelperToolError(RuntimeError):
    """Raised when a direct convenience tool cannot complete locally."""

_SUPPORTED_SERVICE_NAMES = ", ".join(SERVICE_SPECS)
_MCP_INSTRUCTIONS = (
    "Ask for as little as possible. When the user asks to create or configure a "
    "Huawei Cloud service, infer and create prerequisites automatically, reuse "
    "existing resources when safe, and only ask follow-up questions when the "
    "missing choice materially changes region, security, cost, deletion risk, or "
    "required secrets.\n\n"
    "Default to end-to-end provisioning instead of stopping at schema discovery. "
    "That includes VPCs, subnets, security groups, routes, images, node pools, "
    "public access, load balancers, storage, backups, and KMS resources when the "
    "requested service depends on them.\n\n"
    "When a service exposes an SSH endpoint, use `ssh_execute`, `ssh_upload_file`, "
    "and `ssh_download_file` to finish post-provisioning tasks such as package "
    "installation or configuration management. Use OBS file-transfer tools for "
    "binary uploads and downloads. Use `swr_upload_image` to push local container "
    "images to SWR, `functiongraph_deploy_code` to zip and upload local function "
    "source, `cce_get_kubeconfig` to export cluster access config, `k8s_*` tools "
    "for kubectl-style operations, `helm_*` tools for chart management, and "
    "`lts_query_logs` to resolve LTS groups or streams and filter logs.\n\n"
    "Use `huaweicloud_list_services` to discover supported services, aliases, and "
    "API versions. Use `huaweicloud_summarize_capabilities` when you need a fast "
    "answer about what a service can do at the SDK level. Use `huaweicloud_resolve_defaults` "
    "when the user request is vague and you need a least-input service profile. Use service-specific "
    "`*_list_operations`, `*_describe_operation`, and `*_call_operation` tools when "
    "available, or the generic `huaweicloud_*` "
    "tools when you need alias resolution or explicit `api_version` selection.\n\n"
    f"Supported SDK-backed service families include: {_SUPPORTED_SERVICE_NAMES}."
)

mcp = FastMCP("huawei-cloud", instructions=_MCP_INSTRUCTIONS)


@lru_cache(maxsize=1)
def get_obs_service() -> ObsService:
    return ObsService.from_config(ObsConfig.from_env())


@lru_cache(maxsize=1)
def get_ssh_service() -> SshService:
    return SshService()


@lru_cache(maxsize=1)
def get_cli_service() -> CliService:
    return CliService()


@lru_cache(maxsize=None)
def get_sdk_service(
    service_name: str,
    api_version: str | None = None,
    region: str | None = None,
    project_id: str | None = None,
    domain_id: str | None = None,
    endpoint: str | None = None,
) -> HuaweiCloudSdkService:
    resolved_spec = resolve_service_spec(service_name, api_version)
    return HuaweiCloudSdkService(
        CloudApiConfig.from_env(
            resolved_spec.env_key,
            region=region,
            project_id=project_id,
            domain_id=domain_id,
            endpoint=endpoint,
        ),
        resolved_spec.name,
        api_version=resolved_spec.api_version,
    )


def _make_sdk_service_getter(service_name: str):
    def getter(
        region: str | None = None,
        project_id: str | None = None,
        domain_id: str | None = None,
        endpoint: str | None = None,
        api_version: str | None = None,
    ) -> HuaweiCloudSdkService:
        return get_sdk_service(
            service_name,
            api_version=api_version,
            region=region,
            project_id=project_id,
            domain_id=domain_id,
            endpoint=endpoint,
        )

    getter.__name__ = f"get_{service_name}_service"
    return getter


for _service_name in SERVICE_SPECS:
    globals()[f"get_{_service_name}_service"] = _make_sdk_service_getter(_service_name)


def clear_caches() -> None:
    get_obs_service.cache_clear()
    get_ssh_service.cache_clear()
    get_cli_service.cache_clear()
    get_sdk_service.cache_clear()


def _run_tool_call(call: Callable[[], T]) -> T:
    try:
        return call()
    except (
        ConfigError,
        CliServiceError,
        HelperToolError,
        ObsServiceError,
        HuaweiCloudSdkError,
        SshServiceError,
        ValueError,
    ) as exc:
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
        if len(parts) >= 4 and parts[-2:] in (["myhuaweicloud", "com"], ["myhuaweicloud", "eu"]):
            return parts[-3]

    return None


def _get_resolved_sdk_service(
    service_name: str,
    api_version: str | None = None,
    region: str | None = None,
    project_id: str | None = None,
    domain_id: str | None = None,
    endpoint: str | None = None,
) -> HuaweiCloudSdkService:
    resolved_spec = resolve_service_spec(service_name, api_version)
    getter = globals()[f"get_{resolved_spec.name}_service"]
    return getter(
        region=region,
        project_id=project_id,
        domain_id=domain_id,
        endpoint=endpoint,
        api_version=resolved_spec.api_version,
    )


def _resolve_output_path(
    destination_path: str | None,
    *,
    prefix: str,
    suffix: str,
) -> Path:
    if destination_path is None:
        handle = tempfile.NamedTemporaryFile(delete=False, prefix=prefix, suffix=suffix)
        handle.close()
        return Path(handle.name)

    resolved_path = Path(destination_path).expanduser().resolve()
    resolved_path.parent.mkdir(parents=True, exist_ok=True)
    return resolved_path


def _serialize_kubeconfig_document(response: dict[str, object]) -> str:
    kubeconfig = {
        "apiVersion": response.get("apiVersion") or response.get("api_version") or "v1",
        "kind": response.get("kind") or "Config",
        "preferences": response.get("preferences") or {},
        "clusters": response.get("clusters") or [],
        "users": response.get("users") or [],
        "contexts": response.get("contexts") or [],
        "current-context": response.get("current-context")
        or response.get("current_context")
        or "",
    }
    return json.dumps(kubeconfig, indent=2, ensure_ascii=True)


def _execute_cli_tool(
    tool_name: str,
    args: list[str],
    *,
    execution_backend: str = "auto",
    container_image: str | None = None,
    env: dict[str, str] | None = None,
    input_text: str | None = None,
    working_directory: str | Path | None = None,
    mounts: list[ContainerMount] | None = None,
    network: str | None = None,
) -> dict[str, object]:
    cli_service = get_cli_service()
    resolved_image = container_image or DEFAULT_TOOL_IMAGES.get(tool_name)
    backend = cli_service.resolve_backend(
        tool_name,
        backend=execution_backend,
        container_image=resolved_image,
    )
    if backend == "local":
        return cli_service.execute_local(
            tool_name,
            args,
            env=env,
            input_text=input_text,
            working_directory=working_directory,
        )

    if resolved_image is None:
        raise ValueError(f"No default container image is configured for {tool_name}")

    return cli_service.execute_container(
        image=resolved_image,
        entrypoint=tool_name,
        args=args,
        env=env,
        input_text=input_text,
        working_directory=working_directory,
        mounts=mounts,
        network=network,
    )


def _format_cli_value(value: object) -> str:
    if isinstance(value, bool):
        return str(value).lower()
    if isinstance(value, (dict, list)):
        return json.dumps(value, separators=(",", ":"), ensure_ascii=True)
    return str(value)


def _prepare_helm_values_file(
    values: str | None,
    values_file: str | None,
) -> tuple[Path | None, bool]:
    if values and values_file:
        raise ValueError("Provide either values or values_file, not both")
    if values_file:
        return _resolve_existing_path(values_file), False
    if values is None:
        return None, False

    temp_file = tempfile.NamedTemporaryFile(
        delete=False,
        prefix="mcp-hwc-helm-values-",
        suffix=".yaml",
        mode="w",
        encoding="utf-8",
    )
    with temp_file:
        temp_file.write(values)
    return Path(temp_file.name), True


def _prepare_kubeconfig_for_backend(
    kubeconfig_path: str,
    *,
    context: str | None,
    backend: str,
) -> tuple[list[str], list[ContainerMount]]:
    resolved_path = _resolve_existing_path(kubeconfig_path)
    if backend == "container":
        mounted_path = "/tmp/mcp-hwc-kubeconfig"
        args = ["--kubeconfig", mounted_path]
        mounts = [ContainerMount(resolved_path, mounted_path, read_only=True)]
    else:
        args = ["--kubeconfig", str(resolved_path)]
        mounts = []

    if context:
        args.extend(["--context", context])
    return args, mounts


def _parse_json_output(stdout: str) -> object | None:
    text = stdout.strip()
    if not text:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _prepare_chart_reference(
    chart: str,
    *,
    backend: str,
) -> tuple[str, list[ContainerMount]]:
    candidate = Path(chart).expanduser()
    if not candidate.exists():
        return chart, []

    resolved_path = candidate.resolve()
    if backend == "container":
        mounted_path = "/tmp/mcp-hwc-chart"
        return mounted_path, [ContainerMount(resolved_path, mounted_path, read_only=True)]
    return str(resolved_path), []


def _resolve_existing_path(path: str) -> Path:
    candidate = Path(path).expanduser().resolve()
    if not candidate.exists():
        raise ValueError(f"Path does not exist: {candidate}")
    return candidate


def _package_functiongraph_source(source_path: str) -> dict[str, object]:
    resolved_path = _resolve_existing_path(source_path)
    suffix = resolved_path.suffix.lower()

    if resolved_path.is_file() and suffix in {".zip", ".jar"}:
        archive_bytes = resolved_path.read_bytes()
        code_type = "jar" if suffix == ".jar" else "zip"
        code_filename = resolved_path.name
    else:
        archive_buffer = io.BytesIO()
        with zipfile.ZipFile(archive_buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            if resolved_path.is_dir():
                written = False
                for child in sorted(resolved_path.rglob("*")):
                    if child.is_dir():
                        continue
                    archive.write(child, child.relative_to(resolved_path).as_posix())
                    written = True
                if not written:
                    raise ValueError(f"Directory is empty: {resolved_path}")
                code_filename = f"{resolved_path.name or 'function'}.zip"
            else:
                archive.write(resolved_path, resolved_path.name)
                code_filename = f"{resolved_path.stem or resolved_path.name}.zip"
        archive_bytes = archive_buffer.getvalue()
        code_type = "zip"

    return {
        "source_path": str(resolved_path),
        "code_type": code_type,
        "code_filename": code_filename,
        "func_code": {
            "file": base64.b64encode(archive_bytes).decode("ascii"),
        },
        "archive_size_bytes": len(archive_bytes),
    }


def _normalize_time_ms(
    value: str | int | None,
    *,
    default: datetime,
) -> str:
    if value is None:
        resolved = default
    elif isinstance(value, int):
        if value > 10**12:
            return str(value)
        return str(value * 1000)
    else:
        text = value.strip()
        if not text:
            resolved = default
        elif text.isdigit():
            number = int(text)
            return str(number if number > 10**12 else number * 1000)
        else:
            try:
                resolved = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError as exc:
                raise ValueError(
                    "Time values must be epoch seconds, epoch milliseconds, or ISO-8601 strings"
                ) from exc

    if resolved.tzinfo is None:
        resolved = resolved.replace(tzinfo=timezone.utc)
    return str(int(resolved.timestamp() * 1000))


def _extract_first_string(item: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def _select_named_resource(
    items: list[dict[str, object]],
    *,
    name: str | None,
    id_keys: tuple[str, ...],
    name_keys: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    if not items:
        raise HelperToolError(f"No {label}s matched the requested criteria")

    if name is None:
        if len(items) == 1:
            return items[0]
        raise ValueError(
            f"Multiple {label}s matched. Provide the {label}_name or {label}_id explicitly."
        )

    expected = name.casefold()
    exact_matches = [
        item
        for item in items
        if (_extract_first_string(item, *name_keys) or "").casefold() == expected
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise HelperToolError(f"Multiple {label}s matched the exact name '{name}'")

    partial_matches = [
        item
        for item in items
        if expected in (_extract_first_string(item, *name_keys) or "").casefold()
    ]
    if len(partial_matches) == 1:
        return partial_matches[0]

    available = sorted(
        {
            resource_name
            for item in items
            if (resource_name := _extract_first_string(item, *name_keys))
        }
    )
    raise HelperToolError(
        f"Could not resolve {label} '{name}'. Available {label} names: {', '.join(available[:20])}"
    )


def _resolve_lts_log_group(
    service: HuaweiCloudSdkService,
    *,
    log_group_id: str | None,
    log_group_name: str | None,
) -> dict[str, str | None]:
    if log_group_id:
        groups_response = service.call_operation("list_log_groups")
        groups = groups_response["response"].get("log_groups") or []
        for item in groups:
            if not isinstance(item, dict):
                continue
            if _extract_first_string(item, "log_group_id", "id") == log_group_id:
                return {
                    "id": log_group_id,
                    "name": _extract_first_string(item, "log_group_name", "name"),
                }
        return {"id": log_group_id, "name": log_group_name}

    if not log_group_name:
        raise ValueError("Provide log_group_id or log_group_name")

    groups_response = service.call_operation("list_log_groups")
    groups = [
        item
        for item in groups_response["response"].get("log_groups") or []
        if isinstance(item, dict)
    ]
    selected = _select_named_resource(
        groups,
        name=log_group_name,
        id_keys=("log_group_id", "id"),
        name_keys=("log_group_name", "name"),
        label="log group",
    )
    return {
        "id": _extract_first_string(selected, "log_group_id", "id"),
        "name": _extract_first_string(selected, "log_group_name", "name"),
    }


def _resolve_lts_log_stream(
    service: HuaweiCloudSdkService,
    *,
    log_group_id: str,
    log_group_name: str | None,
    log_stream_id: str | None,
    log_stream_name: str | None,
) -> dict[str, str | None]:
    if log_stream_id:
        stream_name = log_stream_name
        if stream_name is None:
            streams_response = service.call_operation(
                "list_log_stream",
                {"log_group_id": log_group_id},
            )
            for item in streams_response["response"].get("log_streams") or []:
                if not isinstance(item, dict):
                    continue
                if _extract_first_string(item, "log_stream_id", "id") == log_stream_id:
                    stream_name = _extract_first_string(item, "log_stream_name", "name")
                    break
        return {"id": log_stream_id, "name": stream_name}

    response = None
    if log_group_name:
        params: dict[str, object] = {"log_group_name": log_group_name}
        if log_stream_name:
            params["log_stream_name"] = log_stream_name
        response = service.call_operation("list_log_streams", params)
    else:
        response = service.call_operation(
            "list_log_stream",
            {"log_group_id": log_group_id},
        )

    streams = [
        item
        for item in response["response"].get("log_streams") or []
        if isinstance(item, dict)
    ]
    selected = _select_named_resource(
        streams,
        name=log_stream_name,
        id_keys=("log_stream_id", "id"),
        name_keys=("log_stream_name", "name"),
        label="log stream",
    )
    return {
        "id": _extract_first_string(selected, "log_stream_id", "id"),
        "name": _extract_first_string(selected, "log_stream_name", "name"),
    }


def _filter_lts_logs(
    items: list[object],
    *,
    contains_text: str | None,
    regex: str | None,
) -> list[object]:
    compiled_pattern = None
    if regex:
        try:
            compiled_pattern = re.compile(regex, re.IGNORECASE)
        except re.error as exc:
            raise ValueError(f"Invalid regex: {exc}") from exc

    expected_text = contains_text.casefold() if contains_text else None
    filtered = []
    for item in items:
        haystack = json.dumps(item, ensure_ascii=True, sort_keys=True, default=str)
        if expected_text and expected_text not in haystack.casefold():
            continue
        if compiled_pattern and compiled_pattern.search(haystack) is None:
            continue
        filtered.append(item)
    return filtered


def _looks_like_existing_resource_error(message: str) -> bool:
    lowered = message.casefold()
    return any(
        token in lowered
        for token in ("already exists", "already exist", "duplicate", "conflict", "exist")
    )


def _normalize_registry_host(registry: str) -> str:
    value = registry.strip().rstrip("/")
    if "://" in value:
        parsed = urlparse(value)
        value = parsed.netloc or parsed.path
    return value.rstrip("/")


def _decode_swr_auth(auth_token: str) -> tuple[str, str]:
    try:
        decoded = base64.b64decode(auth_token).decode("utf-8")
    except Exception as exc:  # noqa: BLE001
        raise HelperToolError("SWR returned an invalid authorization token") from exc

    username, separator, password = decoded.partition(":")
    if not separator or not username or not password:
        raise HelperToolError("SWR authorization token did not contain username and password")
    return username, password


def _resolve_container_cli(preferred_cli: str | None) -> str:
    candidates = [preferred_cli] if preferred_cli else ["docker", "podman", "nerdctl"]
    for candidate in candidates:
        if candidate and shutil.which(candidate):
            return candidate
    if preferred_cli:
        raise HelperToolError(f"Container CLI not found: {preferred_cli}")
    raise HelperToolError("No container CLI found. Install docker, podman, or nerdctl.")


def _run_local_command(command: list[str], *, input_text: str | None = None) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            command,
            input=input_text,
            text=True,
            capture_output=True,
            check=False,
        )
    except OSError as exc:
        joined_command = " ".join(command)
        raise HelperToolError(f"Failed to execute local command '{joined_command}': {exc}") from exc

    if result.returncode != 0:
        joined_command = " ".join(command)
        stderr = result.stderr.strip() or result.stdout.strip()
        raise HelperToolError(f"Local command failed ({joined_command}): {stderr}")
    return result


def _ensure_swr_namespace_and_repo(
    service: HuaweiCloudSdkService,
    *,
    namespace: str,
    repository: str,
    create_namespace: bool,
    create_repo: bool,
    repo_is_public: bool,
    repo_category: str,
    repo_description: str | None,
) -> None:
    if create_namespace:
        try:
            service.call_operation(
                "create_namespace",
                {"body": {"namespace": namespace}},
            )
        except HuaweiCloudSdkError as exc:
            if not _looks_like_existing_resource_error(str(exc)):
                raise

    if create_repo:
        body: dict[str, object] = {
            "repository": repository,
            "is_public": repo_is_public,
            "category": repo_category,
        }
        if repo_description:
            body["description"] = repo_description
        try:
            service.call_operation(
                "create_repo",
                {
                    "namespace": namespace,
                    "body": body,
                },
            )
        except HuaweiCloudSdkError as exc:
            if not _looks_like_existing_resource_error(str(exc)):
                raise


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
def obs_upload_file(
    bucket_name: str,
    source_path: str,
    object_key: str | None = None,
    region: str | None = None,
) -> dict[str, object]:
    """Upload a local file into OBS, defaulting the object key to the file name."""
    return _run_tool_call(
        lambda: get_obs_service().upload_file(
            bucket_name=bucket_name,
            source_path=source_path,
            object_key=object_key,
            region=region,
        )
    )


@mcp.tool()
def obs_download_object(
    bucket_name: str,
    object_key: str,
    destination_path: str,
    region: str | None = None,
) -> dict[str, object]:
    """Download an OBS object to a local file path."""
    return _run_tool_call(
        lambda: get_obs_service().download_object(
            bucket_name=bucket_name,
            object_key=object_key,
            destination_path=destination_path,
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
def huaweicloud_list_services(query: str | None = None) -> dict[str, object]:
    """List supported Huawei Cloud services, aliases, API versions, and provisioning hints."""
    return _run_tool_call(lambda: list_supported_services(query=query))


@mcp.tool()
def huaweicloud_summarize_capabilities(
    service_name: str,
    focus: str | None = None,
    api_version: str | None = None,
) -> dict[str, object]:
    """Summarize the SDK capabilities of a supported Huawei Cloud service."""
    return _run_tool_call(
        lambda: summarize_service_capabilities(
            service_name=service_name,
            api_version=api_version,
            focus=focus,
        )
    )


@mcp.tool()
def huaweicloud_resolve_defaults(
    service_name: str,
    region: str | None = None,
    intent: str = "small",
    exposure: str = "auto",
) -> dict[str, object]:
    """Resolve least-input provisioning defaults for a supported Huawei Cloud service."""
    return _run_tool_call(
        lambda: resolve_service_defaults(
            service_name,
            region=region,
            intent=intent,
            exposure=exposure,
        )
    )


@mcp.tool()
def huaweicloud_list_operations(
    service_name: str,
    query: str | None = None,
    limit: int = 100,
    offset: int = 0,
    api_version: str | None = None,
) -> dict[str, object]:
    """List SDK operations for any supported Huawei Cloud service or alias."""
    return _run_tool_call(
        lambda: _get_resolved_sdk_service(
            service_name,
            api_version=api_version,
        ).list_operations(
            query=query,
            limit=limit,
            offset=offset,
        )
    )


@mcp.tool()
def huaweicloud_describe_operation(
    service_name: str,
    operation: str,
    api_version: str | None = None,
    max_depth: int = 4,
) -> dict[str, object]:
    """Describe the request schema for any supported Huawei Cloud service operation."""
    return _run_tool_call(
        lambda: _get_resolved_sdk_service(
            service_name,
            api_version=api_version,
        ).describe_operation(
            operation=operation,
            max_depth=max_depth,
        )
    )


@mcp.tool()
def huaweicloud_call_operation(
    service_name: str,
    operation: str,
    parameters: dict[str, object] | None = None,
    region: str | None = None,
    project_id: str | None = None,
    domain_id: str | None = None,
    endpoint: str | None = None,
    api_version: str | None = None,
) -> dict[str, object]:
    """Execute any supported Huawei Cloud SDK operation using a service name or alias."""
    return _run_tool_call(
        lambda: _get_resolved_sdk_service(
            service_name,
            api_version=api_version,
            region=_resolve_sdk_region(region, parameters, endpoint),
            project_id=project_id,
            domain_id=domain_id,
            endpoint=endpoint,
        ).call_operation(
            operation=operation,
            parameters=parameters,
        )
    )


@mcp.tool()
def functiongraph_deploy_code(
    source_path: str,
    region: str | None = None,
    function_urn: str | None = None,
    func_name: str | None = None,
    runtime: str | None = None,
    handler: str | None = None,
    package_name: str = "default",
    timeout: int = 30,
    memory_size: int = 128,
    description: str | None = None,
    xrole: str | None = None,
    app_xrole: str | None = None,
    depend_version_list: list[str] | None = None,
    enable_lts_log: bool = False,
    code_encrypt_kms_key_id: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
    api_version: str | None = None,
) -> dict[str, object]:
    """Zip local code and create or update a FunctionGraph function."""

    def deploy() -> dict[str, object]:
        packaged_code = _package_functiongraph_source(source_path)
        service = _get_resolved_sdk_service(
            "functiongraph",
            api_version=api_version,
            region=region,
            project_id=project_id,
            endpoint=endpoint,
        )

        if function_urn:
            body: dict[str, object] = {
                "code_type": packaged_code["code_type"],
                "code_filename": packaged_code["code_filename"],
                "func_code": packaged_code["func_code"],
            }
            if depend_version_list:
                body["depend_version_list"] = depend_version_list
            if code_encrypt_kms_key_id:
                body["code_encrypt_kms_key_id"] = code_encrypt_kms_key_id

            result = service.call_operation(
                "update_function_code",
                {
                    "function_urn": function_urn,
                    "body": body,
                },
            )
        else:
            if not func_name or not runtime or not handler:
                raise ValueError(
                    "func_name, runtime, and handler are required when creating a new FunctionGraph function"
                )

            body = {
                "func_name": func_name,
                "package": package_name,
                "runtime": runtime,
                "timeout": timeout,
                "handler": handler,
                "memory_size": memory_size,
                "code_type": packaged_code["code_type"],
                "code_filename": packaged_code["code_filename"],
                "func_code": packaged_code["func_code"],
                "enable_lts_log": enable_lts_log,
            }
            if description:
                body["description"] = description
            if xrole:
                body["xrole"] = xrole
            if app_xrole:
                body["app_xrole"] = app_xrole
            if depend_version_list:
                body["depend_version_list"] = depend_version_list
            if code_encrypt_kms_key_id:
                body["code_encrypt_kms_key_id"] = code_encrypt_kms_key_id

            result = service.call_operation(
                "create_function",
                {"body": body},
            )

        result["source_path"] = packaged_code["source_path"]
        result["code_filename"] = packaged_code["code_filename"]
        result["archive_size_bytes"] = packaged_code["archive_size_bytes"]
        return result

    return _run_tool_call(deploy)


@mcp.tool()
def cce_get_kubeconfig(
    cluster_id: str,
    region: str,
    duration: int = 7,
    destination_path: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
    api_version: str | None = None,
) -> dict[str, object]:
    """Create a kubeconfig file for a CCE cluster and save it locally."""

    def export_kubeconfig() -> dict[str, object]:
        if duration <= 0:
            raise ValueError("duration must be greater than zero")

        service = _get_resolved_sdk_service(
            "cce",
            api_version=api_version,
            region=region,
            project_id=project_id,
            endpoint=endpoint,
        )
        result = service.call_operation(
            "create_kubernetes_cluster_cert",
            {
                "cluster_id": cluster_id,
                "body": {"duration": duration},
            },
        )

        output_path = _resolve_output_path(
            destination_path,
            prefix=f"{cluster_id[:8]}-",
            suffix=".kubeconfig.json",
        )
        kubeconfig_text = _serialize_kubeconfig_document(result["response"])
        output_path.write_text(kubeconfig_text, encoding="utf-8")
        try:
            output_path.chmod(0o600)
        except OSError:
            pass

        return {
            "service": "cce",
            "operation": "create_kubernetes_cluster_cert",
            "cluster_id": cluster_id,
            "region": region,
            "api_version": result["api_version"],
            "kubeconfig_path": str(output_path),
            "kubeconfig_format": "json",
            "current_context": result["response"].get("current-context")
            or result["response"].get("current_context"),
            "expires_in_days": duration,
            "port_id": result["response"].get("Port-ID")
            or result["response"].get("port_id"),
            "written": True,
        }

    return _run_tool_call(export_kubeconfig)


@mcp.tool()
def k8s_apply_manifest(
    kubeconfig_path: str,
    manifest: str | None = None,
    manifest_path: str | None = None,
    namespace: str | None = None,
    context: str | None = None,
    validate: bool = True,
    server_side: bool = False,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Apply a Kubernetes manifest using kubectl."""

    def apply_manifest() -> dict[str, object]:
        if bool(manifest) == bool(manifest_path):
            raise ValueError("Provide exactly one of manifest or manifest_path")

        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("kubectl")
        backend = get_cli_service().resolve_backend(
            "kubectl",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = _prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )

        args = [*kubeconfig_args, "apply", "-f"]
        input_text = manifest
        if manifest_path:
            resolved_manifest_path = _resolve_existing_path(manifest_path)
            if backend == "container":
                mounted_manifest_path = "/tmp/mcp-hwc-manifest.yaml"
                mounts.append(
                    ContainerMount(
                        resolved_manifest_path,
                        mounted_manifest_path,
                        read_only=True,
                    )
                )
                args.append(mounted_manifest_path)
            else:
                args.append(str(resolved_manifest_path))
            input_text = None
        else:
            args.append("-")

        if namespace:
            args.extend(["-n", namespace])
        if not validate:
            args.append("--validate=false")
        if server_side:
            args.append("--server-side")

        result = _execute_cli_tool(
            "kubectl",
            args,
            execution_backend=backend,
            container_image=resolved_image,
            input_text=input_text,
            mounts=mounts,
        )
        return {
            **result,
            "resource_type": "kubernetes",
            "namespace": namespace,
            "manifest_source": "path" if manifest_path else "inline",
            "applied": True,
        }

    return _run_tool_call(apply_manifest)


@mcp.tool()
def k8s_get_resources(
    kubeconfig_path: str,
    resource: str,
    namespace: str | None = None,
    all_namespaces: bool = False,
    selector: str | None = None,
    field_selector: str | None = None,
    output: str = "yaml",
    context: str | None = None,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Get Kubernetes resources using kubectl."""

    def get_resources() -> dict[str, object]:
        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("kubectl")
        backend = get_cli_service().resolve_backend(
            "kubectl",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = _prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )

        args = [*kubeconfig_args, "get", resource, "-o", output]
        if all_namespaces:
            args.append("--all-namespaces")
        elif namespace:
            args.extend(["-n", namespace])
        if selector:
            args.extend(["-l", selector])
        if field_selector:
            args.extend(["--field-selector", field_selector])

        result = _execute_cli_tool(
            "kubectl",
            args,
            execution_backend=backend,
            container_image=resolved_image,
            mounts=mounts,
        )
        return {
            **result,
            "resource_type": "kubernetes",
            "resource": resource,
            "namespace": namespace,
            "all_namespaces": all_namespaces,
            "output_format": output,
            "parsed_output": _parse_json_output(result["stdout"]) if output == "json" else None,
        }

    return _run_tool_call(get_resources)


@mcp.tool()
def k8s_wait(
    kubeconfig_path: str,
    resource: str,
    namespace: str | None = None,
    for_condition: str = "condition=Available",
    timeout_seconds: int = 300,
    context: str | None = None,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Wait for a Kubernetes resource condition using kubectl."""

    def wait_for_resource() -> dict[str, object]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("kubectl")
        backend = get_cli_service().resolve_backend(
            "kubectl",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = _prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )

        args = [
            *kubeconfig_args,
            "wait",
            resource,
            "--for",
            for_condition,
            "--timeout",
            f"{timeout_seconds}s",
        ]
        if namespace:
            args.extend(["-n", namespace])

        result = _execute_cli_tool(
            "kubectl",
            args,
            execution_backend=backend,
            container_image=resolved_image,
            mounts=mounts,
        )
        return {
            **result,
            "resource_type": "kubernetes",
            "resource": resource,
            "namespace": namespace,
            "for_condition": for_condition,
            "wait_satisfied": True,
        }

    return _run_tool_call(wait_for_resource)


@mcp.tool()
def k8s_logs(
    kubeconfig_path: str,
    resource: str,
    namespace: str | None = None,
    container: str | None = None,
    tail_lines: int = 200,
    since: str | None = None,
    previous: bool = False,
    context: str | None = None,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Fetch Kubernetes logs using kubectl."""

    def get_logs() -> dict[str, object]:
        if tail_lines <= 0:
            raise ValueError("tail_lines must be greater than zero")

        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("kubectl")
        backend = get_cli_service().resolve_backend(
            "kubectl",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = _prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )

        args = [*kubeconfig_args, "logs", resource, "--tail", str(tail_lines)]
        if namespace:
            args.extend(["-n", namespace])
        if container:
            args.extend(["-c", container])
        if since:
            args.extend(["--since", since])
        if previous:
            args.append("--previous")

        result = _execute_cli_tool(
            "kubectl",
            args,
            execution_backend=backend,
            container_image=resolved_image,
            mounts=mounts,
        )
        return {
            **result,
            "resource_type": "kubernetes",
            "resource": resource,
            "namespace": namespace,
            "container": container,
            "logs": result["stdout"],
        }

    return _run_tool_call(get_logs)


@mcp.tool()
def k8s_exec(
    kubeconfig_path: str,
    pod: str,
    namespace: str,
    command: str,
    container: str | None = None,
    context: str | None = None,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Execute a shell command inside a Kubernetes pod using kubectl exec."""

    def exec_in_pod() -> dict[str, object]:
        if not namespace:
            raise ValueError("namespace is required")
        if not command.strip():
            raise ValueError("command cannot be empty")

        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("kubectl")
        backend = get_cli_service().resolve_backend(
            "kubectl",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = _prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )

        args = [*kubeconfig_args, "exec", pod, "-n", namespace]
        if container:
            args.extend(["-c", container])
        args.extend(["--", "sh", "-lc", command])

        result = _execute_cli_tool(
            "kubectl",
            args,
            execution_backend=backend,
            container_image=resolved_image,
            mounts=mounts,
        )
        return {
            **result,
            "resource_type": "kubernetes",
            "pod": pod,
            "namespace": namespace,
            "container": container,
        }

    return _run_tool_call(exec_in_pod)


@mcp.tool()
def helm_install(
    kubeconfig_path: str,
    release_name: str,
    chart: str,
    namespace: str | None = None,
    repo: str | None = None,
    version: str | None = None,
    values: str | None = None,
    values_file: str | None = None,
    set_values: dict[str, object] | None = None,
    create_namespace: bool = True,
    wait: bool = True,
    timeout_seconds: int = 600,
    context: str | None = None,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Install a Helm chart into a Kubernetes cluster."""

    def install_chart() -> dict[str, object]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("helm")
        backend = get_cli_service().resolve_backend(
            "helm",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = _prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )
        effective_chart, chart_mounts = _prepare_chart_reference(chart, backend=backend)
        mounts.extend(chart_mounts)

        values_path, delete_values_file = _prepare_helm_values_file(values, values_file)
        try:
            args = [*kubeconfig_args, "install", release_name, effective_chart]
            if namespace:
                args.extend(["--namespace", namespace])
            if repo:
                args.extend(["--repo", repo])
            if version:
                args.extend(["--version", version])
            if create_namespace:
                args.append("--create-namespace")
            if wait:
                args.extend(["--wait", "--timeout", f"{timeout_seconds}s"])
            if values_path is not None:
                if backend == "container":
                    mounted_values_path = "/tmp/mcp-hwc-helm-values.yaml"
                    mounts.append(
                        ContainerMount(values_path, mounted_values_path, read_only=True)
                    )
                    args.extend(["--values", mounted_values_path])
                else:
                    args.extend(["--values", str(values_path)])
            for key, value in sorted((set_values or {}).items()):
                args.extend(["--set", f"{key}={_format_cli_value(value)}"])

            result = _execute_cli_tool(
                "helm",
                args,
                execution_backend=backend,
                container_image=resolved_image,
                mounts=mounts,
            )
            return {
                **result,
                "resource_type": "helm",
                "release_name": release_name,
                "chart": chart,
                "namespace": namespace,
                "installed": True,
            }
        finally:
            if values_path is not None and delete_values_file:
                values_path.unlink(missing_ok=True)

    return _run_tool_call(install_chart)


@mcp.tool()
def helm_upgrade(
    kubeconfig_path: str,
    release_name: str,
    chart: str,
    namespace: str | None = None,
    repo: str | None = None,
    version: str | None = None,
    values: str | None = None,
    values_file: str | None = None,
    set_values: dict[str, object] | None = None,
    install_if_missing: bool = True,
    wait: bool = True,
    timeout_seconds: int = 600,
    context: str | None = None,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Upgrade a Helm release, optionally installing it if missing."""

    def upgrade_chart() -> dict[str, object]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("helm")
        backend = get_cli_service().resolve_backend(
            "helm",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = _prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )
        effective_chart, chart_mounts = _prepare_chart_reference(chart, backend=backend)
        mounts.extend(chart_mounts)

        values_path, delete_values_file = _prepare_helm_values_file(values, values_file)
        try:
            args = [*kubeconfig_args, "upgrade", release_name, effective_chart]
            if install_if_missing:
                args.append("--install")
            if namespace:
                args.extend(["--namespace", namespace])
            if repo:
                args.extend(["--repo", repo])
            if version:
                args.extend(["--version", version])
            if wait:
                args.extend(["--wait", "--timeout", f"{timeout_seconds}s"])
            if values_path is not None:
                if backend == "container":
                    mounted_values_path = "/tmp/mcp-hwc-helm-values.yaml"
                    mounts.append(
                        ContainerMount(values_path, mounted_values_path, read_only=True)
                    )
                    args.extend(["--values", mounted_values_path])
                else:
                    args.extend(["--values", str(values_path)])
            for key, value in sorted((set_values or {}).items()):
                args.extend(["--set", f"{key}={_format_cli_value(value)}"])

            result = _execute_cli_tool(
                "helm",
                args,
                execution_backend=backend,
                container_image=resolved_image,
                mounts=mounts,
            )
            return {
                **result,
                "resource_type": "helm",
                "release_name": release_name,
                "chart": chart,
                "namespace": namespace,
                "upgraded": True,
            }
        finally:
            if values_path is not None and delete_values_file:
                values_path.unlink(missing_ok=True)

    return _run_tool_call(upgrade_chart)


@mcp.tool()
def helm_uninstall(
    kubeconfig_path: str,
    release_name: str,
    namespace: str | None = None,
    wait: bool = True,
    timeout_seconds: int = 300,
    context: str | None = None,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Uninstall a Helm release from a Kubernetes cluster."""

    def uninstall_chart() -> dict[str, object]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("helm")
        backend = get_cli_service().resolve_backend(
            "helm",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = _prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )

        args = [*kubeconfig_args, "uninstall", release_name]
        if namespace:
            args.extend(["--namespace", namespace])
        if wait:
            args.extend(["--wait", "--timeout", f"{timeout_seconds}s"])

        result = _execute_cli_tool(
            "helm",
            args,
            execution_backend=backend,
            container_image=resolved_image,
            mounts=mounts,
        )
        return {
            **result,
            "resource_type": "helm",
            "release_name": release_name,
            "namespace": namespace,
            "uninstalled": True,
        }

    return _run_tool_call(uninstall_chart)


@mcp.tool()
def lts_query_logs(
    log_group_id: str | None = None,
    log_group_name: str | None = None,
    log_stream_id: str | None = None,
    log_stream_name: str | None = None,
    start_time: str | int | None = None,
    end_time: str | int | None = None,
    keywords: str | None = None,
    labels: dict[str, str] | None = None,
    query: str | None = None,
    analysis_query: bool = False,
    sql_expression: str | None = None,
    limit: int = 100,
    is_desc: bool = True,
    highlight: bool = False,
    original_content: bool = False,
    contains_text: str | None = None,
    regex: str | None = None,
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
    api_version: str | None = None,
) -> dict[str, object]:
    """Resolve LTS log groups or streams by name and query filtered logs."""

    def query_logs() -> dict[str, object]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if analysis_query and not query:
            raise ValueError("query is required when analysis_query is true")

        service = _get_resolved_sdk_service(
            "lts",
            api_version=api_version,
            region=region,
            project_id=project_id,
            endpoint=endpoint,
        )

        now = datetime.now(timezone.utc)
        start_time_ms = _normalize_time_ms(
            start_time,
            default=now - timedelta(hours=1),
        )
        end_time_ms = _normalize_time_ms(end_time, default=now)

        log_group = _resolve_lts_log_group(
            service,
            log_group_id=log_group_id,
            log_group_name=log_group_name,
        )
        if log_group["id"] is None:
            raise HelperToolError("Could not resolve an LTS log group ID")

        log_stream = _resolve_lts_log_stream(
            service,
            log_group_id=log_group["id"],
            log_group_name=log_group["name"],
            log_stream_id=log_stream_id,
            log_stream_name=log_stream_name,
        )
        if log_stream["id"] is None:
            raise HelperToolError("Could not resolve an LTS log stream ID")

        if sql_expression:
            result = service.call_operation(
                "list_query_structured_logs",
                {
                    "log_group_id": log_group["id"],
                    "log_stream_id": log_stream["id"],
                    "body": {
                        "start_time": start_time_ms,
                        "end_time": end_time_ms,
                        "sql_expression": sql_expression,
                        "original_content": original_content,
                    },
                },
            )
        else:
            body: dict[str, object] = {
                "start_time": start_time_ms,
                "end_time": end_time_ms,
                "limit": limit,
                "is_desc": is_desc,
                "highlight": highlight,
            }
            if labels:
                body["labels"] = labels
            if keywords:
                body["keywords"] = keywords
            if query:
                body["query"] = query
                body["is_analysis_query"] = analysis_query

            result = service.call_operation(
                "list_logs",
                {
                    "log_group_id": log_group["id"],
                    "log_stream_id": log_stream["id"],
                    "body": body,
                },
            )

        response = result["response"]
        raw_logs = response.get("struct_logs")
        if raw_logs is None:
            raw_logs = response.get("logs")
        if raw_logs is None:
            raw_logs = response.get("analysis_logs")
        raw_logs = raw_logs or []
        filtered_logs = _filter_lts_logs(
            raw_logs,
            contains_text=contains_text,
            regex=regex,
        )

        result["log_group_id"] = log_group["id"]
        result["log_group_name"] = log_group["name"]
        result["log_stream_id"] = log_stream["id"]
        result["log_stream_name"] = log_stream["name"]
        result["query_window"] = {
            "start_time": start_time_ms,
            "end_time": end_time_ms,
        }
        result["raw_count"] = len(raw_logs)
        result["matched_count"] = len(filtered_logs)
        result["logs"] = filtered_logs
        return result

    return _run_tool_call(query_logs)


@mcp.tool()
def swr_upload_image(
    source_image: str,
    namespace: str,
    repository: str,
    tag: str = "latest",
    registry: str | None = None,
    container_cli: str | None = None,
    create_namespace: bool = True,
    create_repo: bool = True,
    repo_is_public: bool = False,
    repo_category: str = "other",
    repo_description: str | None = None,
    region: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
    api_version: str | None = None,
) -> dict[str, object]:
    """Create SWR auth, optionally create namespace or repo, and push a local image."""

    def upload_image() -> dict[str, object]:
        resolved_cli = _resolve_container_cli(container_cli)
        service = _get_resolved_sdk_service(
            "swr",
            api_version=api_version,
            region=region,
            project_id=project_id,
            endpoint=endpoint,
        )

        _ensure_swr_namespace_and_repo(
            service,
            namespace=namespace,
            repository=repository,
            create_namespace=create_namespace,
            create_repo=create_repo,
            repo_is_public=repo_is_public,
            repo_category=repo_category,
            repo_description=repo_description,
        )

        token_result = service.call_operation("create_authorization_token")
        token_response = token_result["response"]
        auths = token_response.get("auths") or {}
        if not isinstance(auths, dict) or not auths:
            raise HelperToolError("SWR did not return any registry authorization entries")

        requested_registry = registry.strip() if registry else next(iter(auths))
        registry_host = _normalize_registry_host(requested_registry)
        auth_entry = None
        for auth_registry, value in auths.items():
            if _normalize_registry_host(str(auth_registry)) == registry_host:
                auth_entry = value
                break
        if not isinstance(auth_entry, dict):
            raise HelperToolError(
                f"SWR did not return credentials for registry '{registry_host}'"
            )

        encoded_auth = auth_entry.get("auth")
        if not isinstance(encoded_auth, str) or not encoded_auth:
            raise HelperToolError("SWR authorization entry did not include a usable auth token")
        username, password = _decode_swr_auth(encoded_auth)

        target_image = f"{registry_host}/{namespace}/{repository}:{tag}"
        login_result = _run_local_command(
            [resolved_cli, "login", "--username", username, "--password-stdin", registry_host],
            input_text=password,
        )
        _run_local_command([resolved_cli, "tag", source_image, target_image])
        push_result = _run_local_command([resolved_cli, "push", target_image])

        return {
            "service": "swr",
            "operation": "upload_image",
            "region": region,
            "container_cli": resolved_cli,
            "registry": registry_host,
            "namespace": namespace,
            "repository": repository,
            "tag": tag,
            "source_image": source_image,
            "target_image": target_image,
            "authorization_expires_at": token_response.get("x_swr_expireat"),
            "login_stdout": login_result.stdout,
            "push_stdout": push_result.stdout,
            "pushed": True,
        }

    return _run_tool_call(upload_image)


@mcp.tool()
def ssh_execute(
    host: str,
    username: str,
    command: str,
    port: int = 22,
    password: str | None = None,
    private_key_path: str | None = None,
    allow_unknown_host: bool = True,
    connect_timeout: int = 20,
    command_timeout: int = 300,
) -> dict[str, object]:
    """Run a shell command on an SSH-accessible host."""
    return _run_tool_call(
        lambda: get_ssh_service().execute(
            host=host,
            username=username,
            command=command,
            port=port,
            password=password,
            private_key_path=private_key_path,
            allow_unknown_host=allow_unknown_host,
            connect_timeout=connect_timeout,
            command_timeout=command_timeout,
        )
    )


@mcp.tool()
def ssh_upload_file(
    host: str,
    username: str,
    local_path: str,
    remote_path: str,
    port: int = 22,
    password: str | None = None,
    private_key_path: str | None = None,
    allow_unknown_host: bool = True,
    connect_timeout: int = 20,
) -> dict[str, object]:
    """Upload a local file to an SSH-accessible host using SFTP."""
    return _run_tool_call(
        lambda: get_ssh_service().upload_file(
            host=host,
            username=username,
            local_path=local_path,
            remote_path=remote_path,
            port=port,
            password=password,
            private_key_path=private_key_path,
            allow_unknown_host=allow_unknown_host,
            connect_timeout=connect_timeout,
        )
    )


@mcp.tool()
def ssh_download_file(
    host: str,
    username: str,
    remote_path: str,
    local_path: str,
    port: int = 22,
    password: str | None = None,
    private_key_path: str | None = None,
    allow_unknown_host: bool = True,
    connect_timeout: int = 20,
) -> dict[str, object]:
    """Download a remote file from an SSH-accessible host using SFTP."""
    return _run_tool_call(
        lambda: get_ssh_service().download_file(
            host=host,
            username=username,
            remote_path=remote_path,
            local_path=local_path,
            port=port,
            password=password,
            private_key_path=private_key_path,
            allow_unknown_host=allow_unknown_host,
            connect_timeout=connect_timeout,
        )
    )


def _register_sdk_tools(service_name: str) -> None:
    spec = SERVICE_SPECS[service_name]
    getter_name = f"get_{service_name}_service"

    @mcp.tool(
        name=f"{service_name}_list_operations",
        description=f"List {spec.display_name} operations exposed by the Huawei Cloud Python SDK.",
    )
    def list_operations(
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
        api_version: str | None = None,
    ) -> dict[str, object]:
        getter = globals()[getter_name]
        return _run_tool_call(
            lambda: getter(api_version=api_version).list_operations(
                query=query,
                limit=limit,
                offset=offset,
            )
        )

    list_operations.__name__ = f"{service_name}_list_operations"
    globals()[list_operations.__name__] = list_operations

    @mcp.tool(
        name=f"{service_name}_describe_operation",
        description=f"Describe the request schema for a {spec.display_name} operation.",
    )
    def describe_operation(
        operation: str,
        api_version: str | None = None,
        max_depth: int = 4,
    ) -> dict[str, object]:
        getter = globals()[getter_name]
        return _run_tool_call(
            lambda: getter(api_version=api_version).describe_operation(
                operation=operation,
                max_depth=max_depth,
            )
        )

    describe_operation.__name__ = f"{service_name}_describe_operation"
    globals()[describe_operation.__name__] = describe_operation

    @mcp.tool(
        name=f"{service_name}_call_operation",
        description=(
            f"Execute any {spec.display_name} SDK operation with a structured request payload. "
            "Use `api_version` when the service publishes multiple SDK surfaces."
        ),
    )
    def call_operation(
        operation: str,
        parameters: dict[str, object] | None = None,
        region: str | None = None,
        project_id: str | None = None,
        domain_id: str | None = None,
        endpoint: str | None = None,
        api_version: str | None = None,
    ) -> dict[str, object]:
        getter = globals()[getter_name]
        return _run_tool_call(
            lambda: getter(
                region=_resolve_sdk_region(region, parameters, endpoint),
                project_id=project_id,
                domain_id=domain_id,
                endpoint=endpoint,
                api_version=api_version,
            ).call_operation(
                operation=operation,
                parameters=parameters,
            )
        )

    call_operation.__name__ = f"{service_name}_call_operation"
    globals()[call_operation.__name__] = call_operation


for _service_name in SERVICE_SPECS:
    _register_sdk_tools(_service_name)


def main() -> None:
    mcp.run(transport="stdio")
