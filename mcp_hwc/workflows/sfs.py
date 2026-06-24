from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
import shlex
import uuid

from mcp_hwc.cloud_services.compute import (
    create_ecs_security_group,
    extract_server_ids_from_response,
    extract_server_ips,
    find_server_after_create,
    generate_secret_password,
    pick_sfs_availability_zone,
    resolve_ecs_flavor,
    resolve_ecs_image,
    resolve_vpc_and_subnet,
)
from mcp_hwc.core.errors import HelperToolError
from mcp_hwc.utils.polling import DEFAULT_POLL_INTERVAL_SECONDS, wait_for_service_value
from mcp_hwc.core.sdk_service import HuaweiCloudSdkService

SdkServiceFactory = Callable[..., HuaweiCloudSdkService]


def mount_sfs_share_via_ssh(
    *,
    ssh_service: object,
    host: str,
    username: str,
    password: str,
    export_location: str,
    mount_path: str,
) -> dict[str, object]:
    q_export = shlex.quote(export_location)
    q_mount = shlex.quote(mount_path)
    fstab_needle = shlex.quote(export_location + " " + mount_path + " nfs ")

    def run(cmd: str) -> dict:
        result = ssh_service.execute(
            host=host,
            username=username,
            command=cmd,
            password=password,
            allow_unknown_host=True,
            connect_timeout=20,
            command_timeout=600,
        )
        if result["exit_status"] != 0:
            raise HelperToolError(
                f"Failed to prepare SFS mount on {username}@{host}: {result['stderr'] or result['stdout']}"
            )
        return result

    run("dpkg -s nfs-common >/dev/null 2>&1 || { apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y nfs-common; }")
    run(f"mkdir -p {q_mount}")
    run(f"mount -t nfs -o vers=3,timeo=600,noresvport,nolock {q_export} {q_mount}")
    run(f"printf 'sfs proof %s\\n' \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\" > {q_mount}/proof.txt")
    run(
        f"awk -v p={fstab_needle} 'index($0,p)==1' /etc/fstab | grep -q . || "
        f"printf '%s %s nfs vers=3,timeo=600,noresvport,nolock,_netdev 0 0\\n' "
        f"{q_export} {q_mount} >> /etc/fstab"
    )
    proof = run(f"cat {q_mount}/proof.txt")
    fs_report = run(f"df -h {q_mount}")
    mount_report = run(f"mount | grep -F {shlex.quote(' ' + mount_path + ' ')}")
    dir_listing = run(f"ls -la {q_mount}")

    return {
        "proof_text": proof["stdout"].strip(),
        "filesystem_report": fs_report["stdout"].strip(),
        "mount_report": mount_report["stdout"].strip(),
        "directory_listing": dir_listing["stdout"].strip(),
    }


