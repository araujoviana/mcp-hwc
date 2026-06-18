import base64
import io
import json
from types import SimpleNamespace
import zipfile

import os
import pytest
from mcp.server.fastmcp.exceptions import ToolError

@pytest.fixture(autouse=True)
def setup_env(monkeypatch):
    monkeypatch.setenv("HWC_AK", "fake-ak")
    monkeypatch.setenv("HWC_SK", "fake-sk")
from mcp.shared.memory import create_connected_server_and_client_session

from mcp_hwc import server
from mcp_hwc.cloud_services.obs_service import ObsServiceError


class FakeObsService:
    def list_buckets(self) -> dict[str, object]:
        return {
            "endpoint": "https://obs.myhuaweicloud.com",
            "bucket_count": 1,
            "buckets": [
                {
                    "name": "alpha",
                    "location": "ap-southeast-1",
                    "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
                    "created_at": None,
                }
            ],
        }

    def create_bucket(
        self,
        bucket_name: str,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "location": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "created": True,
        }

    def list_objects(
        self,
        bucket_name: str,
        prefix: str | None = None,
        max_keys: int = 100,
        marker: str | None = None,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "prefix": prefix,
            "max_keys": max_keys,
            "marker": marker,
            "objects": [{"key": "notes.txt", "size": 4}],
            "common_prefixes": [],
            "is_truncated": False,
            "next_marker": None,
            "location": "ap-southeast-1",
        }

    def get_bucket_location(self, bucket_name: str) -> dict[str, str]:
        return {
            "bucket": bucket_name,
            "location": "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
        }

    def head_bucket(
        self,
        bucket_name: str,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "status": 200,
            "request_id": "req-1",
        }

    def get_object_text(
        self,
        bucket_name: str,
        object_key: str,
        encoding: str = "utf-8",
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "encoding": encoding,
            "size_bytes": 4,
            "text": "demo",
        }

    def head_object(
        self,
        bucket_name: str,
        object_key: str,
        version_id: str | None = None,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "etag": "etag-1",
            "content_length": 4,
            "content_type": "text/plain",
            "last_modified": "2026-01-01T00:00:00.000Z",
            "version_id": version_id,
            "metadata": {},
        }

    def put_text_object(
        self,
        bucket_name: str,
        object_key: str,
        content: str,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "etag": "etag-1",
            "version_id": None,
            "object_url": f"https://example/{bucket_name}/{object_key}",
        }

    def upload_file(
        self,
        bucket_name: str,
        source_path: str,
        object_key: str | None = None,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "key": object_key or "payload.bin",
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "source_path": source_path,
            "size_bytes": 4,
            "etag": "etag-upload",
            "version_id": None,
            "object_url": f"https://example/{bucket_name}/{object_key or 'payload.bin'}",
        }

    def download_object(
        self,
        bucket_name: str,
        object_key: str,
        destination_path: str,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "destination_path": destination_path,
            "size_bytes": 4,
            "etag": None,
            "downloaded": True,
        }

    def delete_object(
        self,
        bucket_name: str,
        object_key: str,
        version_id: str | None = None,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "version_id": version_id,
            "deleted": True,
        }

    def delete_bucket(
        self,
        bucket_name: str,
        region: str | None = None,
    ) -> dict[str, object]:
        return {
            "bucket": bucket_name,
            "region": region or "ap-southeast-1",
            "endpoint": "https://obs.ap-southeast-1.myhuaweicloud.com",
            "deleted": True,
        }


