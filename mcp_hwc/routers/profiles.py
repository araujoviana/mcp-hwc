from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_hwc.core import profiles as profiles_core
from mcp_hwc.server import _run_tool_call, clear_caches

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

def hwc_list_profiles() -> dict[str, object]:
    """List available Huawei Cloud credential profiles (.env plus .env.<name> files) and which one is active."""
    return _run_tool_call(profiles_core.list_profiles)

def hwc_switch_profile(name: str) -> dict[str, object]:
    """Switch the active Huawei Cloud account to the given credential profile. All subsequent tool calls use the new account. Returns the profile name and a masked access key, never secrets."""

    def switch() -> dict[str, object]:
        result = profiles_core.switch_profile(name)
        clear_caches()
        return result

    return _run_tool_call(switch)

def register_profile_tools(mcp: FastMCP):
    mcp.tool()(hwc_list_profiles)
    mcp.tool()(hwc_switch_profile)
