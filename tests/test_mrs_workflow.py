import pytest

from mcp_hwc.workflows import mrs


# Fixtures use the camelCase wire names the v1 API actually returns
# (sanitize_for_serialization emits attribute_map keys, e.g. "clusterId").
NORMAL_CLUSTER = {
    "clusterId": "c-123",
    "clusterName": "analytics",
    "clusterState": "running",
    "safeMode": 0,
    "componentList": [
        {"componentName": "Hive"},
        {"componentName": "Spark"},
        {"componentName": "Kafka"},
    ],
    "masterNodeIp": "192.168.0.10",
    "eipAddress": "1.2.3.4",
    "internalIp": "192.168.0.10",
}

KERBEROS_CLUSTER = {
    "clusterId": "c-666",
    "clusterName": "secure",
    "clusterState": "running",
    "safeMode": 1,
    "componentList": [{"componentName": "Hive"}],
    "masterNodeIp": "192.168.0.20",
    "eipAddress": "",
    "internalIp": "192.168.0.20",
}


class FakeSdkService:
    def __init__(self, responses: dict) -> None:
        self.responses = dict(responses)
        self.calls: list[tuple[str, dict]] = []

    def call_operation(self, operation: str, payload: dict | None = None) -> dict:
        self.calls.append((operation, payload or {}))
        return {"response": self.responses[operation]}


class SequencedSdkService(FakeSdkService):
    """call_operation returns queued responses one at a time per operation."""

    def call_operation(self, operation: str, payload: dict | None = None) -> dict:
        self.calls.append((operation, payload or {}))
        queue = self.responses[operation]
        if isinstance(queue, list):
            response = queue.pop(0) if len(queue) > 1 else queue[0]
        else:
            response = queue
        return {"response": response}


class FakeSshService:
    def __init__(self, result: dict | None = None) -> None:
        self.calls: list[dict] = []
        self.result = result or {"exit_status": 0, "stdout": "ok", "stderr": ""}

    def execute(self, **kwargs) -> dict:
        self.calls.append(kwargs)
        return dict(self.result)


def make_factory(services: dict):
    def factory(service_name: str, api_version: str | None = None, **kwargs):
        return services[(service_name, api_version)]

    return factory


def clusters_service(clusters: list[dict]) -> FakeSdkService:
    return FakeSdkService({"list_clusters": {"clusters": clusters}})


def test_list_clusters_returns_compact_summaries() -> None:
    v1 = clusters_service([NORMAL_CLUSTER, KERBEROS_CLUSTER])
    factory = make_factory({("mrs", "v1"): v1})

    result = mrs.list_clusters(service_factory=factory, region="sa-brazil-1")

    assert result["count"] == 2
    first = result["clusters"][0]
    assert first["cluster_id"] == "c-123"
    assert first["name"] == "analytics"
    assert first["components"] == ["Hive", "Spark", "Kafka"]
    assert first["kerberos"] is False
    assert first["master_ip"] == "192.168.0.10"
    assert first["eip"] == "1.2.3.4"
    assert result["clusters"][1]["kerberos"] is True


def test_list_clusters_accepts_snake_case_fields() -> None:
    snake = {
        "cluster_id": "c-9",
        "cluster_name": "legacy",
        "cluster_state": "running",
        "safe_mode": 0,
        "component_list": [{"component_name": "Hive"}],
        "master_node_ip": "10.0.0.9",
        "eip_address": "5.6.7.8",
    }
    v1 = clusters_service([snake])
    factory = make_factory({("mrs", "v1"): v1})

    result = mrs.list_clusters(service_factory=factory, region="sa-brazil-1")

    first = result["clusters"][0]
    assert first["cluster_id"] == "c-9"
    assert first["name"] == "legacy"
    assert first["state"] == "running"
    assert first["master_ip"] == "10.0.0.9"
    assert first["eip"] == "5.6.7.8"


def test_resolve_cluster_by_name_and_id() -> None:
    v1 = clusters_service([NORMAL_CLUSTER, KERBEROS_CLUSTER])
    factory = make_factory({("mrs", "v1"): v1})

    by_name = mrs._resolve_cluster(factory, "analytics", region="sa-brazil-1")
    by_id = mrs._resolve_cluster(factory, "c-666", region="sa-brazil-1")

    assert by_name["cluster_id"] == "c-123"
    assert by_id["cluster_id"] == "c-666"


def test_resolve_cluster_unknown_raises_with_candidates() -> None:
    v1 = clusters_service([NORMAL_CLUSTER])
    factory = make_factory({("mrs", "v1"): v1})

    with pytest.raises(ValueError, match="analytics"):
        mrs._resolve_cluster(factory, "nope", region="sa-brazil-1")


