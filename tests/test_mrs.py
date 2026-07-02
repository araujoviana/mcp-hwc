import pytest
from unittest.mock import MagicMock
import mcp_hwc.server as server
from mcp_hwc.routers.mrs import mrs_list_node_ips, register_mrs_tools
from mcp.server.fastmcp import FastMCP

@pytest.mark.anyio
async def test_mrs_tools_registration():
    mcp = FastMCP("test")
    register_mrs_tools(mcp)
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "mrs_list_node_ips" in tool_names

def test_mrs_list_node_ips(monkeypatch):
    mock_service = MagicMock()
    mock_service.call_operation.return_value = {
        "api_version": "v2",
        "response": {
            "node_total": 2,
            "nodes": [
                {
                    "node_name": "mrs-node-1",
                    "node_type": "master",
                    "node_group_name": "master_node_default_group",
                    "node_status": "Running",
                    "server_info": {
                        "internal_ip": "192.168.0.10"
                    }
                },
                {
                    "node_name": "mrs-node-2",
                    "node_type": "core",
                    "node_group_name": "core_node_default_group",
                    "node_status": "Running",
                    "server_info": {
                        "internal_ip": "192.168.0.11"
                    }
                }
            ]
        }
    }

    monkeypatch.setattr(server, "_get_resolved_sdk_service", lambda *args, **kwargs: mock_service)

    result = mrs_list_node_ips(cluster_id="cluster-123", region="cn-north-4")

    assert result["cluster_id"] == "cluster-123"
    assert len(result["nodes"]) == 2
    assert result["nodes"][0]["name"] == "mrs-node-1"
    assert result["nodes"][0]["internal_ip"] == "192.168.0.10"
    assert result["nodes"][1]["name"] == "mrs-node-2"
    assert result["nodes"][1]["internal_ip"] == "192.168.0.11"
