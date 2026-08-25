from __future__ import annotations

import os
import time
from collections.abc import Callable

SdkServiceFactory = Callable[..., object]

CLIENT_ENV_COMMAND = "source /opt/Bigdata/client/bigdata_env 2>/dev/null || true"

_SQL_ENGINES = {"hive", "spark", "presto"}
_JOB_TYPES = {"MapReduce", "SparkSubmit", "SparkSql", "HiveSql", "HiveScript", "Flink"}
_TERMINAL_SQL_STATES = {"FINISHED", "FAILED", "CANCELLED"}
_TERMINAL_JOB_STATES = {"FINISHED", "FAILED", "KILLED"}

# Component CLI entry points available on cluster nodes once the client env is
# sourced. The tool command is appended verbatim after the entry point.
COMPONENT_CLIS = {
    "hdfs": "hdfs",
    "yarn": "yarn",
    "hive": "beeline",
    "spark": "spark-sql",
    "flink": "flink",
    "kafka": "kafka-topics.sh",
    "hbase": "hbase",
    "clickhouse": "clickhouse client",
}


def list_clusters(
    *,
    service_factory: SdkServiceFactory,
    region: str,
    state: str | None = None,
) -> dict[str, object]:
    payload: dict[str, object] = {}
    if state:
        payload["cluster_state"] = state
    clusters = _list_raw_clusters(service_factory, region=region, payload=payload)
    summaries = [_summarize_cluster(c) for c in clusters]
    return {"clusters": summaries, "count": len(summaries)}


def run_sql(
    *,
    service_factory: SdkServiceFactory,
    cluster: str,
    sql: str,
    engine: str = "hive",
    region: str,
    database: str | None = None,
    wait: bool = True,
    timeout_s: int = 300,
    poll_interval_s: float = 5.0,
) -> dict[str, object]:
    if engine not in _SQL_ENGINES:
        supported = ", ".join(sorted(_SQL_ENGINES))
        raise ValueError(f"Unsupported SQL engine '{engine}'. Supported engines: {supported}")
    if not sql.strip():
        raise ValueError("sql cannot be empty")

    info = _resolve_cluster(service_factory, cluster, region=region)
    _require_normal_mode(info, "SQL execution")
    cluster_id = info["cluster_id"]

    svc = service_factory("mrs", api_version="v2", region=region)
    payload: dict[str, object] = {
        "cluster_id": cluster_id,
        "sql_type": engine,
        "sql_content": sql,
    }
    if database:
        payload["database"] = database
    submitted = svc.call_operation("execute_sql", payload)["response"]

    result = submitted
    if wait:
        deadline = time.monotonic() + timeout_s
        while result.get("status") not in _TERMINAL_SQL_STATES:
            if time.monotonic() > deadline:
                raise ValueError(
                    f"SQL statement {result.get('id')} did not finish within {timeout_s}s "
                    f"(last status: {result.get('status')})"
                )
            if poll_interval_s > 0:
                time.sleep(poll_interval_s)
            result = svc.call_operation(
                "show_sql_result",
                {"cluster_id": cluster_id, "sql_id": result.get("id")},
            )["response"]

    status = result.get("status")
    if status in {"FAILED", "CANCELLED"}:
        raise ValueError(
            f"SQL execution {status.lower()} on cluster '{info['cluster_name']}': "
            f"{result.get('message') or 'no error message returned'}"
        )
    return {
        "cluster_id": cluster_id,
        "sql_id": result.get("id"),
        "status": status,
        "rows": result.get("content") or [],
        "result_location": result.get("result_location"),
        "message": result.get("message"),
    }


def submit_job(
    *,
    service_factory: SdkServiceFactory,
    cluster: str,
    job_type: str,
    job_name: str | None = None,
    arguments: list[str] | None = None,
    properties: dict[str, str] | None = None,
    region: str,
    wait: bool = False,
    timeout_s: int = 1800,
    poll_interval_s: float = 30.0,
) -> dict[str, object]:
    if job_type not in _JOB_TYPES:
        supported = ", ".join(sorted(_JOB_TYPES))
        raise ValueError(f"Unsupported job_type '{job_type}'. Supported types: {supported}")

    info = _resolve_cluster(service_factory, cluster, region=region)
    _require_normal_mode(info, "job submission")
    cluster_id = info["cluster_id"]

    svc = service_factory("mrs", api_version="v2", region=region)
    payload: dict[str, object] = {
        "cluster_id": cluster_id,
        "job_type": job_type,
        "job_name": job_name or f"mcp-hwc-{job_type.lower()}-{int(time.time())}",
        "arguments": arguments or [],
    }
    if properties:
        payload["properties"] = properties
    response = svc.call_operation("create_execute_job", payload)["response"]
    submit_result = response.get("job_submit_result") or response
    job_id = submit_result.get("job_id")

    result: dict[str, object] = {
        "cluster_id": cluster_id,
        "job_id": job_id,
        "job_type": job_type,
    }
    if not wait:
        return result

    deadline = time.monotonic() + timeout_s
    detail: dict[str, object] = {}
    while True:
        detail = (
            svc.call_operation(
                "show_single_job_exe",
                {"cluster_id": cluster_id, "job_execution_id": job_id},
            )["response"].get("job_detail")
            or {}
        )
        if detail.get("job_state") in _TERMINAL_JOB_STATES:
            break
        if time.monotonic() > deadline:
            raise ValueError(
                f"Job {job_id} did not finish within {timeout_s}s "
                f"(last state: {detail.get('job_state')})"
            )
        if poll_interval_s > 0:
            time.sleep(poll_interval_s)

    if detail.get("job_state") in {"FAILED", "KILLED"}:
        raise ValueError(
            f"Job {job_id} ended in state {detail.get('job_state')} "
            f"(result: {detail.get('job_result')}). Check tracking_url or Yarn logs."
        )
    result.update(
        {
            "job_state": detail.get("job_state"),
            "job_result": detail.get("job_result"),
            "tracking_url": detail.get("tracking_url"),
        }
    )
    return result