class FakeSdkService:
    def __init__(self, service_name: str):
        self._service_name = service_name

    def list_operations(
        self,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        return {
            "service": self._service_name,
            "region": "ap-southeast-1",
            "endpoint": f"https://{self._service_name}.ap-southeast-1.myhuaweicloud.com",
            "total_count": 1,
            "returned_count": 1,
            "offset": offset,
            "limit": limit,
            "operations": [f"{self._service_name}_demo_operation"],
        }

    def describe_operation(
        self,
        operation: str,
        max_depth: int = 4,
    ) -> dict[str, object]:
        return {
            "service": self._service_name,
            "operation": operation,
            "request_model": "DemoRequest",
            "request_schema": {"kind": "object", "model": "DemoRequest", "fields": []},
            "request_template": {},
            "notes": "demo",
        }

    def call_operation(
        self,
        operation: str,
        parameters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        return {
            "service": self._service_name,
            "operation": operation,
            "region": "ap-southeast-1",
            "endpoint": f"https://{self._service_name}.ap-southeast-1.myhuaweicloud.com",
            "response": {"ok": True, "parameters": parameters or {}},
        }


class FakeSshService:
    def execute(self, **kwargs) -> dict[str, object]:
        return {
            "host": kwargs["host"],
            "port": kwargs["port"],
            "username": kwargs["username"],
            "command": kwargs["command"],
            "exit_status": 0,
            "stdout": "ok",
            "stderr": "",
        }

    def upload_file(self, **kwargs) -> dict[str, object]:
        return {
            "host": kwargs["host"],
            "port": kwargs["port"],
            "username": kwargs["username"],
            "local_path": kwargs["local_path"],
            "remote_path": kwargs["remote_path"],
            "size_bytes": 4,
            "uploaded": True,
        }

    def download_file(self, **kwargs) -> dict[str, object]:
        return {
            "host": kwargs["host"],
            "port": kwargs["port"],
            "username": kwargs["username"],
            "remote_path": kwargs["remote_path"],
            "local_path": kwargs["local_path"],
            "size_bytes": 4,
            "downloaded": True,
        }


class FakeCliService:
    def __init__(self, backend: str = "local", stdout: str = "ok\n"):
        self.backend = backend
        self.stdout = stdout
        self.calls: list[tuple[str, object]] = []

    def resolve_backend(self, tool_name: str, *, backend: str = "auto", container_image=None):
        self.calls.append(("resolve_backend", {"tool_name": tool_name, "backend": backend, "container_image": container_image}))
        return self.backend if backend == "auto" else backend

    def execute_local(self, tool_name: str, args, **kwargs) -> dict[str, object]:
        self.calls.append(("execute_local", {"tool_name": tool_name, "args": list(args), **kwargs}))
        return {
            "backend": "local",
            "command": [tool_name, *args],
            "exit_status": 0,
            "stdout": self.stdout,
            "stderr": "",
        }

    def execute_container(self, *, image: str, entrypoint: str, args, mounts=None, **kwargs) -> dict[str, object]:
        self.calls.append(("execute_container", {"image": image, "entrypoint": entrypoint, "args": list(args), "mounts": mounts or [], **kwargs}))
        return {
            "backend": "container",
            "command": [entrypoint, *args],
            "exit_status": 0,
            "stdout": self.stdout,
            "stderr": "",
        }


def test_tool_function_calls_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_obs_service", lambda: FakeObsService())

    result = server.obs_list_objects("demo-bucket", prefix="docs/", max_keys=10)

    assert result["bucket"] == "demo-bucket"
    assert result["objects"][0]["key"] == "notes.txt"


def test_tool_errors_are_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    failing_service = SimpleNamespace(
        list_buckets=lambda: (_ for _ in ()).throw(ObsServiceError("boom"))
    )
    monkeypatch.setattr(server, "get_obs_service", lambda: failing_service)

    with pytest.raises(ToolError, match="boom"):
        server.obs_list_buckets()


def test_capability_summary_tool_calls_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server,
        "summarize_service_capabilities",
        lambda service_name, api_version=None, focus=None: {
            "service": service_name,
            "api_version": api_version,
            "focus": focus,
            "operation_count": 1,
        },
    )

    result = server.huaweicloud_summarize_capabilities(
        "cce",
        focus="node pool",
        api_version="v3",
    )

    assert result["service"] == "cce"
    assert result["focus"] == "node pool"
    assert result["api_version"] == "v3"


def test_defaults_tool_calls_helper(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server,
        "resolve_service_defaults",
        lambda service_name, region=None, intent="small", exposure="auto": {
            "service": service_name,
            "region": region,
            "intent": intent,
            "exposure": exposure,
        },
    )

    result = server.huaweicloud_resolve_defaults(
        "ecs",
        region="la-south-2",
        intent="balanced",
        exposure="public",
    )

    assert result["service"] == "ecs"
    assert result["region"] == "la-south-2"
    assert result["intent"] == "balanced"
    assert result["exposure"] == "public"


def test_ecs_tool_function_calls_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "get_ecs_service", lambda *args, **kwargs: FakeSdkService("ecs")
    )

    result = server.ecs_call_operation(
        "create_servers",
        parameters={"body": {"server": {"name": "web-01"}}},
        region="ap-southeast-1",
    )

    assert result["service"] == "ecs"
    assert result["response"]["ok"] is True


