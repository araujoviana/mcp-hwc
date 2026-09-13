from __future__ import annotations

import base64
import subprocess
from unittest.mock import MagicMock, patch

import pytest

from mcp_hwc.workflows.swr_workflow import (
    decode_swr_auth,
    looks_like_existing_resource_error,
    normalize_registry_host,
    upload_swr_image,
)


def test_looks_like_existing_resource_error() -> None:
    assert looks_like_existing_resource_error("Resource already exists") is True
    assert looks_like_existing_resource_error("Duplicate namespace") is True
    assert looks_like_existing_resource_error("Conflict on name") is True
    # Crucial fix: "does not exist" should NOT be treated as already existing
    assert looks_like_existing_resource_error("Repository does not exist") is False
    assert looks_like_existing_resource_error("Namespace not exist") is False


def test_decode_swr_auth() -> None:
    encoded = base64.b64encode(b"myuser:mypassword123").decode("utf-8")
    user, pwd = decode_swr_auth(encoded)
    assert user == "myuser"
    assert pwd == "mypassword123"


def test_normalize_registry_host() -> None:
    assert normalize_registry_host("https://swr.sa-brazil-1.myhuaweicloud.com/") == "swr.sa-brazil-1.myhuaweicloud.com"
    assert normalize_registry_host("swr.sa-brazil-1.myhuaweicloud.com") == "swr.sa-brazil-1.myhuaweicloud.com"


def test_upload_swr_image_flow_and_logout() -> None:
    mock_service = MagicMock()
    mock_service.call_operation.side_effect = [
        # create_namespace
        {"response": {}},
        # create_repo
        {"response": {}},
        # create_authorization_token
        {
            "response": {
                "auths": {
                    "swr.sa-brazil-1.myhuaweicloud.com": {
                        "auth": base64.b64encode(b"u:p").decode("utf-8")
                    }
                },
                "x-swr-expireat": "2026-09-14T00:00:00Z",
            }
        },
    ]

    executed_cmds = []

    def fake_run(cmd, input_text=None):
        executed_cmds.append(cmd)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="ok", stderr="")

    with patch("mcp_hwc.workflows.swr_workflow.resolve_container_cli", return_value="docker"), \
         patch("mcp_hwc.workflows.swr_workflow.run_local_command", side_effect=fake_run):
        result = upload_swr_image(
            mock_service,
            source_image="local/my-app:v1",
            namespace="my-org",
            repository="my-app",
            tag="v1",
            region="sa-brazil-1",
        )

    assert result["authorization_expires_at"] == "2026-09-14T00:00:00Z"
    assert result["target_image"] == "swr.sa-brazil-1.myhuaweicloud.com/my-org/my-app:v1"

    # Verify docker login, tag, push, and logout were called in order
    assert len(executed_cmds) == 4
    assert executed_cmds[0] == ["docker", "login", "--username", "u", "--password-stdin", "swr.sa-brazil-1.myhuaweicloud.com"]
    assert executed_cmds[1] == ["docker", "tag", "local/my-app:v1", "swr.sa-brazil-1.myhuaweicloud.com/my-org/my-app:v1"]
    assert executed_cmds[2] == ["docker", "push", "swr.sa-brazil-1.myhuaweicloud.com/my-org/my-app:v1"]
    assert executed_cmds[3] == ["docker", "logout", "swr.sa-brazil-1.myhuaweicloud.com"]
