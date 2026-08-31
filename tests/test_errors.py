import pytest
from mcp.server.fastmcp.exceptions import ToolError

from mcp_hwc.core.errors import build_access_denied_hint, is_access_denied
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


def test_is_access_denied_true_for_403_regardless_of_message():
    assert is_access_denied(403, "APIGW.0301", "No permission to access the URL") is True
    assert is_access_denied(403, "Ecs.0000", "anything") is True


def test_is_access_denied_true_for_permission_phrasing_without_status():
    assert is_access_denied(400, None, "The user does not have permission to perform this action")
    assert is_access_denied(None, "IAM.0011", "Access denied.")


@pytest.mark.parametrize(
    "status, code, message",
    [
        (400, "Ecs.0079", "You are forbidden to use market image aacd6941-1467-44c8-8a23-0e42fd383e64."),
        (400, "Ecs.0312", "The instance operation is forbidden in the current state."),
        (409, "VPC.0202", "Deletion forbidden: the resource is still in use."),
    ],
)
def test_is_access_denied_false_for_non_iam_forbidden(status, code, message):
    assert is_access_denied(status, code, message) is False


def test_build_access_denied_hint_surfaces_policy_action_with_context():
    hint = build_access_denied_hint(
        service_display_name="Elastic Cloud Server (ECS)",
        operation="list_servers_details",
        error_code="APIGW.0301",
        error_msg="No permission. Please grant ecs:servers:list to the caller.",
    )
    assert "ecs:servers:list" in hint


def test_build_access_denied_hint_ignores_incidental_colon_token():
    hint = build_access_denied_hint(
        service_display_name="Elastic Cloud Server (ECS)",
        operation="create_servers",
        error_code="Ecs.0079",
        error_msg="You are forbidden to use market image img:base:ubuntu.",
    )
    assert "Grant policy action" not in hint
    assert "create_servers" in hint