def test_ecs_create_vm_uses_compact_workflow_without_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, object]] = []

    class FakeWorkflowService:
        def __init__(self, service_name: str):
            self.service_name = service_name

        def call_operation(self, operation: str, parameters=None) -> dict[str, object]:
            calls.append((self.service_name, operation, parameters))
            if self.service_name == "vpc":
                if operation == "list_vpcs":
                    return {"response": {"vpcs": [{"id": "vpc-1", "name": "vpc-default"}]}}
                if operation == "list_subnets":
                    return {"response": {"subnets": [{"id": "subnet-1", "name": "subnet-default"}]}}
                if operation == "show_subnet":
                    return {"response": {"subnet": {"id": "subnet-1", "cidr": "192.168.0.0/24"}}}
                if operation == "create_security_group":
                    return {"response": {"security_group": {"id": "sg-1"}}}
                if operation == "create_security_group_rule":
                    return {"response": {"security_group_rule": {"id": "rule-1"}}}
            if self.service_name == "ims" and operation == "list_images":
                return {
                    "response": {
                        "images": [
                            {
                                "id": "image-1",
                                "name": "Ubuntu 24.04",
                                "status": "active",
                                "__platform": "Ubuntu",
                                "__os_version": "Ubuntu 24.04 server 64bit",
                                "__os_type": "Linux",
                            }
                        ]
                    }
                }
            if self.service_name == "ecs":
                if operation == "list_flavors":
                    return {
                        "response": {
                            "flavors": [
                                {
                                    "id": "ac8.large.2",
                                    "vcpus": "2",
                                    "ram": 4096,
                                    "os_extra_specs": {"cond:operation:az": "la-south-2a(normal)"},
                                }
                            ]
                        }
                    }
                if operation == "create_servers":
                    return {
                        "service": "ecs",
                        "region": "la-south-2",
                        "response": {"job_id": "job-1", "server_ids": ["server-1"]},
                    }
            raise AssertionError((self.service_name, operation, parameters))

    monkeypatch.setattr(
        server,
        "_get_resolved_sdk_service",
        lambda service_name, *args, **kwargs: FakeWorkflowService(service_name),
    )

    result = server.ecs_create_vm(
        region="santiago",
        name="web-01",
        ssh_cidr="189.40.74.88/32",
        return_password=False,
    )

    assert result["created"] is True
    assert result["waited"] is False
    assert result["job_id"] == "job-1"
    assert result["server_ids"] == ["server-1"]
    assert result["selected"]["vpc_id"] == "vpc-1"
    assert result["selected"]["image_id"] == "image-1"
    assert result["login"]["password_returned"] is False
    assert ("ecs", "show_job") not in [(service_name, operation) for service_name, operation, _ in calls]


def test_functiongraph_deploy_code_builds_zip_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    source_file = tmp_path / "index.py"
    source_file.write_text("def handler(event, context):\n    return 'ok'\n")
    captured: dict[str, object] = {}

    class FakeFunctionGraphService:
        def call_operation(self, operation: str, parameters=None) -> dict[str, object]:
            captured["operation"] = operation
            captured["parameters"] = parameters
            return {
                "service": "functiongraph",
                "operation": operation,
                "region": "ap-southeast-1",
                "endpoint": "https://functiongraph.ap-southeast-1.myhuaweicloud.com",
                "response": {"func_urn": "urn:fss:demo", "func_name": "hello"},
            }

    monkeypatch.setattr(
        server,
        "_get_resolved_sdk_service",
        lambda *args, **kwargs: FakeFunctionGraphService(),
    )

    result = server.functiongraph_deploy_code(
        source_path=str(source_file),
        region="ap-southeast-1",
        func_name="hello",
        runtime="Python3.9",
        handler="index.handler",
    )

    assert captured["operation"] == "create_function"
    body = captured["parameters"]["body"]
    assert body["code_type"] == "zip"
    encoded_archive = body["func_code"]["file"]
    archive_bytes = base64.b64decode(encoded_archive)
    with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
        assert archive.namelist() == ["index.py"]
    assert result["response"]["func_urn"] == "urn:fss:demo"
    assert result["archive_size_bytes"] > 0


