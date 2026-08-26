from __future__ import annotations

import json

import pytest

from mcp_hwc.core.config import CloudApiConfig
from mcp_hwc.core.sdk_service import (
    HuaweiCloudSdkService,
    format_list_as_markdown_table,
    project_response_fields,
    render_dense_type_schema,
    resolve_service_spec,
)


def make_config() -> CloudApiConfig:
    return CloudApiConfig(
        access_key_id="test-ak",
        secret_access_key="test-sk",
        project_id="project-123",
        region="sa-brazil-1",
    )


def test_dense_schema_drastically_reduces_token_size() -> None:
    service = HuaweiCloudSdkService(make_config(), "ecs")

    # 1. Old/verbose schema description
    raw_desc = service.describe_operation("create_servers", dense_only=False)
    raw_schema_json = json.dumps(raw_desc["request_schema"])
    raw_template_json = json.dumps(raw_desc["request_template"])
    raw_total_len = len(raw_schema_json) + len(raw_template_json)

    # 2. Dense TypeScript schema representation
    dense_repr = render_dense_type_schema(service, "CreateServersRequest", max_depth=3)
    dense_len = len(dense_repr)

    # Assert dense representation is non-empty and readable
    assert "interface CreateServersRequest" in dense_repr or "CreateServersRequest" in dense_repr
    assert "server" in dense_repr

    # Empirical Proof: Dense representation must achieve at least 70% reduction in character count
    reduction_pct = (1.0 - (dense_len / raw_total_len)) * 100.0
    print(
        f"\n[Token Optimization Proof 1] Raw AST chars: {raw_total_len}, Dense chars: {dense_len}, Reduction: {reduction_pct:.2f}%"
    )
    assert reduction_pct > 70.0


def test_field_projection_filters_unnecessary_metadata() -> None:
    # Simulate a heavy ECS list_servers response with 50+ metadata fields
    raw_server_record = {
        "id": "server-uuid-12345",
        "name": "production-app-node-01",
        "status": "ACTIVE",
        "hostId": "host-internal-hash-998877",
        "flavor": {
            "id": "c7.large.2",
            "links": [
                {
                    "rel": "self",
                    "href": "https://ecs.sa-brazil-1.myhuaweicloud.com/v2/flavors/c7.large.2",
                }
            ],
        },
        "image": {
            "id": "img-ubuntu-2204",
            "links": [
                {
                    "rel": "bookmark",
                    "href": "https://ims.sa-brazil-1.myhuaweicloud.com/images/img-ubuntu-2204",
                }
            ],
        },
        "metadata": {
            "charging_mode": "0",
            "metering.order_id": "none",
            "os_type": "Linux",
            "vpc_id": "vpc-123",
        },
        "os-extended-volumes:volumes_attached": [
            {"id": "vol-001", "delete_on_termination": "false", "bootIndex": "0"}
        ],
        "OS-EXT-SRV-ATTR:hypervisor_hostname": "compute-blade-09.az1",
        "OS-EXT-SRV-ATTR:instance_name": "instance-0000004a",
        "OS-EXT-STS:task_state": None,
        "OS-EXT-STS:vm_state": "active",
        "OS-EXT-STS:power_state": 1,
        "accessIPv4": "",
        "accessIPv6": "",
        "config_drive": "",
        "progress": 0,
        "addresses": {
            "vpc-123": [{"version": "4", "addr": "192.168.1.15", "OS-EXT-IPS:type": "fixed"}]
        },
    }
    raw_response = {"servers": [raw_server_record] * 5}
    raw_json_len = len(json.dumps(raw_response))

    # Projected response requesting only core fields
    projected = project_response_fields(raw_response, fields=["id", "name", "status", "addresses"])
    projected_json_len = len(json.dumps(projected))

    reduction_pct = (1.0 - (projected_json_len / raw_json_len)) * 100.0
    print(
        f"\n[Token Optimization Proof 2] Raw JSON chars: {raw_json_len}, Projected JSON chars: {projected_json_len}, Reduction: {reduction_pct:.2f}%"
    )

    assert len(projected["servers"]) == 5
    assert "id" in projected["servers"][0]
    assert "OS-EXT-SRV-ATTR:hypervisor_hostname" not in projected["servers"][0]
    assert reduction_pct > 60.0


def test_markdown_table_formatter_produces_compact_tabular_output() -> None:
    records = [
        {
            "id": "vm-01",
            "name": "web-01",
            "status": "ACTIVE",
            "ip": "10.0.1.10",
            "flavor": "c7.large.2",
        },
        {
            "id": "vm-02",
            "name": "web-02",
            "status": "ACTIVE",
            "ip": "10.0.1.11",
            "flavor": "c7.large.2",
        },
        {
            "id": "vm-03",
            "name": "db-01",
            "status": "ACTIVE",
            "ip": "10.0.2.10",
            "flavor": "m7.xlarge.4",
        },
    ]
    raw_json_len = len(json.dumps(records, indent=2))
    table_str = format_list_as_markdown_table(
        records, columns=["name", "status", "ip", "flavor", "id"]
    )
    table_len = len(table_str)

    assert "| name | status | ip | flavor | id |" in table_str
    assert "| web-01 | ACTIVE | 10.0.1.10 | c7.large.2 | vm-01 |" in table_str

    reduction_pct = (1.0 - (table_len / raw_json_len)) * 100.0
    print(
        f"\n[Token Optimization Proof 3] Raw indented JSON chars: {raw_json_len}, Markdown Table chars: {table_len}, Reduction: {reduction_pct:.2f}%"
    )
    assert reduction_pct > 35.0
