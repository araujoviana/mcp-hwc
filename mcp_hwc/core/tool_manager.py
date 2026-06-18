from __future__ import annotations
import asyncio
from typing import Any, Callable, Dict, List, Optional, TypeVar
from pydantic import BaseModel
from mcp.server.fastmcp import FastMCP

T = TypeVar("T")

class Toolset:
    def __init__(self, name: str, description: str):
        self.name = name
        self.description = description
        self.tools: Dict[str, Callable] = {}
        # Internal FastMCP to manage schemas
        self._mcp = FastMCP(name)

    def add_tool(self, func: Callable):
        self.tools[func.__name__] = func
        self._mcp.tool()(func)

    async def get_tool_schemas(self) -> List[Any]:
        return await self._mcp.list_tools()

class ToolManager:
    def __init__(self):
        self.toolsets: Dict[str, Toolset] = {}
        self.loaded_toolsets: set[str] = set()

    def register_toolset(self, toolset: Toolset):
        self.toolsets[toolset.name] = toolset

    def list_available_toolsets(self) -> List[Dict[str, str]]:
        return [
            {
                "name": name,
                "description": ts.description,
                "status": "loaded" if name in self.loaded_toolsets else "available"
            }
            for name, ts in self.toolsets.items()
        ]

    async def load_toolset(self, mcp: FastMCP, toolset_name: str, force: bool = False) -> str:
        if toolset_name not in self.toolsets:
            raise ValueError(f"Toolset '{toolset_name}' not found")

        if toolset_name in self.loaded_toolsets and not force:
            return f"Toolset '{toolset_name}' is already loaded."

        ts = self.toolsets[toolset_name]
        for func in ts.tools.values():
            mcp.tool()(func)

        self.loaded_toolsets.add(toolset_name)
        return f"Successfully loaded {len(ts.tools)} tools from toolset '{toolset_name}'."

tool_manager = ToolManager()