def test_lts_query_logs_resolves_names_and_filters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []

    class FakeLtsService:
        def call_operation(self, operation: str, parameters=None) -> dict[str, object]:
            calls.append((operation, parameters))
            if operation == "list_log_groups":
                return {
                    "response": {
                        "log_groups": [
                            {"log_group_id": "group-1", "log_group_name": "app-logs"}
                        ]
                    }
                }
            if operation == "list_log_streams":
                return {
                    "response": {
                        "log_streams": [
                            {"log_stream_id": "stream-1", "log_stream_name": "web"}
                        ]
                    }
                }
            if operation == "list_logs":
                assert parameters["log_group_id"] == "group-1"
                assert parameters["log_stream_id"] == "stream-1"
                return {
                    "service": "lts",
                    "operation": operation,
                    "region": "ap-southeast-1",
                    "endpoint": "https://lts.ap-southeast-1.myhuaweicloud.com",
                    "response": {
                        "logs": [
                            {"content": "ERROR failed request", "line_num": "1"},
                            {"content": "INFO ok", "line_num": "2"},
                        ]
                    },
                }
            raise AssertionError(operation)

    monkeypatch.setattr(
        server,
        "_get_resolved_sdk_service",
        lambda *args, **kwargs: FakeLtsService(),
    )

    result = server.lts_query_logs(
        log_group_name="app-logs",
        log_stream_name="web",
        region="ap-southeast-1",
        keywords="ERROR",
        contains_text="failed",
    )

    assert calls[0][0] == "list_log_groups"
    assert calls[1][0] == "list_log_streams"
    assert calls[2][0] == "list_logs"
    assert result["matched_count"] == 1
    assert result["logs"][0]["content"] == "ERROR failed request"


def test_swr_upload_image_creates_repo_and_pushes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service_calls: list[tuple[str, object]] = []
    command_calls: list[tuple[list[str], str | None]] = []
    auth_token = base64.b64encode(b"demo:secret").decode("ascii")

    class FakeSwrService:
        def call_operation(self, operation: str, parameters=None) -> dict[str, object]:
            service_calls.append((operation, parameters))
            if operation in {"create_namespace", "create_repo"}:
                return {"response": {"ok": True}}
            if operation == "create_authorization_token":
                return {
                    "response": {
                        "auths": {
                            "swr.ap-southeast-1.myhuaweicloud.com": {"auth": auth_token}
                        },
                        "x_swr_expireat": "2099-01-01T00:00:00Z",
                    }
                }
            raise AssertionError(operation)

    def fake_run(command, input=None, text=None, capture_output=None, check=None):
        command_calls.append((command, input))
        return SimpleNamespace(returncode=0, stdout="ok", stderr="")

    monkeypatch.setattr(
        server,
        "_get_resolved_sdk_service",
        lambda *args, **kwargs: FakeSwrService(),
    )
    monkeypatch.setattr(server.shutil, "which", lambda name: f"/usr/bin/{name}" if name == "docker" else None)
    monkeypatch.setattr(server.subprocess, "run", fake_run)

    result = server.swr_upload_image(
        source_image="local:dev",
        namespace="team",
        repository="app",
        region="ap-southeast-1",
    )

    assert [operation for operation, _ in service_calls] == [
        "create_namespace",
        "create_repo",
        "create_authorization_token",
    ]
    assert command_calls[0][0][:4] == ["docker", "login", "--username", "demo"]
    assert command_calls[1][0] == [
        "docker",
        "tag",
        "local:dev",
        "swr.ap-southeast-1.myhuaweicloud.com/team/app:latest",
    ]
    assert command_calls[2][0] == [
        "docker",
        "push",
        "swr.ap-southeast-1.myhuaweicloud.com/team/app:latest",
    ]
    assert result["pushed"] is True
    assert result["target_image"] == "swr.ap-southeast-1.myhuaweicloud.com/team/app:latest"


