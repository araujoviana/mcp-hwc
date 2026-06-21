from __future__ import annotations

from functools import lru_cache
import os
import sys
import argparse
from pathlib import Path
import shutil
import subprocess
import time
import uuid
from typing import Callable, TypeVar
from urllib.parse import urlparse

from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

from mcp_hwc.cloud_services.cli_service import DEFAULT_TOOL_IMAGES, CliService, CliServiceError, ContainerMount
from mcp_hwc.core.config import CloudApiConfig, ConfigError, ObsConfig
from mcp_hwc.cloud_services.compute import (
    create_ecs_security_group as _create_ecs_security_group,
    extract_first_string as _extract_first_string,
    extract_server_ips as _extract_server_ips,
    generate_secret_password as _generate_secret_password,
    normal_azs_for_flavor as _normal_azs_for_flavor,
    pick_access_image as _pick_access_image,
    pick_access_vm_flavor as _pick_access_vm_flavor,
    pick_default_subnet as _pick_default_subnet,
    pick_default_vpc as _pick_default_vpc,
    pick_sfs_availability_zone as _pick_sfs_availability_zone,
    list_compatible_ecs_flavors as _list_compatible_ecs_flavors,
    resolve_ecs_flavor as _resolve_ecs_flavor,
    resolve_ecs_image as _resolve_ecs_image,
    resolve_vpc_and_subnet as _resolve_vpc_and_subnet,
    select_named_resource as _select_named_resource,
)
from mcp_hwc.core.defaults import resolve_service_defaults
from mcp_hwc.core.errors import HelperToolError
from mcp_hwc.utils.local_artifacts import (
    format_cli_value as _format_cli_value,
    package_functiongraph_source as _package_functiongraph_source,
    parse_json_output as _parse_json_output,
    parse_psql_rows as _parse_psql_rows,
    prepare_chart_reference as _prepare_chart_reference,
    prepare_helm_values_file as _prepare_helm_values_file,
    prepare_kubeconfig_for_backend as _prepare_kubeconfig_for_backend,
    resolve_existing_path as _resolve_existing_path,
    resolve_output_path as _resolve_output_path,
    serialize_kubeconfig_document as _serialize_kubeconfig_document,
)
from mcp_hwc.workflows.lts_workflow import (
    filter_lts_logs as _filter_lts_logs,
    normalize_time_ms as _normalize_time_ms,
    query_lts_logs,
    resolve_lts_log_group as _resolve_lts_log_group,
    resolve_lts_log_stream as _resolve_lts_log_stream,
)
from mcp_hwc.cloud_services.obs_service import ObsService, ObsServiceError
from mcp_hwc.utils.polling import (
    DEFAULT_POLL_INTERVAL_SECONDS as _DEFAULT_POLL_INTERVAL_SECONDS,
    MIN_POLL_INTERVAL_SECONDS as _MIN_POLL_INTERVAL_SECONDS,
    extract_path_value as _extract_path_value,
    resolve_poll_interval as _resolve_poll_interval,
    sleep_before_next_poll as _sleep_before_next_poll,
    wait_for_service_value as _wait_for_service_value,
    wait_condition_matches as _wait_condition_matches,
)
from mcp_hwc.core.sdk_service import (
    HuaweiCloudSdkError,
    HuaweiCloudSdkService,
    SERVICE_SPECS,
    list_supported_services,
    resolve_service_spec,
    summarize_service_capabilities,
)
from mcp_hwc.cloud_services.ssh_service import SshService, SshServiceError
from mcp_hwc.workflows.swr_workflow import (
    decode_swr_auth as _decode_swr_auth,
    ensure_swr_namespace_and_repo as _ensure_swr_namespace_and_repo,
    looks_like_existing_resource_error as _looks_like_existing_resource_error,
    normalize_registry_host as _normalize_registry_host,
    resolve_container_cli as _resolve_container_cli,
    run_local_command as _run_local_command,
    upload_swr_image,
)
from mcp_hwc.pricing.models import QuoteItem, QuoteResult, ResourceDescriptor
from mcp_hwc.pricing.bss_pricing import BssAccessDenied, BssPricingBackend, PricingNotAvailable
from mcp_hwc.pricing.catalog import resolve_region as _pricing_resolve_region
from mcp_hwc.pricing.persistence import QuoteStore
from mcp_hwc.pricing.tools import export_csv, export_json, export_terraform, format_text
from mcp_hwc.workflows.ecs import create_ecs_vm as _create_ecs_vm_workflow
from mcp_hwc.workflows.sfs import create_accessible_share as _create_accessible_sfs_share_workflow

