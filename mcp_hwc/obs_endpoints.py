from __future__ import annotations

import re
from urllib.parse import urlparse

from .regions import normalize_region_input

OBS_GLOBAL_SERVER = "https://obs.myhuaweicloud.com"
OBS_SERVER_TEMPLATE = "https://obs.{region}.myhuaweicloud.com"

OBS_ENDPOINT_REFERENCE_URLS = (
    "https://developer.huaweicloud.com/endpoint?OBS",
    "https://developer.huaweicloud.com/intl/en-us/endpoint?OBS",
    "https://console.huaweicloud.com/apiexplorer/#/endpoint/OBS",
    "https://console-intl.huaweicloud.com/apiexplorer/#/endpoint/OBS",
)

_REGION_PATTERN = re.compile(r"^[a-z0-9-]+$")


def normalize_region(region: str) -> str:
    value = normalize_region_input(region, field_name="OBS region")
    if not value:
        raise ValueError("OBS region cannot be empty")

    if not _REGION_PATTERN.fullmatch(value):
        raise ValueError("OBS region must look like 'ap-southeast-1' or 'cn-north-4'")

    return value


def build_obs_server(region: str) -> str:
    return OBS_SERVER_TEMPLATE.format(region=normalize_region(region))


def normalize_server(server: str) -> str:
    value = server.strip()
    if not value:
        raise ValueError("HWC_OBS_SERVER cannot be empty")

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(
            "HWC_OBS_SERVER must be a valid OBS endpoint, for example "
            "https://obs.ap-southeast-1.myhuaweicloud.com"
        )

    return value.rstrip("/")
