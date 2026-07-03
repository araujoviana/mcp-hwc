from __future__ import annotations

from typing import TYPE_CHECKING

from mcp_hwc.server import (
    _run_tool_call,
    get_sdk_service,
    get_ssh_service,
)
from mcp_hwc.workflows import mrs as mrs_workflow

if TYPE_CHECKING:
    from mcp.server.fastmcp import FastMCP

def mrs_list_clusters(
    region: str,
    state: str | None = None,
) -> dict[str, object]:
    """List MRS clusters in a region with their components, security mode, and master addresses. Use this first to find the cluster the other mrs_* tools operate on."""
    return _run_tool_call(
        lambda: mrs_workflow.list_clusters(
            service_factory=get_sdk_service,
            region=region,
            state=state,
        )
    )

def mrs_run_sql(
    cluster: str,
    sql: str,
    region: str,
    engine: str = "hive",
    database: str | None = None,
    wait: bool = True,
    timeout_s: int = 300,
) -> dict[str, object]:
    """Run a SQL statement on an MRS cluster via the MRS SQL API (no SSH needed). engine: hive, spark, or presto. cluster accepts a name or id. Returns result rows for queries that finish in time."""
    return _run_tool_call(
        lambda: mrs_workflow.run_sql(
            service_factory=get_sdk_service,
            cluster=cluster,
            sql=sql,
            engine=engine,
            region=region,
            database=database,
            wait=wait,
            timeout_s=timeout_s,
        )
    )

def mrs_submit_job(
    cluster: str,
    job_type: str,
    region: str,
    job_name: str | None = None,
    arguments: list[str] | None = None,
    properties: dict[str, str] | None = None,
    wait: bool = False,
    timeout_s: int = 1800,
) -> dict[str, object]:
    """Submit a job to an MRS cluster: MapReduce, SparkSubmit, SparkSql, HiveSql, HiveScript, or Flink. Returns the job id; set wait=True to poll until the job finishes."""
    return _run_tool_call(
        lambda: mrs_workflow.submit_job(
            service_factory=get_sdk_service,
            cluster=cluster,
            job_type=job_type,
            job_name=job_name,
            arguments=arguments,
            properties=properties,
            region=region,
            wait=wait,
            timeout_s=timeout_s,
        )
    )

def mrs_node_execute(
    cluster: str,
    command: str,
    region: str,
    username: str | None = None,
    password: str | None = None,
    private_key_path: str | None = None,
    host: str | None = None,
    command_timeout: int = 300,
) -> dict[str, object]:
    """Run a shell command on an MRS cluster's master node over SSH with the cluster client env sourced. Credentials default from MRS_SSH_USER/MRS_SSH_KEY/MRS_SSH_PASSWORD env vars."""
    return _run_tool_call(
        lambda: mrs_workflow.node_execute(
            service_factory=get_sdk_service,
            ssh_service=get_ssh_service(),
            cluster=cluster,
            command=command,
            region=region,
            username=username,
            password=password,
            private_key_path=private_key_path,
            host=host,
            command_timeout=command_timeout,
        )
    )

def mrs_component_cli(
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
    """Run an MRS component CLI on the cluster master node over SSH. component: hdfs, yarn, hive (beeline), spark (spark-sql), kafka (kafka-topics.sh), hbase, clickhouse, or flink; the command is appended to the component entry point (e.g. component='hdfs', command='dfs -ls /tmp')."""
    return _run_tool_call(
        lambda: mrs_workflow.component_cli(
            service_factory=get_sdk_service,
            ssh_service=get_ssh_service(),
            cluster=cluster,
            component=component,
            command=command,
            region=region,
            username=username,
            password=password,
            private_key_path=private_key_path,
            host=host,
            command_timeout=command_timeout,
        )
    )

def register_mrs_tools(mcp: FastMCP):
    mcp.tool()(mrs_list_clusters)
    mcp.tool()(mrs_run_sql)
    mcp.tool()(mrs_submit_job)
    mcp.tool()(mrs_node_execute)
    mcp.tool()(mrs_component_cli)