def test_run_sql_rejects_kerberos_cluster() -> None:
    v1 = clusters_service([KERBEROS_CLUSTER])
    factory = make_factory({("mrs", "v1"): v1})

    with pytest.raises(ValueError, match="[Kk]erberos"):
        mrs.run_sql(
            service_factory=factory,
            cluster="secure",
            sql="SELECT 1",
            region="sa-brazil-1",
        )


def test_run_sql_submits_and_polls_until_finished() -> None:
    v1 = clusters_service([NORMAL_CLUSTER])
    v2 = SequencedSdkService(
        {
            "execute_sql": {"id": "sql-1", "status": "RUNNING", "content": None},
            "show_sql_result": [
                {"id": "sql-1", "status": "RUNNING", "content": None},
                {
                    "id": "sql-1",
                    "status": "FINISHED",
                    "content": [["db1"], ["db2"]],
                    "result_location": None,
                },
            ],
        }
    )
    factory = make_factory({("mrs", "v1"): v1, ("mrs", "v2"): v2})

    result = mrs.run_sql(
        service_factory=factory,
        cluster="analytics",
        sql="SHOW DATABASES",
        engine="hive",
        region="sa-brazil-1",
        poll_interval_s=0,
    )

    assert result["status"] == "FINISHED"
    assert result["rows"] == [["db1"], ["db2"]]
    submit_op, submit_payload = v2.calls[0]
    assert submit_op == "execute_sql"
    assert submit_payload["cluster_id"] == "c-123"
    assert submit_payload["sql_type"] == "hive"
    assert submit_payload["sql_content"] == "SHOW DATABASES"
    poll_op, poll_payload = v2.calls[1]
    assert poll_op == "show_sql_result"
    assert poll_payload == {"cluster_id": "c-123", "sql_id": "sql-1"}


def test_run_sql_returns_immediately_when_finished() -> None:
    v1 = clusters_service([NORMAL_CLUSTER])
    v2 = FakeSdkService(
        {"execute_sql": {"id": "sql-2", "status": "FINISHED", "content": [["1"]]}}
    )
    factory = make_factory({("mrs", "v1"): v1, ("mrs", "v2"): v2})

    result = mrs.run_sql(
        service_factory=factory,
        cluster="c-123",
        sql="SELECT 1",
        engine="spark",
        region="sa-brazil-1",
    )

    assert result["rows"] == [["1"]]
    assert [op for op, _ in v2.calls] == ["execute_sql"]
    assert v2.calls[0][1]["sql_type"] == "spark"


def test_run_sql_failure_raises_with_message() -> None:
    v1 = clusters_service([NORMAL_CLUSTER])
    v2 = FakeSdkService(
        {
            "execute_sql": {
                "id": "sql-3",
                "status": "FAILED",
                "message": "Table not found: nope",
                "content": None,
            }
        }
    )
    factory = make_factory({("mrs", "v1"): v1, ("mrs", "v2"): v2})

    with pytest.raises(ValueError, match="Table not found"):
        mrs.run_sql(
            service_factory=factory,
            cluster="analytics",
            sql="SELECT * FROM nope",
            region="sa-brazil-1",
        )


def test_run_sql_rejects_unknown_engine() -> None:
    v1 = clusters_service([NORMAL_CLUSTER])
    factory = make_factory({("mrs", "v1"): v1})

    with pytest.raises(ValueError, match="engine"):
        mrs.run_sql(
            service_factory=factory,
            cluster="analytics",
            sql="SELECT 1",
            engine="mysql",
            region="sa-brazil-1",
        )


def test_submit_job_returns_job_id_without_waiting() -> None:
    v1 = clusters_service([NORMAL_CLUSTER])
    v2 = FakeSdkService(
        {"create_execute_job": {"job_submit_result": {"job_id": "j-1", "state": "COMPLETE"}}}
    )
    factory = make_factory({("mrs", "v1"): v1, ("mrs", "v2"): v2})

    result = mrs.submit_job(
        service_factory=factory,
        cluster="analytics",
        job_type="SparkSubmit",
        job_name="wordcount",
        arguments=["--class", "Main", "obs://bucket/app.jar"],
        region="sa-brazil-1",
    )

    assert result["job_id"] == "j-1"
    op, payload = v2.calls[0]
    assert op == "create_execute_job"
    assert payload["cluster_id"] == "c-123"
    assert payload["job_type"] == "SparkSubmit"
    assert payload["job_name"] == "wordcount"
    assert payload["arguments"] == ["--class", "Main", "obs://bucket/app.jar"]