def test_cce_get_kubeconfig_writes_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    destination = tmp_path / "cluster.kubeconfig.json"

    class FakeCceService:
        def call_operation(self, operation: str, parameters=None) -> dict[str, object]:
            assert operation == "create_kubernetes_cluster_cert"
            assert parameters["cluster_id"] == "cluster-1"
            return {
                "api_version": "v3",
                "response": {
                    "kind": "Config",
                    "apiVersion": "v1",
                    "preferences": {},
                    "clusters": [{"name": "demo"}],
                    "users": [{"name": "demo-user"}],
                    "contexts": [{"name": "external"}],
                    "current-context": "external",
                },
            }

    monkeypatch.setattr(
        server,
        "_get_resolved_sdk_service",
        lambda *args, **kwargs: FakeCceService(),
    )

    result = server.cce_get_kubeconfig(
        cluster_id="cluster-1",
        region="ap-southeast-1",
        destination_path=str(destination),
    )

    assert result["written"] is True
    assert result["kubeconfig_path"] == str(destination)
    document = json.loads(destination.read_text(encoding="utf-8"))
    assert document["current-context"] == "external"


def test_k8s_get_resources_uses_cli_runner(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("{}", encoding="utf-8")
    fake_cli = FakeCliService(backend="container", stdout='{"items": []}\n')
    monkeypatch.setattr(server, "get_cli_service", lambda: fake_cli)

    result = server.k8s_get_resources(
        kubeconfig_path=str(kubeconfig),
        resource="pods",
        output="json",
    )

    assert result["backend"] == "container"
    assert result["parsed_output"] == {"items": []}
    execute_call = next(call for call in fake_cli.calls if call[0] == "execute_container")
    assert "get" in execute_call[1]["args"]
    assert any(getattr(mount, "target", "") == "/tmp/mcp-hwc-kubeconfig" for mount in execute_call[1]["mounts"])


def test_helm_install_uses_values_and_repo(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    kubeconfig = tmp_path / "kubeconfig"
    kubeconfig.write_text("{}", encoding="utf-8")
    fake_cli = FakeCliService(backend="local", stdout="release installed\n")
    monkeypatch.setattr(server, "get_cli_service", lambda: fake_cli)

    result = server.helm_install(
        kubeconfig_path=str(kubeconfig),
        release_name="nginx",
        chart="ingress-nginx",
        repo="https://kubernetes.github.io/ingress-nginx",
        namespace="ingress-nginx",
        values="controller:\n  replicaCount: 1\n",
        set_values={"controller.service.type": "LoadBalancer"},
    )

    assert result["installed"] is True
    execute_call = next(call for call in fake_cli.calls if call[0] == "execute_local")
    args = execute_call[1]["args"]
    assert "install" in args
    assert "--repo" in args
    assert "https://kubernetes.github.io/ingress-nginx" in args
    assert any(item.startswith("controller.service.type=LoadBalancer") for item in args)


def test_ecs_tool_infers_region_from_parameters(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured = {}

    def fake_get_ecs_service(*args, **kwargs):
        captured.update(kwargs)
        return FakeSdkService("ecs")

    monkeypatch.setattr(server, "get_ecs_service", fake_get_ecs_service)

    server.ecs_call_operation(
        "create_servers",
        parameters={"body": {"region": "ap-southeast-1"}},
    )

    assert captured["region"] == "ap-southeast-1"


def test_vpc_tool_function_calls_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "get_vpc_service", lambda *args, **kwargs: FakeSdkService("vpc")
    )

    result = server.vpc_list_operations(query="list_vpc", limit=5)

    assert result["service"] == "vpc"
    assert result["operations"][0] == "vpc_demo_operation"


def test_huaweicloud_list_services_includes_taurusdb() -> None:
    result = server.huaweicloud_list_services(query="taurus")

    assert any(service["service"] == "taurusdb" for service in result["services"])


def test_generic_tool_resolves_service_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server,
        "get_taurusdb_service",
        lambda *args, **kwargs: FakeSdkService("taurusdb"),
    )

    result = server.huaweicloud_call_operation(
        service_name="TaurusDB",
        operation="create_instance",
        parameters={"body": {"name": "db-01"}},
        region="ap-southeast-1",
    )

    assert result["service"] == "taurusdb"
    assert result["response"]["ok"] is True


def test_wait_for_condition_polls_until_match(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, object]] = []
    sleep_calls: list[float] = []
    responses = iter(
        [
            {
                "service": "rds",
                "region": "la-south-2",
                "endpoint": "https://rds.la-south-2.myhuaweicloud.com",
                "response": {"instances": [{"status": "BUILD"}]},
            },
            {
                "service": "rds",
                "region": "la-south-2",
                "endpoint": "https://rds.la-south-2.myhuaweicloud.com",
                "response": {"instances": [{"status": "ACTIVE"}]},
            },
        ]
    )

    class FakePollingService:
        def call_operation(self, operation: str, parameters=None) -> dict[str, object]:
            calls.append((operation, parameters))
            return next(responses)

    monkeypatch.setattr(
        server,
        "_get_resolved_sdk_service",
        lambda *args, **kwargs: FakePollingService(),
    )
    monkeypatch.setattr(server.time, "sleep", sleep_calls.append)

    result = server.huaweicloud_wait_for_condition(
        service_name="rds",
        operation="list_instances",
        parameters={"id": "instance-1"},
        response_path="response.instances[0].status",
        expected_value="ACTIVE",
        region="la-south-2",
        timeout_seconds=120,
        interval_seconds=1,
    )

    assert len(calls) == 2
    assert sleep_calls == [server._MIN_POLL_INTERVAL_SECONDS]
    assert result["matched"] is True
    assert result["value"] == "ACTIVE"
    assert result["last_result"]["response"]["instances"][0]["status"] == "ACTIVE"