from mcp_hwc.schemas.operations import EcsCreateSchema, GenericCallSchema

T = TypeVar("T")


_SUPPORTED_SERVICE_NAMES = ", ".join(SERVICE_SPECS)
_GENERATED_SERVICE_TOOL_ENV = "MCP_HWC_ENABLE_SERVICE_TOOLS"
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
    "Prefer direct workflow tools over raw SDK calls. For ECS virtual machines, use "
    "`ecs_create_vm` first; it resolves the usual VPC, subnet, image, flavor, security "
    "group, and create payload from minimal input. Use raw SDK tools only for uncommon "
    "operations or when a workflow helper cannot express the request.\n\n"
    "When a service exposes an SSH endpoint, use `ssh_execute`, `ssh_upload_file`, "
    "and `ssh_download_file` to finish post-provisioning tasks such as package "
    "installation or configuration management. Use OBS file-transfer tools for "
    "binary uploads and downloads. Use `swr_upload_image` to push local container "
    "images to SWR, `functiongraph_deploy_code` to zip and upload local function "
    "source, `cce_get_kubeconfig` to export cluster access config, `k8s_*` tools "
    "for kubectl-style operations, `helm_*` tools for chart management, and "
    "`lts_query_logs` to resolve LTS groups or streams and filter logs. Do not poll "
    "after creates by default; prefer returning provider job IDs or resource IDs and "
    "only use `huaweicloud_wait_for_condition` when the next step requires the final "
    "state. When polling is required, use sparse intervals of at least 60 seconds, "
    "and `postgres_execute_sql` when you need to validate PostgreSQL connectivity "
    "from the MCP host.\n\n"
    "The default MCP catalog intentionally hides generated per-service SDK tools to "
    f"save model context. Set `{_GENERATED_SERVICE_TOOL_ENV}=all` or a comma-separated "
    "service allowlist to expose them. Generic `huaweicloud_*` SDK tools remain available.\n\n"
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
    config = ObsConfig.from_env()
    return ObsService.from_config(config)


@lru_cache(maxsize=1)
def get_ssh_service() -> SshService:
    return SshService()


@lru_cache(maxsize=1)
def get_cli_service() -> CliService:
    return CliService()


@lru_cache(maxsize=1)
def get_bss_pricing_backend() -> BssPricingBackend:
    return BssPricingBackend(CloudApiConfig.from_env("BSS"))


@lru_cache(maxsize=1)
def get_quote_store() -> QuoteStore:
    return QuoteStore()


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
    get_bss_pricing_backend.cache_clear()
    get_quote_store.cache_clear()


def _generated_service_tool_enabled(service_name: str) -> bool:
    configured = os.getenv(_GENERATED_SERVICE_TOOL_ENV, "").strip().lower()
    if not configured:
        return False
    if configured in {"*", "all"}:
        return True
    enabled = {
        item.strip().lower()
        for item in configured.split(",")
        if item.strip()
    }
    return service_name in enabled