def node_execute(
    *,
    service_factory: SdkServiceFactory,
    ssh_service: object,
    cluster: str,
    command: str,
    region: str,
    username: str | None = None,
    password: str | None = None,
    private_key_path: str | None = None,
    host: str | None = None,
    command_timeout: int = 300,
) -> dict[str, object]:
    if not command.strip():
        raise ValueError("command cannot be empty")

    info = _resolve_cluster(service_factory, cluster, region=region)
    resolved_host = host or info["eip"] or info["master_ip"]
    if not resolved_host:
        raise ValueError(
            f"Cluster '{info['cluster_name']}' has no reachable master address. "
            "Bind an EIP to the master node or pass host= explicitly."
        )

    resolved_username = username or os.environ.get("MRS_SSH_USER") or "root"
    resolved_key = private_key_path or os.environ.get("MRS_SSH_KEY") or None
    resolved_password = password or os.environ.get("MRS_SSH_PASSWORD") or None
    if not resolved_key and not resolved_password:
        raise ValueError(
            "SSH credentials required: pass password/private_key_path or set "
            "MRS_SSH_PASSWORD/MRS_SSH_KEY in the environment."
        )

    result = ssh_service.execute(
        host=resolved_host,
        username=resolved_username,
        command=f"{CLIENT_ENV_COMMAND}; {command}",
        password=resolved_password,
        private_key_path=resolved_key,
        allow_unknown_host=True,
        connect_timeout=20,
        command_timeout=command_timeout,
    )
    return {
        **result,
        "cluster_id": info["cluster_id"],
        "host": resolved_host,
    }


def component_cli(
    *,
    service_factory: SdkServiceFactory,
    ssh_service: object,
    cluster: str,
    component: str,
    command: str,
    region: str,
    username: str | None = None,
    password: str | None = None,
    private_key_path: str | None = None,
    host: str | None = None,
    command_timeout: int = 300,
) -> dict[str, object]:
    entry_point = COMPONENT_CLIS.get(component.strip().lower())
    if entry_point is None:
        supported = ", ".join(sorted(COMPONENT_CLIS))
        raise ValueError(f"Unsupported component '{component}'. Supported components: {supported}")

    info = _resolve_cluster(service_factory, cluster, region=region)
    _require_normal_mode(info, f"{component} CLI access")

    return node_execute(
        service_factory=service_factory,
        ssh_service=ssh_service,
        cluster=info["cluster_id"],
        command=f"{entry_point} {command}",
        region=region,
        username=username,
        password=password,
        private_key_path=private_key_path,
        host=host,
        command_timeout=command_timeout,
    )


def _list_raw_clusters(
    service_factory: SdkServiceFactory,
    *,
    region: str,
    payload: dict[str, object] | None = None,
) -> list[dict]:
    svc = service_factory("mrs", api_version="v1", region=region)
    response = svc.call_operation("list_clusters", payload or {})["response"]
    return response.get("clusters") or []


def _field(cluster: dict, camel: str, snake: str) -> object:
    # The v1 API serializes with camelCase wire names (attribute_map keys,
    # e.g. "clusterId"); accept snake_case too in case a caller feeds
    # already-normalized data.
    value = cluster.get(camel)
    if value is None:
        value = cluster.get(snake)
    return value


def _resolve_cluster(
    service_factory: SdkServiceFactory,
    cluster: str,
    *,
    region: str,
) -> dict[str, object]:
    clusters = [_summarize_cluster(c) for c in _list_raw_clusters(service_factory, region=region)]
    matches = [c for c in clusters if c["cluster_id"] == cluster or c["cluster_name"] == cluster]
    if not matches:
        known = ", ".join(f"{c['cluster_name']} ({c['cluster_id']})" for c in clusters) or "none"
        raise ValueError(f"MRS cluster '{cluster}' not found. Known clusters: {known}")
    if len(matches) > 1:
        ids = ", ".join(str(c["cluster_id"]) for c in matches)
        raise ValueError(f"MRS cluster name '{cluster}' is ambiguous. Use one of the ids: {ids}")
    return matches[0]


def _summarize_cluster(cluster: dict) -> dict[str, object]:
    components = [
        _field(item, "componentName", "component_name") or ""
        for item in _field(cluster, "componentList", "component_list") or []
    ]
    name = _field(cluster, "clusterName", "cluster_name") or ""
    return {
        "cluster_id": _field(cluster, "clusterId", "cluster_id") or "",
        "cluster_name": name,
        "name": name,
        "state": _field(cluster, "clusterState", "cluster_state") or "",
        "kerberos": bool(_field(cluster, "safeMode", "safe_mode")),
        "components": [c for c in components if c],
        "master_ip": (
            _field(cluster, "masterNodeIp", "master_node_ip")
            or _field(cluster, "privateIpFirst", "private_ip_first")
            or ""
        ),
        "eip": (
            _field(cluster, "eipAddress", "eip_address")
            or _field(cluster, "externalIp", "external_ip")
            or ""
        ),
    }


def _require_normal_mode(cluster_info: dict[str, object], operation: str) -> None:
    if cluster_info.get("kerberos"):
        raise ValueError(
            f"Cluster '{cluster_info['cluster_name']}' is Kerberos-secured; "
            f"{operation} is only supported on normal-mode clusters for now."
        )