def test_postgres_execute_sql_uses_cli_runner(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_cli = FakeCliService(backend="container", stdout="PostgreSQL 16.10\n")
    monkeypatch.setattr(server, "get_cli_service", lambda: fake_cli)

    result = server.postgres_execute_sql(
        host="176.52.138.63",
        port=5432,
        username="root",
        password="secret",
        database="postgres",
        sql="select version();",
    )

    assert result["backend"] == "container"
    assert result["row_count"] == 1
    assert result["rows"] == [["PostgreSQL 16.10"]]
    execute_call = next(call for call in fake_cli.calls if call[0] == "execute_container")
    assert execute_call[1]["entrypoint"] == "psql"
    assert "--host" in execute_call[1]["args"]
    assert execute_call[1]["env"]["PGPASSWORD"] == "secret"
    assert execute_call[1]["env"]["PGSSLMODE"] == "require"


def test_sfs_create_accessible_share_orchestrates_workflow(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, str, object]] = []

    class FakeWorkflowService:
        def __init__(self, service_name: str):
            self.service_name = service_name

        def call_operation(self, operation: str, parameters=None) -> dict[str, object]:
            calls.append((self.service_name, operation, parameters))
            if self.service_name == "vpc":
                if operation == "list_vpcs":
                    return {"response": {"vpcs": [{"id": "vpc-1", "name": "vpc-default"}]}}
                if operation == "list_subnets":
                    return {"response": {"subnets": [{"id": "subnet-1", "name": "subnet-default"}]}}
                if operation == "show_subnet":
                    return {"response": {"subnet": {"id": "subnet-1", "cidr": "192.168.0.0/24"}}}
                if operation == "create_security_group":
                    return {"response": {"security_group": {"id": "sg-1"}}}
                if operation == "create_security_group_rule":
                    return {"response": {"security_group_rule": {"id": "rule-ssh"}}}
            if self.service_name == "sfs":
                if operation == "list_share_types":
                    return {
                        "response": {
                            "share_types": [
                                {
                                    "share_type": "standard",
                                    "available_zones": [
                                        {"available_zone": "la-south-2a", "status": "active"}
                                    ],
                                }
                            ]
                        }
                    }
                if operation == "create_share":
                    return {"response": {"id": "share-1"}}
                if operation == "show_share":
                    return {
                        "response": {
                            "id": "share-1",
                            "name": "demo-share",
                            "status": "200",
                            "export_location": "192.168.0.2:/",
                            "optional_endpoint": "192.168.0.2",
                        }
                    }
                if operation == "list_perm_rules":
                    return {
                        "response": {
                            "rules": [
                                {"id": "wild-1", "ip_cidr": "*"},
                            ]
                        }
                    }
                if operation == "delete_perm_rule":
                    return {"response": {}}
                if operation == "create_perm_rule":
                    return {"response": {"rules": [{"id": "perm-1"}]}}
            if self.service_name == "ims":
                if operation == "list_images":
                    return {
                        "response": {
                            "images": [
                                {
                                    "id": "image-1",
                                    "status": "active",
                                    "__platform": "Ubuntu",
                                    "__os_version": "Ubuntu 24.04 server 64bit",
                                    "__os_type": "Linux",
                                }
                            ]
                        }
                    }
            if self.service_name == "ecs":
                if operation == "list_flavors":
                    return {
                        "response": {
                            "flavors": [
                                {
                                    "id": "ac8.large.2",
                                    "vcpus": "2",
                                    "ram": 4096,
                                    "os_extra_specs": {"cond:operation:az": "la-south-2a(normal),la-south-2b(normal)"},
                                }
                            ]
                        }
                    }
                if operation == "create_servers":
                    return {"response": {"job_id": "job-1"}}
                if operation == "show_job":
                    return {"response": {"status": "SUCCESS"}}
                if operation == "list_servers_details":
                    return {
                        "response": {
                            "servers": [
                                {
                                    "id": "server-1",
                                    "name": "demo-share-client",
                                    "addresses": {
                                        "net-1": [
                                            {"addr": "192.168.0.10", "OS-EXT-IPS:type": "fixed"},
                                            {"addr": "101.44.13.13", "OS-EXT-IPS:type": "floating"},
                                        ]
                                    },
                                }
                            ]
                        }
                    }
            raise AssertionError((self.service_name, operation, parameters))

    class FakeWorkflowSshService:
        def __init__(self):
            self.commands: list[str] = []

        def execute(self, **kwargs) -> dict[str, object]:
            command = kwargs["command"]
            self.commands.append(command)
            stdout = "ok\n"
            if command.startswith("cat "):
                stdout = "sfs proof 2026-04-28T01:06:31Z\n"
            elif command.startswith("df -h "):
                stdout = "Filesystem      Size  Used Avail Use% Mounted on\n192.168.0.2:/   500G     0  500G   0% /mnt/sfs-demo\n"
            elif command.startswith("mount | grep"):
                stdout = "192.168.0.2:/ on /mnt/sfs-demo type nfs (... )\n"
            elif command.startswith("ls -la "):
                stdout = "proof.txt\nproof-2.txt\n"
            return {
                "host": kwargs["host"],
                "port": 22,
                "username": kwargs["username"],
                "command": command,
                "exit_status": 0,
                "stdout": stdout,
                "stderr": "",
            }

    fake_ssh = FakeWorkflowSshService()
    monkeypatch.setattr(
        server,
        "_get_resolved_sdk_service",
        lambda service_name, *args, **kwargs: FakeWorkflowService(service_name),
    )
    monkeypatch.setattr(server, "get_ssh_service", lambda: fake_ssh)

    result = server.sfs_create_accessible_share(
        region="la-south-2",
        client_cidr="189.40.74.88/32",
        share_name="demo-share",
        access_vm_name="demo-share-client",
        access_vm_password="Secret123!",
    )

    assert result["share"]["id"] == "share-1"
    assert result["share"]["export_location"] == "192.168.0.2:/"
    assert result["access_vm"]["public_ip"] == "101.44.13.13"
    assert result["access_vm"]["password"] == "Secret123!"
    assert result["proof"]["proof_text"] == "sfs proof 2026-04-28T01:06:31Z"
    assert any("mount -t nfs" in command for command in fake_ssh.commands)


