import pytest
from mcp.server.fastmcp import FastMCP
from mcp_hwc.routers.obs import register_obs_tools
from mcp_hwc.routers.k8s import register_k8s_tools
from mcp_hwc.routers.pricing import register_pricing_tools

@pytest.mark.anyio
async def test_obs_tools_registration():
    mcp = FastMCP("test")
    register_obs_tools(mcp)
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "obs_list_buckets" in tool_names
    assert "obs_create_bucket" in tool_names
    assert "obs_upload_file" in tool_names

@pytest.mark.anyio
async def test_k8s_tools_registration():
    mcp = FastMCP("test")
    register_k8s_tools(mcp)
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "cce_get_kubeconfig" in tool_names
    assert "k8s_apply_manifest" in tool_names
    assert "helm_install" in tool_names

@pytest.mark.anyio
async def test_pricing_tools_registration():
    mcp = FastMCP("test")
    register_pricing_tools(mcp)
    tools = await mcp.list_tools()
    tool_names = [t.name for t in tools]
    assert "price_quote" in tool_names
    assert "price_discover" in tool_names