def test_submit_job_wait_polls_job_state() -> None:
    v1 = clusters_service([NORMAL_CLUSTER])
    v2 = SequencedSdkService(
        {
            "create_execute_job": {"job_submit_result": {"job_id": "j-2"}},
            "show_single_job_exe": [
                {"job_detail": {"job_id": "j-2", "job_state": "RUNNING"}},
                {
                    "job_detail": {
                        "job_id": "j-2",
                        "job_state": "FINISHED",
                        "job_result": "SUCCEEDED",
                    }
                },
            ],
        }
    )
    factory = make_factory({("mrs", "v1"): v1, ("mrs", "v2"): v2})

    result = mrs.submit_job(
        service_factory=factory,
        cluster="analytics",
        job_type="HiveScript",
        arguments=["obs://bucket/script.sql"],
        region="sa-brazil-1",
        wait=True,
        poll_interval_s=0,
    )

    assert result["job_state"] == "FINISHED"
    assert result["job_result"] == "SUCCEEDED"


def test_node_execute_uses_eip_and_sources_client_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("MRS_SSH_USER", raising=False)
    v1 = clusters_service([NORMAL_CLUSTER])
    factory = make_factory({("mrs", "v1"): v1})
    ssh = FakeSshService()

    result = mrs.node_execute(
        service_factory=factory,
        ssh_service=ssh,
        cluster="analytics",
        command="hdfs dfs -ls /",
        region="sa-brazil-1",
        password="secret",
    )

    assert result["exit_status"] == 0
    call = ssh.calls[0]
    assert call["host"] == "1.2.3.4"
    assert call["username"] == "root"
    assert call["command"].startswith("source /opt/Bigdata/client/bigdata_env")
    assert "hdfs dfs -ls /" in call["command"]


def test_node_execute_credentials_default_from_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MRS_SSH_USER", "omm")
    monkeypatch.setenv("MRS_SSH_KEY", "/home/user/.ssh/mrs.pem")
    v1 = clusters_service([NORMAL_CLUSTER])
    factory = make_factory({("mrs", "v1"): v1})
    ssh = FakeSshService()

    mrs.node_execute(
        service_factory=factory,
        ssh_service=ssh,
        cluster="analytics",
        command="whoami",
        region="sa-brazil-1",
    )

    call = ssh.calls[0]
    assert call["username"] == "omm"
    assert call["private_key_path"] == "/home/user/.ssh/mrs.pem"


def test_node_execute_without_reachable_address_raises() -> None:
    isolated = dict(NORMAL_CLUSTER, eipAddress="", masterNodeIp="", internalIp="")
    v1 = clusters_service([isolated])
    factory = make_factory({("mrs", "v1"): v1})

    with pytest.raises(ValueError, match="EIP"):
        mrs.node_execute(
            service_factory=factory,
            ssh_service=FakeSshService(),
            cluster="analytics",
            command="whoami",
            region="sa-brazil-1",
            password="secret",
        )


def test_component_cli_maps_component_to_command() -> None:
    v1 = clusters_service([NORMAL_CLUSTER])
    factory = make_factory({("mrs", "v1"): v1})
    ssh = FakeSshService()

    mrs.component_cli(
        service_factory=factory,
        ssh_service=ssh,
        cluster="analytics",
        component="hdfs",
        command="dfs -ls /tmp",
        region="sa-brazil-1",
        password="secret",
    )

    command = ssh.calls[0]["command"]
    assert "hdfs dfs -ls /tmp" in command


def test_component_cli_rejects_unknown_component() -> None:
    v1 = clusters_service([NORMAL_CLUSTER])
    factory = make_factory({("mrs", "v1"): v1})

    with pytest.raises(ValueError, match="hdfs"):
        mrs.component_cli(
            service_factory=factory,
            ssh_service=FakeSshService(),
            cluster="analytics",
            component="warptable",
            command="ls",
            region="sa-brazil-1",
            password="secret",
        )


def test_component_cli_rejects_kerberos_cluster() -> None:
    v1 = clusters_service([KERBEROS_CLUSTER])
    factory = make_factory({("mrs", "v1"): v1})

    with pytest.raises(ValueError, match="[Kk]erberos"):
        mrs.component_cli(
            service_factory=factory,
            ssh_service=FakeSshService(),
            cluster="secure",
            component="hive",
            command="-e 'SHOW TABLES'",
            region="sa-brazil-1",
            password="secret",
        )


def test_mrs_tools_registered_in_mcp() -> None:
    from mcp_hwc.server import mcp

    tool_names = {t.name for t in mcp._tool_manager.list_tools()}
    expected = {
        "mrs_list_clusters",
        "mrs_run_sql",
        "mrs_submit_job",
        "mrs_node_execute",
        "mrs_component_cli",
    }
    assert expected.issubset(tool_names), f"Missing tools: {expected - tool_names}"