def test_obs_upload_file_calls_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_obs_service", lambda: FakeObsService())

    result = server.obs_upload_file(
        bucket_name="demo-bucket",
        source_path="./payload.bin",
        object_key="payload.bin",
    )

    assert result["key"] == "payload.bin"
    assert result["size_bytes"] == 4


def test_ssh_execute_calls_service(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_ssh_service", lambda: FakeSshService())

    result = server.ssh_execute(
        host="10.0.0.10",
        username="root",
        command="uname -a",
    )

    assert result["exit_status"] == 0
    assert result["stdout"] == "ok"


@pytest.mark.anyio
async def test_mcp_session_can_call_obs_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_obs_service", lambda: FakeObsService())

    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as session:
        result = await session.call_tool("obs_list_buckets", {})

    assert result.isError is False
    assert result.structuredContent["bucket_count"] == 1
    assert result.structuredContent["buckets"][0]["name"] == "alpha"


@pytest.mark.anyio
async def test_mcp_session_can_call_generic_sdk_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        server, "get_rds_service", lambda *args, **kwargs: FakeSdkService("rds")
    )

    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as session:
        result = await session.call_tool("huaweicloud_list_operations", {"service_name": "rds"})

    assert result.isError is False
    assert result.structuredContent["service"] == "rds"
    assert result.structuredContent["operations"][0] == "rds_demo_operation"


