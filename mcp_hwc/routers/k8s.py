from __future__ import annotations

from typing import TYPE_CHECKING, Literal

import mcp_hwc.server as server
from mcp_hwc.cloud_services.cli_service import DEFAULT_TOOL_IMAGES, ContainerMount

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

        service = server._get_resolved_sdk_service(
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

        output_path = server._resolve_output_path(
            destination_path,
            prefix=f"{cluster_id[:8]}-",
            suffix=".kubeconfig.json",
        )
        kubeconfig_text = server._serialize_kubeconfig_document(result["response"])
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
            "port_id": result["response"].get("Port-ID") or result["response"].get("port_id"),
            "written": True,
        }

    return server._run_tool_call(export_kubeconfig)


def k8s_resource(
    action: Literal["apply", "get", "wait"],
    kubeconfig_path: str,
    resource: str | None = None,
    manifest: str | None = None,
    manifest_path: str | None = None,
    namespace: str | None = None,
    all_namespaces: bool = False,
    selector: str | None = None,
    field_selector: str | None = None,
    output: str = "yaml",
    validate_manifest: bool = True,
    server_side: bool = False,
    for_condition: str = "condition=Available",
    timeout_seconds: int = 300,
    context: str | None = None,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Manage Kubernetes resources via kubectl: apply, get, or wait.

    action='apply': requires exactly one of manifest or manifest_path.
    action='get': requires resource (e.g. 'pods', 'deployment/my-app').
    action='wait': requires resource; waits up to timeout_seconds for for_condition.
    """

    def run() -> dict[str, object]:
        if action == "apply":
            if bool(manifest) == bool(manifest_path):
                raise ValueError("Provide exactly one of manifest or manifest_path")
        elif not resource:
            raise ValueError(f"resource is required for action='{action}'")
        if action == "wait" and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")

        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("kubectl")
        backend = server.get_cli_service().resolve_backend(
            "kubectl",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = server._prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )

        if action == "apply":
            args_list = [*kubeconfig_args, "apply", "-f"]
            input_text = manifest
            if manifest_path:
                resolved_manifest_path = server._resolve_existing_path(manifest_path)
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

            if namespace:
                args_list.extend(["-n", namespace])
            if not validate_manifest:
                args_list.append("--validate=false")
            if server_side:
                args_list.append("--server-side")

            result = server._execute_cli_tool(
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
                "namespace": namespace,
                "manifest_source": "path" if manifest_path else "inline",
                "applied": True,
            }

        if action == "get":
            args = [*kubeconfig_args, "get", resource, "-o", output]
            if all_namespaces:
                args.append("--all-namespaces")
            elif namespace:
                args.extend(["-n", namespace])
            if selector:
                args.extend(["-l", selector])
            if field_selector:
                args.extend(["--field-selector", field_selector])

            result = server._execute_cli_tool(
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
                "parsed_output": server._parse_json_output(result["stdout"])
                if output == "json"
                else None,
            }

        if action == "wait":
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

            result = server._execute_cli_tool(
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

        raise ValueError(f"Unsupported action '{action}'")

    return server._run_tool_call(run)


def k8s_exec_logs(
    action: Literal["exec", "logs"],
    kubeconfig_path: str,
    pod: str | None = None,
    namespace: str | None = None,
    container: str | None = None,
    command: str | None = None,
    tail_lines: int = 200,
    since: str | None = None,
    previous: bool = False,
    context: str | None = None,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Exec into or fetch logs from a Kubernetes pod via kubectl.

    action='exec': requires pod, namespace, and command.
    action='logs': requires pod; namespace is optional.
    """

    def run() -> dict[str, object]:
        if not pod:
            raise ValueError("pod is required")
        if action == "exec":
            if not namespace:
                raise ValueError("namespace is required for action='exec'")
            if not command or not command.strip():
                raise ValueError("command is required for action='exec'")
        elif action == "logs" and tail_lines <= 0:
            raise ValueError("tail_lines must be greater than zero")

        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("kubectl")
        backend = server.get_cli_service().resolve_backend(
            "kubectl",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = server._prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )

        if action == "exec":
            args = [*kubeconfig_args, "exec", pod, "-n", namespace]
            if container:
                args.extend(["-c", container])
            args.extend(["--", "sh", "-lc", command])

            result = server._execute_cli_tool(
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

        if action == "logs":
            args = [*kubeconfig_args, "logs", pod, "--tail", str(tail_lines)]
            if namespace:
                args.extend(["-n", namespace])
            if container:
                args.extend(["-c", container])
            if since:
                args.extend(["--since", since])
            if previous:
                args.append("--previous")

            result = server._execute_cli_tool(
                "kubectl",
                args,
                execution_backend=backend,
                container_image=resolved_image,
                mounts=mounts,
            )
            return {
                **result,
                "resource_type": "kubernetes",
                "resource": pod,
                "namespace": namespace,
                "container": container,
                "logs": result["stdout"],
            }

        raise ValueError(f"Unsupported action '{action}'")

    return server._run_tool_call(run)


def helm_action(
    action: Literal["install", "upgrade", "uninstall"],
    kubeconfig_path: str,
    release_name: str,
    chart: str | None = None,
    namespace: str | None = None,
    repo: str | None = None,
    version: str | None = None,
    values: str | None = None,
    values_file: str | None = None,
    set_values: dict[str, object] | None = None,
    create_namespace: bool = True,
    install_if_missing: bool = True,
    wait: bool = True,
    timeout_seconds: int | None = None,
    context: str | None = None,
    execution_backend: str = "auto",
    container_image: str | None = None,
) -> dict[str, object]:
    """Install, upgrade, or uninstall a Helm release.

    action='install'/'upgrade': requires chart. timeout_seconds defaults to 600 if not set.
    action='uninstall': chart not needed. timeout_seconds defaults to 300 if not set.
    """
    resolved_timeout = timeout_seconds
    if resolved_timeout is None:
        resolved_timeout = 300 if action == "uninstall" else 600

    def run() -> dict[str, object]:
        if resolved_timeout <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        if action != "uninstall" and not chart:
            raise ValueError(f"chart is required for action='{action}'")

        resolved_image = container_image or DEFAULT_TOOL_IMAGES.get("helm")
        backend = server.get_cli_service().resolve_backend(
            "helm",
            backend=execution_backend,
            container_image=resolved_image,
        )
        kubeconfig_args, mounts = server._prepare_kubeconfig_for_backend(
            kubeconfig_path,
            context=context,
            backend=backend,
        )

        if action == "uninstall":
            args = [*kubeconfig_args, "uninstall", release_name]
            if namespace:
                args.extend(["--namespace", namespace])
            if wait:
                args.extend(["--wait", "--timeout", f"{resolved_timeout}s"])

            result = server._execute_cli_tool(
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

        effective_chart, chart_mounts = server._prepare_chart_reference(chart, backend=backend)
        mounts.extend(chart_mounts)

        values_path, delete_values_file = server._prepare_helm_values_file(values, values_file)
        try:
            verb = "install" if action == "install" else "upgrade"
            args = [*kubeconfig_args, verb, release_name, effective_chart]
            if action == "install" and create_namespace:
                args.append("--create-namespace")
            if action == "upgrade" and install_if_missing:
                args.append("--install")
            if namespace:
                args.extend(["--namespace", namespace])
            if repo:
                args.extend(["--repo", repo])
            if version:
                args.extend(["--version", version])
            if wait:
                args.extend(["--wait", "--timeout", f"{resolved_timeout}s"])
            if values_path is not None:
                if backend == "container":
                    mounted_values_path = "/tmp/mcp-hwc-helm-values.yaml"
                    mounts.append(ContainerMount(values_path, mounted_values_path, read_only=True))
                    args.extend(["--values", mounted_values_path])
                else:
                    args.extend(["--values", str(values_path)])
            for key, value in sorted((set_values or {}).items()):
                args.extend(["--set", f"{key}={server._format_cli_value(value)}"])

            result = server._execute_cli_tool(
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
                "installed": action == "install",
                "upgraded": action == "upgrade",
            }
        finally:
            if values_path is not None and delete_values_file:
                values_path.unlink(missing_ok=True)

    return server._run_tool_call(run)


def register_k8s_tools(mcp: FastMCP):
    mcp.tool()(cce_get_kubeconfig)
    mcp.tool()(k8s_resource)
    mcp.tool()(k8s_exec_logs)
    mcp.tool()(helm_action)
