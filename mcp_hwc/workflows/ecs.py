from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import uuid

from mcp_hwc.cloud_services.compute import (
    create_ecs_security_group,
    extract_server_ips,
    generate_secret_password,
    resolve_ecs_flavor,
    resolve_ecs_image,
    resolve_vpc_and_subnet,
)
from mcp_hwc.core.errors import HelperToolError
from mcp_hwc.utils.polling import wait_for_service_value
from mcp_hwc.core.sdk_service import HuaweiCloudSdkService

SdkServiceFactory = Callable[..., HuaweiCloudSdkService]


def create_ecs_vm(
    *,
    service_factory: SdkServiceFactory,
    region: str,
    name: str | None = None,
    public_access: bool = True,
    ssh_cidr: str | None = None,
    admin_password: str | None = None,
    return_password: bool = True,
    vpc_id: str | None = None,
    subnet_id: str | None = None,
    security_group_id: str | None = None,
    image_id: str | None = None,
    image_hint: str | None = "Ubuntu",
    flavor_id: str | None = None,
    flavor_hint: str | None = None,
    availability_zone: str | None = None,
    root_volume_type: str = "GPSSD",
    root_volume_size_gb: int = 40,
    bandwidth_size_mbit: int = 5,
    wait: bool = False,
) -> dict[str, object]:
    if not region.strip():
        raise ValueError("region cannot be empty")
    if root_volume_size_gb <= 0:
        raise ValueError("root_volume_size_gb must be greater than zero")
    if bandwidth_size_mbit <= 0:
        raise ValueError("bandwidth_size_mbit must be greater than zero")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    resolved_name = name or f"mcp-ecs-{timestamp}"
    resolved_password = admin_password or generate_secret_password("McpEcs")
    resolved_ssh_cidr = ssh_cidr if ssh_cidr is not None else ("0.0.0.0/0" if public_access else None)

    vpc_service = service_factory("vpc", region=region)
    ims_service = service_factory("ims", region=region)
    ecs_service = service_factory("ecs", region=region)

    resolved_vpc_id, resolved_subnet_id, _ = resolve_vpc_and_subnet(
        vpc_service,
        vpc_id=vpc_id,
        subnet_id=subnet_id,
    )
    resolved_security_group_id = security_group_id
    if resolved_security_group_id is None:
        resolved_security_group_id = create_ecs_security_group(
            vpc_service,
            name=f"mcp-hwc-ecs-{timestamp}",
            vpc_id=resolved_vpc_id,
            ssh_cidr=resolved_ssh_cidr,
        )

    image = resolve_ecs_image(
        ims_service,
        image_id=image_id,
        image_hint=image_hint,
    )
    flavor, vm_az = resolve_ecs_flavor(
        ecs_service,
        flavor_id=flavor_id,
        flavor_hint=flavor_hint,
        availability_zone=availability_zone,
    )

    server_payload: dict[str, object] = {
        "imageRef": image["id"],
        "flavorRef": flavor["id"],
        "name": resolved_name,
        "adminPass": resolved_password,
        "vpcid": resolved_vpc_id,
        "nics": [{"subnet_id": resolved_subnet_id}],
        "count": 1,
        "root_volume": {
            "volumetype": root_volume_type,
            "size": root_volume_size_gb,
        },
        "security_groups": [{"id": resolved_security_group_id}],
        "availability_zone": vm_az,
        "extendparam": {
            "chargingMode": "postPaid",
            "regionID": region,
            "isAutoPay": "true",
        },
    }
    if public_access:
        server_payload["publicip"] = {
            "eip": {
                "iptype": "5_bgp",
                "bandwidth": {
                    "size": bandwidth_size_mbit,
                    "sharetype": "PER",
                    "chargemode": "traffic",
                },
            },
            "delete_on_termination": True,
        }

    create_result = ecs_service.call_operation(
        "create_servers",
        {
            "x_client_token": str(uuid.uuid4()),
            "body": {"server": server_payload},
        },
    )
    response = create_result.get("response") or {}
    job_id = response.get("job_id")
    server_ids = response.get("server_ids") or response.get("serverIds") or []
    if isinstance(response.get("server_id"), str):
        server_ids = [response["server_id"]]

    result: dict[str, object] = {
        "region": create_result.get("region") or region,
        "name": resolved_name,
        "created": True,
        "waited": False,
        "job_id": job_id,
        "server_ids": server_ids,
        "selected": {
            "vpc_id": resolved_vpc_id,
            "subnet_id": resolved_subnet_id,
            "security_group_id": resolved_security_group_id,
            "image_id": image["id"],
            "flavor_id": flavor["id"],
            "availability_zone": vm_az,
            "public_access": public_access,
            "ssh_cidr": resolved_ssh_cidr,
        },
        "login": {
            "username": "root",
            "password_returned": bool(return_password),
        },
        "next_steps": [
            "Use job_id to check provisioning status only if you need readiness now.",
            "Call ecs_create_vm with wait=true when you need the IPs returned immediately.",
        ],
    }
    if return_password:
        result["login"]["password"] = resolved_password
    if resolved_ssh_cidr == "0.0.0.0/0":
        result["warnings"] = [
            "SSH is open to 0.0.0.0/0 because ssh_cidr was not provided. Restrict it when possible."
        ]

    if wait:
        if not isinstance(job_id, str) or not job_id.strip():
            raise HelperToolError("ECS did not return a create job ID")
        wait_for_service_value(
            ecs_service,
            operation="show_job",
            parameters={"job_id": job_id},
            response_path="response.status",
            expected_value="SUCCESS",
            timeout_seconds=1200,
        )
        servers = ecs_service.call_operation(
            "list_servers_details",
            {"name": resolved_name},
        )["response"].get("servers") or []
        if servers:
            server = servers[0]
            private_ip, public_ip = extract_server_ips(server)
            result["waited"] = True
            result["server"] = {
                "id": server.get("id"),
                "name": server.get("name") or resolved_name,
                "private_ip": private_ip,
                "public_ip": public_ip,
            }

    return result
