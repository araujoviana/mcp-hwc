from __future__ import annotations

import re
import secrets
from typing import TYPE_CHECKING

from mcp_hwc.core.errors import HelperToolError

if TYPE_CHECKING:
    from mcp_hwc.core.sdk_service import HuaweiCloudSdkService


def generate_secret_password(prefix: str = "Mcp") -> str:
    token = re.sub(r"[^A-Za-z0-9]", "", secrets.token_urlsafe(12))[:12]
    return f"{prefix}{token}9!"


def extract_first_string(item: dict[str, object], *keys: str) -> str | None:
    for key in keys:
        value = item.get(key)
        if isinstance(value, str) and value.strip():
            return value
    return None


def select_named_resource(
    items: list[dict[str, object]],
    *,
    name: str | None,
    id_keys: tuple[str, ...],
    name_keys: tuple[str, ...],
    label: str,
) -> dict[str, object]:
    if not items:
        raise HelperToolError(f"No {label}s matched the requested criteria")

    if name is None:
        if len(items) == 1:
            return items[0]
        raise ValueError(
            f"Multiple {label}s matched. Provide the {label}_name or {label}_id explicitly."
        )

    expected = name.casefold()
    exact_matches = [
        item
        for item in items
        if (extract_first_string(item, *name_keys) or "").casefold() == expected
    ]
    if len(exact_matches) == 1:
        return exact_matches[0]
    if len(exact_matches) > 1:
        raise HelperToolError(f"Multiple {label}s matched the exact name '{name}'")

    partial_matches = [
        item
        for item in items
        if expected in (extract_first_string(item, *name_keys) or "").casefold()
    ]
    if len(partial_matches) == 1:
        return partial_matches[0]

    available = sorted(
        {
            resource_name
            for item in items
            if (resource_name := extract_first_string(item, *name_keys))
        }
    )
    raise HelperToolError(
        f"Could not resolve {label} '{name}'. Available {label} names: {', '.join(available[:20])}"
    )


def pick_default_vpc(vpcs: list[dict[str, object]]) -> dict[str, object]:
    if not vpcs:
        raise HelperToolError("No VPCs are available in the selected region")
    for candidate in vpcs:
        if candidate.get("name") == "vpc-default":
            return candidate
    return vpcs[0]


def pick_default_subnet(subnets: list[dict[str, object]]) -> dict[str, object]:
    if not subnets:
        raise HelperToolError("No subnets are available in the selected VPC")
    for candidate in subnets:
        if candidate.get("name") == "subnet-default":
            return candidate
    return subnets[0]


def pick_sfs_availability_zone(
    share_types: list[dict[str, object]],
    *,
    requested_share_type: str,
) -> str:
    normalized_share_type = requested_share_type.strip().lower()
    for item in share_types:
        if str(item.get("share_type", "")).strip().lower() != normalized_share_type:
            continue
        for zone in item.get("available_zones") or []:
            if str(zone.get("status", "")).strip().lower() == "active":
                az = zone.get("available_zone")
                if isinstance(az, str) and az.strip():
                    return az
    raise HelperToolError(
        f"No active availability zone found for SFS share type {requested_share_type}"
    )


def pick_access_image(
    images: list[dict[str, object]],
    *,
    image_hint: str | None = None,
) -> dict[str, object]:
    ranked: list[tuple[int, dict[str, object]]] = []
    normalized_hint = image_hint.strip().lower() if image_hint else None
    for image in images:
        if str(image.get("status", "")).strip().lower() != "active":
            continue
        platform = str(image.get("__platform") or image.get("platform") or "").lower()
        os_version = str(image.get("__os_version") or image.get("os_version") or "").lower()
        image_id = image.get("id")
        if not isinstance(image_id, str) or not image_id.strip():
            continue
        if "linux" not in str(image.get("__os_type") or image.get("os_type") or "Linux").lower():
            continue

        score = 100
        image_text = " ".join(
            str(image.get(key) or "")
            for key in ("name", "__platform", "platform", "__os_version", "os_version")
        ).lower()
        if normalized_hint and normalized_hint in image_text:
            score = -1
        elif "ubuntu" in platform and "24.04" in os_version:
            score = 0
        elif "ubuntu" in platform:
            score = 1
        elif "openeuler" in platform or "debian" in platform or "centos" in platform:
            score = 2
        ranked.append((score, image))

    if not ranked:
        raise HelperToolError("No suitable public Linux image was found for the access VM")
    ranked.sort(key=lambda item: (item[0], str(item[1].get("name") or item[1].get("id"))))
    return ranked[0][1]