def _run_tool_call(call: Callable[[], T]) -> T:
    """Execute a tool call and wrap potential exceptions into ToolError."""
    try:
        return call()
    except (
        ConfigError,
        CliServiceError,
        HelperToolError,
        ObsServiceError,
        HuaweiCloudSdkError,
        PricingNotAvailable,
        SshServiceError,
        ValueError,
    ) as exc:
        msg = str(exc)
        if "subeni quota is 0" in msg or "Eni network is not supported" in msg:
            msg += (
                ". Try using a different flavor that supports ENI. "
                "You can use `ecs_list_compatible_flavors` with `eni_required=True` to find one."
            )
        raise ToolError(msg) from exc


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


def _list_supported_services_for_mcp(query: str | None = None) -> dict[str, object]:
    result = list_supported_services(query=query)
    for service in result.get("services", []):
        if not isinstance(service, dict):
            continue
        service_name = service.get("service")
        if isinstance(service_name, str) and not _generated_service_tool_enabled(service_name):
            service["service_tools"] = []
        service["generic_sdk_tools"] = [
            "huaweicloud_list_operations",
            "huaweicloud_describe_operation",
            "huaweicloud_call_operation",
        ]
        if service_name == "ecs":
            service["workflow_tools"] = ["ecs_create_vm"]
    result["tooling_notes"] = [
        "Generated per-service SDK tools are hidden from the MCP catalog by default to save tokens.",
        f"Set {_GENERATED_SERVICE_TOOL_ENV}=all or a comma-separated service allowlist to expose them.",
        "Prefer workflow_tools when present; use generic_sdk_tools for uncommon operations.",
    ]
    return result


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


# Import router tools to expose them in the server module for testing
from mcp_hwc.routers.obs import (
    obs_list_buckets,
    obs_create_bucket,
    obs_list_objects,
    obs_get_bucket_location,
    obs_head_bucket,
    obs_get_text_object,
    obs_head_object,
    obs_put_text_object,
    obs_upload_file,
    obs_download_object,
    obs_delete_object,
    obs_delete_bucket,
    register_obs_tools,
)
from mcp_hwc.routers.k8s import (
    cce_get_kubeconfig,
    k8s_apply_manifest,
    k8s_get_resources,
    k8s_wait,
    k8s_logs,
    k8s_exec,
    helm_install,
    helm_upgrade,
    helm_uninstall,
    register_k8s_tools,
)
from mcp_hwc.routers.pricing import (
    price_quote,
    price_discover,
    price_export,
    price_list_quotes,
    price_get_quote,
    register_pricing_tools,
)

# Register tools with the MCP server
register_obs_tools(mcp)
register_k8s_tools(mcp)
register_pricing_tools(mcp)