@pytest.mark.anyio
async def test_mcp_session_hides_generated_sdk_tools_by_default() -> None:
    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as session:
        tools = await session.list_tools()

    tool_names = {tool.name for tool in tools.tools}
    assert "ims_list_operations" not in tool_names
    assert "ecs_create_vm" in tool_names
    assert "huaweicloud_list_operations" in tool_names


@pytest.mark.anyio
async def test_mcp_session_can_call_ecs_create_vm(monkeypatch: pytest.MonkeyPatch) -> None:
    class FakeWorkflowService:
        def __init__(self, service_name: str):
            self.service_name = service_name

        def call_operation(self, operation: str, parameters=None) -> dict[str, object]:
            if self.service_name == "vpc":
                if operation == "list_vpcs":
                    return {"response": {"vpcs": [{"id": "vpc-1", "name": "vpc-default"}]}}
                if operation == "list_subnets":
                    return {"response": {"subnets": [{"id": "subnet-1", "name": "subnet-default"}]}}
                if operation == "show_subnet":
                    return {"response": {"subnet": {"id": "subnet-1"}}}
                if operation == "create_security_group":
                    return {"response": {"security_group": {"id": "sg-1"}}}
                if operation == "create_security_group_rule":
                    return {"response": {}}
            if self.service_name == "ims" and operation == "list_images":
                return {
                    "response": {
                        "images": [
                            {
                                "id": "image-1",
                                "name": "Ubuntu 24.04",
                                "status": "active",
                                "__platform": "Ubuntu",
                                "__os_version": "Ubuntu 24.04 server 64bit",
                                "__os_type": "Linux",
                            }
                        ]
                    }
                }
            if self.service_name == "ecs":
                if operation == "list_flavors":
                    return {
                        "response": {
                            "flavors": [
                                {
                                    "id": "ac8.large.2",
                                    "vcpus": "2",
                                    "ram": 4096,
                                    "os_extra_specs": {"cond:operation:az": "la-south-2a(normal)"},
                                }
                            ]
                        }
                    }
                if operation == "create_servers":
                    return {"service": "ecs", "region": "la-south-2", "response": {"job_id": "job-1"}}
            raise AssertionError((self.service_name, operation))

    monkeypatch.setattr(
        server,
        "_get_resolved_sdk_service",
        lambda service_name, *args, **kwargs: FakeWorkflowService(service_name),
    )

    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as session:
        result = await session.call_tool("ecs_create_vm", {"region": "la-south-2"})

    assert result.isError is False
    assert result.structuredContent["created"] is True
    assert result.structuredContent["job_id"] == "job-1"


@pytest.mark.anyio
async def test_mcp_session_can_call_ssh_tool(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(server, "get_ssh_service", lambda: FakeSshService())

    async with create_connected_server_and_client_session(
        server.mcp, raise_exceptions=True
    ) as session:
        result = await session.call_tool(
            "ssh_execute",
            {"host": "10.0.0.10", "username": "root", "command": "id"},
        )

    assert result.isError is False
    assert result.structuredContent["exit_status"] == 0