def normal_azs_for_flavor(flavor: dict[str, object]) -> list[str]:
    extra_specs = flavor.get("os_extra_specs")
    if not isinstance(extra_specs, dict):
        return []
    condition = extra_specs.get("cond:operation:az")
    if not isinstance(condition, str):
        return []

    zones: list[str] = []
    for entry in condition.split(","):
        text = entry.strip()
        if not text.endswith("(normal)"):
            continue
        zones.append(text[: -len("(normal)")])
    return zones


def pick_access_vm_flavor(
    flavors: list[dict[str, object]],
    *,
    preferred_az: str | None,
    flavor_hint: str | None = None,
) -> tuple[dict[str, object], str]:
    ranked: list[tuple[int, int, int, int, str, str]] = []
    normalized_hint = flavor_hint.strip().lower() if flavor_hint else None
    for flavor in flavors:
        flavor_id = flavor.get("id")
        if not isinstance(flavor_id, str) or not flavor_id.strip():
            continue
        if "gpus" in flavor and flavor.get("gpus"):
            continue
        normal_azs = normal_azs_for_flavor(flavor)
        if not normal_azs:
            continue
        vcpus = int(str(flavor.get("vcpus") or 0))
        ram = int(flavor.get("ram") or 0)
        selected_az = preferred_az if preferred_az in normal_azs else normal_azs[0]
        az_penalty = 0 if selected_az == preferred_az else 1
        hint_penalty = 0 if normalized_hint and normalized_hint in flavor_id.lower() else 1
        ranked.append((az_penalty, hint_penalty, vcpus, ram, flavor_id, selected_az))

    if not ranked:
        raise HelperToolError("No suitable ECS flavor was found for the access VM")
    ranked.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]))
    _, _, _, _, flavor_id, selected_az = ranked[0]
    return ({"id": flavor_id}, selected_az)


def extract_server_ips(server: dict[str, object]) -> tuple[str | None, str | None]:
    private_ip = None
    public_ip = None
    addresses = server.get("addresses")
    if not isinstance(addresses, dict):
        return private_ip, public_ip

    for network_entries in addresses.values():
        if not isinstance(network_entries, list):
            continue
        for entry in network_entries:
            if not isinstance(entry, dict):
                continue
            addr = entry.get("addr")
            if not isinstance(addr, str) or not addr.strip():
                continue
            address_type = str(entry.get("OS-EXT-IPS:type") or "").strip().lower()
            if address_type == "floating" and public_ip is None:
                public_ip = addr
            elif address_type == "fixed" and private_ip is None:
                private_ip = addr
    return private_ip, public_ip


def resolve_vpc_and_subnet(
    vpc_service: "HuaweiCloudSdkService",
    *,
    vpc_id: str | None,
    subnet_id: str | None,
) -> tuple[str, str, dict[str, object]]:
    resolved_vpc_id = vpc_id
    if resolved_vpc_id is None:
        vpcs = vpc_service.call_operation("list_vpcs", {"limit": 100})["response"].get("vpcs") or []
        resolved_vpc_id = pick_default_vpc(vpcs)["id"]

    resolved_subnet_id = subnet_id
    if resolved_subnet_id is None:
        subnets = vpc_service.call_operation(
            "list_subnets",
            {"limit": 100, "vpc_id": resolved_vpc_id},
        )["response"].get("subnets") or []
        resolved_subnet_id = pick_default_subnet(subnets)["id"]

    subnet = vpc_service.call_operation(
        "show_subnet",
        {"subnet_id": resolved_subnet_id},
    )["response"].get("subnet") or {}
    return resolved_vpc_id, resolved_subnet_id, subnet