@mcp.tool()
def ecs_list_compatible_flavors(
    region: str,
    min_cpu: int | None = None,
    min_ram_gb: int | None = None,
    eni_required: bool = False,
    availability_zone: str | None = None,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> dict[str, object]:
    """List ECS flavors filtered by CPU, RAM, ENI support, and availability zone."""
    return _run_tool_call(
        lambda: {
            "region": region,
            "flavors": _list_compatible_ecs_flavors(
                get_sdk_service(
                    "ecs",
                    region=region,
                    project_id=project_id,
                    endpoint=endpoint,
                ),
                min_cpu=min_cpu,
                min_ram_gb=min_ram_gb,
                eni_required=eni_required,
                az=availability_zone,
            ),
        }
    )


@mcp.tool()
def cce_monitor_provisioning(
    region: str,
    resource_type: str,
    resource_id: str,
    cluster_id: str | None = None,
    timeout_seconds: int = 1800,
    project_id: str | None = None,
    endpoint: str | None = None,
) -> dict[str, object]:
    """Monitor CCE cluster, node pool, or node provisioning status until Active/Available."""
    return _run_tool_call(
        lambda: _wait_for_service_value(
            get_sdk_service(
                "cce",
                region=region,
                project_id=project_id,
                endpoint=endpoint,
            ),
            operation={
                "cluster": "show_cluster",
                "node_pool": "show_node_pool",
                "node": "show_node",
            }[resource_type],
            parameters={
                "cluster": {"cluster_id": resource_id},
                "node_pool": {"cluster_id": cluster_id, "node_pool_id": resource_id},
                "node": {"cluster_id": cluster_id, "node_id": resource_id},
            }[resource_type],
            response_path={
                "cluster": "response.status.phase",
                "node_pool": "response.status.phase",
                "node": "response.status.phase",
            }[resource_type],
            expected_value="Available" if resource_type == "cluster" else "Active",
            timeout_seconds=timeout_seconds,
        )
    )


@mcp.tool()
def huaweicloud_list_services(query: str | None = None) -> dict[str, object]:
    """List supported Huawei Cloud services, aliases, API versions, and provisioning hints."""
    return _run_tool_call(lambda: _list_supported_services_for_mcp(query=query))


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
    wait_for_completion: bool = False,
    timeout_seconds: int = 1200,
) -> dict[str, object]:
    """Execute any supported Huawei Cloud SDK operation using a service name or alias."""

    def call_and_maybe_wait() -> dict[str, object]:
        resolved_service = _get_resolved_sdk_service(
            service_name,
            api_version=api_version,
            region=_resolve_sdk_region(region, parameters, endpoint),
            project_id=project_id,
            domain_id=domain_id,
            endpoint=endpoint,
        )
        result = resolved_service.call_operation(
            operation=operation,
            parameters=parameters,
        )

        if not wait_for_completion:
            return result

        response_body = result.get("response") or {}
        job_id = response_body.get("job_id") or response_body.get("jobId")

        if not job_id:
            return result

        return _wait_for_service_value(
            resolved_service,
            operation="show_job" if "show_job" in resolved_service._operations() else "show_job_status",
            parameters={"job_id": job_id},
            response_path="response.status",
            expected_value="SUCCESS",
            timeout_seconds=timeout_seconds,
        )

    return _run_tool_call(call_and_maybe_wait)


