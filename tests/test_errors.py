import pytest
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError
from mcp_hwc.core.service_factory import _run_tool_call
from mcp_hwc.schemas.operations import EcsCreateSchema

def test_run_tool_call_wraps_validation_error():
    def failing_call():
        # Simulate Pydantic validation failure
        EcsCreateSchema(name="missing-region")

    with pytest.raises(ToolError) as exc_info:
        _run_tool_call(failing_call)

    assert "Invalid tool parameters provided" in str(exc_info.value)
    assert "region" in str(exc_info.value)
    assert "Field required" in str(exc_info.value)

def test_run_tool_call_wraps_value_error():
    def failing_call():
        raise ValueError("Something went wrong")

    with pytest.raises(ToolError) as exc_info:
        _run_tool_call(failing_call)

    assert "Something went wrong" in str(exc_info.value)