def create_ecs_security_group(
    vpc_service: "HuaweiCloudSdkService",
    *,
    name: str,
    vpc_id: str,
    ssh_cidr: str | None,
) -> str:
    security_group = vpc_service.call_operation(
        "create_security_group",
        {"body": {"security_group": {"name": name, "vpc_id": vpc_id}}},
    )["response"].get("security_group") or {}
    security_group_id = security_group.get("id")
    if not isinstance(security_group_id, str) or not security_group_id.strip():
        raise HelperToolError("Failed to create the ECS security group")

    if ssh_cidr:
        vpc_service.call_operation(
            "create_security_group_rule",
            {
                "body": {
                    "security_group_rule": {
                        "security_group_id": security_group_id,
                        "description": "SSH access for mcp-hwc ECS helper",
                        "direction": "ingress",
                        "ethertype": "IPv4",
                        "protocol": "tcp",
                        "port_range_min": 22,
                        "port_range_max": 22,
                        "remote_ip_prefix": ssh_cidr,
                    }
                }
            },
        )
    return security_group_id


def resolve_ecs_image(
    ims_service: "HuaweiCloudSdkService",
    *,
    image_id: str | None,
    image_hint: str | None,
) -> dict[str, object]:
    if image_id:
        return {"id": image_id}
    images = ims_service.call_operation(
        "list_images",
        {"limit": 100, "visibility": "public", "os_type": "Linux"},
    )["response"].get("images") or []
    return pick_access_image(images, image_hint=image_hint)


def resolve_ecs_flavor(
    ecs_service: "HuaweiCloudSdkService",
    *,
    flavor_id: str | None,
    flavor_hint: str | None,
    availability_zone: str | None,
) -> tuple[dict[str, object], str]:
    if flavor_id:
        if availability_zone is None:
            raise ValueError("availability_zone is required when flavor_id is provided")
        return {"id": flavor_id}, availability_zone
    flavors = ecs_service.call_operation("list_flavors", {"limit": 200})["response"].get("flavors") or []
    return pick_access_vm_flavor(
        flavors,
        preferred_az=availability_zone,
        flavor_hint=flavor_hint,
    )


def list_compatible_ecs_flavors(
    ecs_service: "HuaweiCloudSdkService",
    *,
    min_cpu: int | None = None,
    min_ram_gb: int | None = None,
    eni_required: bool = False,
    az: str | None = None,
) -> list[dict[str, object]]:
    # Use list_flavors_details to get os_extra_specs
    # Wait, ecs v2 list_flavors might already have details in some regions or we use ListFlavorsDetails
    # Checking the SDK, ListFlavorsDetails is often what we want for extra_specs.
    try:
        response = ecs_service.call_operation("list_flavors", {"limit": 500})
    except Exception:
        # Fallback or try another way if list_flavors doesn't give extra_specs
        response = ecs_service.call_operation("list_flavors_details", {"limit": 500})

    flavors = response["response"].get("flavors") or []
    compatible = []

    for f in flavors:
        vcpus = int(str(f.get("vcpus") or 0))
        ram = int(f.get("ram") or 0)  # ram is in MB in ECS API
        ram_gb = ram // 1024

        if min_cpu and vcpus < min_cpu:
            continue
        if min_ram_gb and ram_gb < min_ram_gb:
            continue

        extra_specs = f.get("os_extra_specs") or {}

        if eni_required:
            sub_eni = extra_specs.get("sub_network_interface_max_num")
            if sub_eni is None:
                # Some flavors use different keys or we might need to check if it's a "known" eni flavor
                # But we follow the report's hint
                continue
            try:
                if int(sub_eni) <= 0:
                    continue
            except (ValueError, TypeError):
                continue

        if az:
            normal_azs = normal_azs_for_flavor(f)
            if az not in normal_azs:
                continue

        compatible.append(f)

    return compatible