def create_accessible_share(
    *,
    service_factory: SdkServiceFactory,
    ssh_service: object,
    region: str,
    client_cidr: str,
    share_name: str | None = None,
    size_gb: int = 500,
    share_type: str = "STANDARD",
    vpc_id: str | None = None,
    subnet_id: str | None = None,
    availability_zone: str | None = None,
    access_vm_name: str | None = None,
    access_vm_password: str | None = None,
    mount_path: str = "/mnt/sfs-demo",
) -> dict[str, object]:
    if size_gb <= 0:
        raise ValueError("size_gb must be greater than zero")
    if not client_cidr.strip():
        raise ValueError("client_cidr cannot be empty")
    if not mount_path.startswith("/"):
        raise ValueError("mount_path must be an absolute path")

    normalized_share_type = share_type.strip().upper()
    if normalized_share_type not in {"STANDARD", "PERFORMANCE"}:
        raise ValueError("share_type must be STANDARD or PERFORMANCE")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
    resolved_share_name = share_name or f"mcphwcsfs{timestamp}"
    resolved_vm_name = access_vm_name or f"{resolved_share_name}-client"
    resolved_vm_password = access_vm_password or generate_secret_password("McpSfsVm")

    vpc_service = service_factory("vpc", region=region)
    sfs_service = service_factory("sfs", region=region)
    ims_service = service_factory("ims", region=region)
    ecs_service = service_factory("ecs", region=region)

    resolved_vpc_id, resolved_subnet_id, subnet = resolve_vpc_and_subnet(
        vpc_service,
        vpc_id=vpc_id,
        subnet_id=subnet_id,
    )
    subnet_cidr = subnet.get("cidr")
    if not isinstance(subnet_cidr, str) or not subnet_cidr.strip():
        raise HelperToolError("Could not resolve the subnet CIDR for the SFS permission rule")

    resolved_availability_zone = availability_zone
    if resolved_availability_zone is None:
        share_types = sfs_service.call_operation(
            "list_share_types",
            {"limit": 100, "offset": 0},
        )["response"].get("share_types") or []
        resolved_availability_zone = pick_sfs_availability_zone(
            share_types,
            requested_share_type=normalized_share_type,
        )

    sg_name = f"mcp-hwc-sfs-{timestamp}"
    security_group_id = create_ecs_security_group(
        vpc_service,
        name=sg_name,
        vpc_id=resolved_vpc_id,
        ssh_cidr=client_cidr,
    )

    share_response = sfs_service.call_operation(
        "create_share",
        {
            "body": {
                "share": {
                    "availability_zone": resolved_availability_zone,
                    "description": "SFS share created by mcp-hwc",
                    "name": resolved_share_name,
                    "security_group_id": security_group_id,
                    "share_proto": "NFS",
                    "share_type": normalized_share_type,
                    "size": size_gb,
                    "subnet_id": resolved_subnet_id,
                    "vpc_id": resolved_vpc_id,
                    "tags": [
                        {"key": "managed-by", "value": "mcp-hwc"},
                        {"key": "purpose", "value": "sfs-demo"},
                    ],
                }
            }
        },
    )
    share_id = share_response["response"].get("id")
    if not isinstance(share_id, str) or not share_id.strip():
        raise HelperToolError("SFS did not return a share ID")

    share_result = wait_for_service_value(
        sfs_service,
        operation="show_share",
        parameters={"share_id": share_id},
        response_path="response.status",
        expected_value="200",
        timeout_seconds=1200,
        interval_seconds=DEFAULT_POLL_INTERVAL_SECONDS,
    )
    share = share_result["response"]
    export_location = share.get("export_location")
    if not isinstance(export_location, str) or not export_location.strip():
        raise HelperToolError("SFS did not become mountable")

    perm_rules = sfs_service.call_operation(
        "list_perm_rules",
        {"share_id": share_id, "limit": 100, "offset": 0},
    )["response"].get("rules") or []
    for rule in perm_rules:
        if rule.get("ip_cidr") == "*":
            rule_id = rule.get("id")
            if isinstance(rule_id, str) and rule_id.strip():
                sfs_service.call_operation(
                    "delete_perm_rule",
                    {"share_id": share_id, "rule_id": rule_id},
                )

    if not any(rule.get("ip_cidr") == subnet_cidr for rule in perm_rules):
        sfs_service.call_operation(
            "create_perm_rule",
            {
                "share_id": share_id,
                "body": {
                    "rules": [
                        {
                            "ip_cidr": subnet_cidr,
                            "rw_type": "rw",
                            "user_type": "no_root_squash",
                        }
                    ]
                },
            },
        )

    image = resolve_ecs_image(ims_service, image_id=None, image_hint=None)
    flavor, vm_az = resolve_ecs_flavor(
        ecs_service,
        flavor_id=None,
        flavor_hint=None,
        availability_zone=resolved_availability_zone,
    )

    create_vm_response = ecs_service.call_operation(
        "create_servers",
        {
            "x_client_token": str(uuid.uuid4()),
            "body": {
                "server": {
                    "imageRef": image["id"],
                    "flavorRef": flavor["id"],
                    "name": resolved_vm_name,
                    "adminPass": resolved_vm_password,
                    "vpcid": resolved_vpc_id,
                    "nics": [{"subnet_id": resolved_subnet_id}],
                    "publicip": {
                        "eip": {
                            "iptype": "5_bgp",
                            "bandwidth": {
                                "size": 5,
                                "sharetype": "PER",
                                "chargemode": "traffic",
                            },
                        },
                        "delete_on_termination": True,
                    },
                    "count": 1,
                    "root_volume": {"volumetype": "GPSSD", "size": 40},
                    "security_groups": [{"id": security_group_id}],
                    "availability_zone": vm_az,
                    "extendparam": {
                        "chargingMode": "postPaid",
                        "regionID": region,
                        "isAutoPay": "true",
                    },
                }
            },
        },
    )
    create_vm = create_vm_response["response"]
    job_id = create_vm.get("job_id")
    if not isinstance(job_id, str) or not job_id.strip():
        raise HelperToolError("ECS did not return a create job ID")
    create_server_ids = extract_server_ids_from_response(create_vm)

    wait_for_service_value(
        ecs_service,
        operation="show_job",
        parameters={"job_id": job_id},
        response_path="response.status",
        expected_value="SUCCESS",
        timeout_seconds=1200,
        interval_seconds=DEFAULT_POLL_INTERVAL_SECONDS,
    )

    server = find_server_after_create(ecs_service, create_server_ids, resolved_vm_name)
    if server is None:
        raise HelperToolError("Could not locate the access VM after creation")
    private_ip, public_ip = extract_server_ips(server)
    if not public_ip:
        raise HelperToolError("Access VM did not receive a public IP")

    mount_result = mount_sfs_share_via_ssh(
        ssh_service=ssh_service,
        host=public_ip,
        username="root",
        password=resolved_vm_password,
        export_location=export_location,
        mount_path=mount_path,
    )

    return {
        "region": region,
        "share": {
            "id": share_id,
            "name": share.get("name") or resolved_share_name,
            "availability_zone": resolved_availability_zone,
            "size_gb": size_gb,
            "share_type": normalized_share_type,
            "export_location": export_location,
            "endpoint": share.get("optional_endpoint"),
            "security_group_id": security_group_id,
            "allowed_mount_cidr": subnet_cidr,
        },
        "access_vm": {
            "id": server.get("id"),
            "name": server.get("name") or resolved_vm_name,
            "availability_zone": vm_az,
            "image_id": image["id"],
            "flavor_id": flavor["id"],
            "private_ip": private_ip,
            "public_ip": public_ip,
            "username": "root",
            "password": resolved_vm_password,
            "mount_path": mount_path,
            "ssh_allowed_cidr": client_cidr,
        },
        "proof": mount_result,
    }