@mcp.tool()
def huaweicloud_wait_for_condition(
    service_name: str,
    operation: str,
    response_path: str,
    expected_value: object | None = None,
    match_mode: str | None = None,
    parameters: dict[str, object] | None = None,
    region: str | None = None,
    project_id: str | None = None,
    domain_id: str | None = None,
    endpoint: str | None = None,
    api_version: str | None = None,
    timeout_seconds: int = 1200,
    interval_seconds: int = _DEFAULT_POLL_INTERVAL_SECONDS,
) -> dict[str, object]:
    """Poll a Huawei Cloud SDK operation until a response field matches a condition."""

    def wait_for_condition() -> dict[str, object]:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        effective_interval = _resolve_poll_interval(interval_seconds)

        resolved_mode = match_mode or ("truthy" if expected_value is None else "equals")
        resolved_service = _get_resolved_sdk_service(
            service_name,
            api_version=api_version,
            region=_resolve_sdk_region(region, parameters, endpoint),
            project_id=project_id,
            domain_id=domain_id,
            endpoint=endpoint,
        )

        deadline = time.monotonic() + timeout_seconds
        attempts = 0
        last_result: dict[str, object] | None = None
        last_value: object | None = None
        last_error: str | None = None
        started_at = time.monotonic()

        while True:
            attempts += 1
            last_result = resolved_service.call_operation(
                operation=operation,
                parameters=parameters,
            )
            try:
                last_value = _extract_path_value(last_result, response_path)
                last_error = None
            except HelperToolError as exc:
                last_value = None
                last_error = str(exc)
            else:
                if _wait_condition_matches(
                    last_value,
                    expected_value=expected_value,
                    match_mode=resolved_mode,
                ):
                    return {
                        "service": last_result["service"],
                        "operation": operation,
                        "region": last_result["region"],
                        "endpoint": last_result["endpoint"],
                        "response_path": response_path,
                        "match_mode": resolved_mode,
                        "expected_value": expected_value,
                        "matched": True,
                        "attempts": attempts,
                        "elapsed_seconds": round(time.monotonic() - started_at, 3),
                        "value": last_value,
                        "last_result": last_result,
                    }

            if time.monotonic() >= deadline:
                detail = last_error or f"last value: {last_value!r}"
                raise HelperToolError(
                    f"Timed out waiting for {service_name}.{operation} {response_path} with match_mode={resolved_mode}; {detail}"
                )
            _sleep_before_next_poll(deadline, effective_interval)

    return _run_tool_call(wait_for_condition)


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
def postgres_execute_sql(
    host: str,
    username: str,
    password: str,
    sql: str,
    port: int = 5432,
    database: str = "postgres",
    sslmode: str = "require",
    connect_timeout: int = 15,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Execute a SQL statement against a PostgreSQL server using psql."""

    def execute_sql() -> dict[str, object]:
        if not host.strip():
            raise ValueError("host cannot be empty")
        if not username.strip():
            raise ValueError("username cannot be empty")
        if not sql.strip():
            raise ValueError("sql cannot be empty")
        if port <= 0:
            raise ValueError("port must be greater than zero")
        if connect_timeout <= 0:
            raise ValueError("connect_timeout must be greater than zero")

        env = {
            "PGPASSWORD": password,
            "PGSSLMODE": sslmode,
            "PGCONNECT_TIMEOUT": str(connect_timeout),
        }
        args = [
            "--host",
            host,
            "--port",
            str(port),
            "--username",
            username,
            "--dbname",
            database,
            "--no-password",
            "--no-psqlrc",
            "--set",
            "ON_ERROR_STOP=1",
            "--tuples-only",
            "--no-align",
            "--field-separator",
            "\t",
            "--command",
            sql,
        ]

        result = _execute_cli_tool(
            "psql",
            args,
            execution_backend=execution_backend,
            container_image=container_image,
            env=env,
        )
        rows = _parse_psql_rows(result["stdout"])
        return {
            **result,
            "host": host,
            "port": port,
            "database": database,
            "username": username,
            "sslmode": sslmode,
            "rows": rows,
            "row_count": len(rows),
        }

    return _run_tool_call(execute_sql)


@mcp.tool()
def ecs_create_vm(
    region: str,
    name: str | None = None,
    public_access: bool = True,
    ssh_cidr: str | None = None,
    admin_password: str | None = None,
    return_password: bool = True,
    vpc_id: str | None = None,
    subnet_id: str | None = None,
    security_group_id: str | None = None,
    image_id: str | None = None,
    image_hint: str | None = "Ubuntu",
    flavor_id: str | None = None,
    flavor_hint: str | None = None,
    availability_zone: str | None = None,
    root_volume_type: str = "GPSSD",
    root_volume_size_gb: int = 40,
    bandwidth_size_mbit: int = 5,
    wait: bool = False,
) -> dict[str, object]:
    """Create a small ECS VM from minimal input and hide routine SDK payload details."""
    return _run_tool_call(
        lambda: _create_ecs_vm_workflow(
            service_factory=_get_resolved_sdk_service,
            region=region,
            name=name,
            public_access=public_access,
            ssh_cidr=ssh_cidr,
            admin_password=admin_password,
            return_password=return_password,
            vpc_id=vpc_id,
            subnet_id=subnet_id,
            security_group_id=security_group_id,
            image_id=image_id,
            image_hint=image_hint,
            flavor_id=flavor_id,
            flavor_hint=flavor_hint,
            availability_zone=availability_zone,
            root_volume_type=root_volume_type,
            root_volume_size_gb=root_volume_size_gb,
            bandwidth_size_mbit=bandwidth_size_mbit,
            wait=wait,
        )
    )


@mcp.tool()
def sfs_create_accessible_share(
    region: str,
    client_cidr: str,
    share_name: str | None = None,
    size_gb: int = 500,
    share_type: str = "STANDARD",
    vpc_id: str | None = None,
    subnet_id: str | None = None,
    availability_zone: str | None = None,
    access_vm_name: str | None = None,
    access_vm_password: str | None = None,
    mount_path: str = "/mnt/sfs-demo",
) -> dict[str, object]:
    """Create an SFS share plus a public access VM, mount it, and return proof."""
    return _run_tool_call(
        lambda: _create_accessible_sfs_share_workflow(
            service_factory=_get_resolved_sdk_service,
            ssh_service=get_ssh_service(),
            region=region,
            client_cidr=client_cidr,
            share_name=share_name,
            size_gb=size_gb,
            share_type=share_type,
            vpc_id=vpc_id,
            subnet_id=subnet_id,
            availability_zone=availability_zone,
            access_vm_name=access_vm_name,
            access_vm_password=access_vm_password,
            mount_path=mount_path,
        )
    )


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
    """Resolve LTS log groups or streams by name and query filtered logs. Requires log_group_id or log_group_name; call list_log_groups first if you only have the cluster or resource name."""
    return _run_tool_call(
        lambda: query_lts_logs(
            _get_resolved_sdk_service(
                "lts",
                api_version=api_version,
                region=region,
                project_id=project_id,
                endpoint=endpoint,
            ),
            log_group_id=log_group_id,
            log_group_name=log_group_name,
            log_stream_id=log_stream_id,
            log_stream_name=log_stream_name,
            start_time=start_time,
            end_time=end_time,
            keywords=keywords,
            labels=labels,
            query=query,
            analysis_query=analysis_query,
            sql_expression=sql_expression,
            limit=limit,
            is_desc=is_desc,
            highlight=highlight,
            original_content=original_content,
            contains_text=contains_text,
            regex=regex,
        )
    )


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
    return _run_tool_call(
        lambda: upload_swr_image(
            _get_resolved_sdk_service(
                "swr",
                api_version=api_version,
                region=region,
                project_id=project_id,
                endpoint=endpoint,
            ),
            source_image=source_image,
            namespace=namespace,
            repository=repository,
            tag=tag,
            registry=registry,
            container_cli=container_cli,
            create_namespace=create_namespace,
            create_repo=create_repo,
            repo_is_public=repo_is_public,
            repo_category=repo_category,
            repo_description=repo_description,
            region=region,
        )
    )


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
    expose_tools = _generated_service_tool_enabled(service_name)

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
    if expose_tools:
        list_operations = mcp.tool(
            name=f"{service_name}_list_operations",
            description=f"List {spec.display_name} operations exposed by the Huawei Cloud Python SDK.",
        )(list_operations)
    globals()[list_operations.__name__] = list_operations

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
    if expose_tools:
        describe_operation = mcp.tool(
            name=f"{service_name}_describe_operation",
            description=f"Describe the request schema for a {spec.display_name} operation.",
        )(describe_operation)
    globals()[describe_operation.__name__] = describe_operation

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
    if expose_tools:
        call_operation = mcp.tool(
            name=f"{service_name}_call_operation",
            description=(
                f"Execute any {spec.display_name} SDK operation with a structured request payload. "
                "Use `api_version` when the service publishes multiple SDK surfaces."
            ),
        )(call_operation)
    globals()[call_operation.__name__] = call_operation


for _service_name in SERVICE_SPECS:
    _register_sdk_tools(_service_name)

def generate_config():
    python_path = sys.executable
    config = {
        "mcpServers": {
            "huawei-cloud": {
                "command": python_path,
                "args": ["-m", "mcp_hwc"]
            }
        }
    }
    import json
    print(json.dumps(config, indent=2))

def main() -> None:
    parser = argparse.ArgumentParser(description="Huawei Cloud MCP Server")
    parser.add_argument("--generate-config", action="store_true", help="Generate MCP client configuration")
    args, unknown = parser.parse_known_args()

    if args.generate_config:
        generate_config()
        return

    mcp.run(transport="stdio")
