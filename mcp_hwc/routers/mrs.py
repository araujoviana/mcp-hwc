from __future__ import annotations
from typing import TYPE_CHECKING
import mcp_hwc.server as server

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

def mrs_list_node_ips(
    cluster_id: str,
    region: str,
    project_id: str | None = None,
    endpoint: str | None = None,
    api_version: str | None = "v2",
) -> dict[str, object]:
    """Resolve an MRS cluster ID into node names and internal IPs for SSH access."""

    def list_node_ips() -> dict[str, object]:
        service = server._get_resolved_sdk_service(
            "mrs",
            api_version=api_version,
            region=region,
            project_id=project_id,
            endpoint=endpoint,
        )
        # We use v2 for list_nodes as it provides richer node information
        result = service.call_operation(
            "list_nodes",
            {
                "cluster_id": cluster_id,
            },
        )

        nodes = result["response"].get("nodes", [])
        resolved_nodes = []
        for node in nodes:
            node_name = node.get("node_name")
            server_info = node.get("server_info") or {}
            internal_ip = server_info.get("internal_ip")

            if node_name and internal_ip:
                resolved_nodes.append({
                    "name": node_name,
                    "internal_ip": internal_ip,
                    "node_type": node.get("node_type"),
                    "node_group_name": node.get("node_group_name"),
                    "node_status": node.get("node_status"),
                })

        return {
            "service": "mrs",
            "operation": "list_nodes",
            "cluster_id": cluster_id,
            "region": region,
            "nodes": resolved_nodes,
            "total_count": result["response"].get("node_total", len(resolved_nodes)),
            "notes": "Use these internal IPs with `ssh_execute` or other SSH tools if the MCP host has network access to the VPC.",
        }

    return server._run_tool_call(list_node_ips)

def register_mrs_tools(mcp: FastMCP):
    mcp.tool()(mrs_list_node_ips)
