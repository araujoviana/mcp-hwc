from __future__ import annotations
from typing import TYPE_CHECKING
from mcp_hwc.server import (
    _run_tool_call,
    _get_resolved_sdk_service,
    _prepare_kubeconfig_for_backend,
    _execute_cli_tool,
    _resolve_output_path,
    _serialize_kubeconfig_document,
    _resolve_existing_path,
    _parse_json_output,
    _prepare_chart_reference,
    _prepare_helm_values_file,
    _format_cli_value,
    get_cli_service,
)
from mcp_hwc.cloud_services.cli_service import DEFAULT_TOOL_IMAGES, ContainerMount
from mcp_hwc.schemas.operations import K8sApplySchema

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

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

def k8s_apply_manifest(
    args: K8sApplySchema
) -> dict[str, object]:
    """Apply a Kubernetes manifest using kubectl."""

    def apply_manifest() -> dict[str, object]:
        if bool(args.manifest) == bool(args.manifest_path):
            raise ValueError("Provide exactly one of manifest or manifest_path")

        resolved_image = args.container_image or DEFAULT_TOOL_IMAGES.get("kubectl")
        backend = get_cli_service().resolve_backend(
            "kubectl",
            backend=args.execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = _prepare_kubeconfig_for_backend(
            args.kubeconfig_path,
            context=args.context,
            backend=backend,
        )

        args_list = [*kubeconfig_args, "apply", "-f"]
        input_text = args.manifest
        if args.manifest_path:
            resolved_manifest_path = _resolve_existing_path(args.manifest_path)
            if backend == "container":
                mounted_manifest_path = "/tmp/mcp-hwc-manifest.yaml"
                mounts.append(
                    ContainerMount(
                        resolved_manifest_path,
                        mounted_manifest_path,
                        read_only=True,
                    )
                )
                args_list.append(mounted_manifest_path)
            else:
                args_list.append(str(resolved_manifest_path))
            input_text = None
        else:
            args_list.append("-")

        if args.namespace:
            args_list.extend(["-n", args.namespace])
        if not args.validate_manifest:
            args_list.append("--validate=false")
        if args.server_side:
            args_list.append("--server-side")

        result = _execute_cli_tool(
            "kubectl",
            args_list,
            execution_backend=backend,
            container_image=resolved_image,
            input_text=input_text,
            mounts=mounts,
        )
        return {
            **result,
            "resource_type": "kubernetes",
            "namespace": args.namespace,
            "manifest_source": "path" if args.manifest_path else "inline",
            "applied": True,
        }

    return _run_tool_call(apply_manifest)

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

def register_k8s_tools(mcp: FastMCP):
    mcp.tool()(cce_get_kubeconfig)
    mcp.tool()(k8s_apply_manifest)
    mcp.tool()(k8s_get_resources)
    mcp.tool()(k8s_wait)
    mcp.tool()(k8s_logs)
    mcp.tool()(k8s_exec)
    mcp.tool()(helm_install)
    mcp.tool()(helm_upgrade)
    mcp.tool()(helm_uninstall)
