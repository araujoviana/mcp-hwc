from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

from dotenv import dotenv_values, find_dotenv

from .obs_endpoints import (
    OBS_GLOBAL_SERVER,
    build_obs_server,
    normalize_region,
    normalize_server,
)
from .regions import normalize_region_input


class ConfigError(ValueError):
    """Raised when Huawei Cloud configuration is missing or invalid."""


_HUAWEI_ENDPOINT_REGION_PATTERN = re.compile(
    r"^[a-z0-9-]+\.(?P<region>[a-z0-9-]+)\.myhuaweicloud\.com$"
)


@dataclass(frozen=True)
class CloudApiConfig:
    access_key_id: str
    secret_access_key: str
    project_id: str | None = None
    region: str | None = None
    security_token: str | None = None
    endpoint: str | None = None

    @classmethod
    def from_env(
        cls,
        service_name: str,
        env_file: str | Path | None = None,
        *,
        region: str | None = None,
        project_id: str | None = None,
        endpoint: str | None = None,
    ) -> "CloudApiConfig":
        env_values = _load_env_values(env_file)
        service_key = service_name.strip().upper()
        if not service_key:
            raise ConfigError("Service name cannot be empty")

        access_key_id = _first_present(
            env_values,
            "HWC_AK",
            "HWC_OBS_ACCESS_KEY_ID",
            "AccessKeyID",
        )
        secret_access_key = _first_present(
            env_values,
            "HWC_SK",
            "HWC_OBS_SECRET_ACCESS_KEY",
            "SecretAccessKey",
        )
        security_token = _first_present(
            env_values,
            "HWC_SECURITY_TOKEN",
            "HWC_OBS_SECURITY_TOKEN",
            "SecurityToken",
        )
        resolved_region = region
        if resolved_region is None:
            resolved_region = _first_present(
                env_values,
                f"HWC_{service_key}_REGION",
                "HWC_REGION",
            )

        resolved_project_id = project_id
        if resolved_project_id is None:
            resolved_project_id = _first_present(
                env_values,
                f"HWC_{service_key}_PROJECT_ID",
                "HWC_PROJECT_ID",
            )

        resolved_endpoint = endpoint
        if resolved_endpoint is None:
            resolved_endpoint = _first_present(
                env_values, f"HWC_{service_key}_ENDPOINT"
            )

        missing = []
        if not access_key_id:
            missing.append("HWC_AK")
        if not secret_access_key:
            missing.append("HWC_SK")

        if missing:
            missing_fields = ", ".join(missing)
            raise ConfigError(f"Missing {service_key} configuration: {missing_fields}")

        normalized_endpoint = (
            _normalize_endpoint(resolved_endpoint)
            if resolved_endpoint is not None
            else None
        )
        normalized_region = (
            _normalize_cloud_region(resolved_region)
            if resolved_region is not None
            else _infer_region_from_endpoint(normalized_endpoint)
        )

        return cls(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            project_id=_normalize_project_id(resolved_project_id),
            region=normalized_region,
            security_token=security_token,
            endpoint=normalized_endpoint,
        )


@dataclass(frozen=True)
class ObsConfig:
    access_key_id: str
    secret_access_key: str
    security_token: str | None = None
    region: str | None = None
    server: str | None = None

    @property
    def discovery_server(self) -> str:
        if self.server:
            return self.server
        if self.region:
            return build_obs_server(self.region)
        return OBS_GLOBAL_SERVER

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "ObsConfig":
        env_values = _load_env_values(env_file)

        access_key_id = _first_present(
            env_values,
            "HWC_AK",
            "HWC_OBS_ACCESS_KEY_ID",
            "AccessKeyID",
        )
        secret_access_key = _first_present(
            env_values,
            "HWC_SK",
            "HWC_OBS_SECRET_ACCESS_KEY",
            "SecretAccessKey",
        )
        region = _first_present(env_values, "HWC_REGION", "HWC_OBS_REGION")
        server = _first_present(env_values, "HWC_OBS_SERVER")
        security_token = _first_present(
            env_values,
            "HWC_SECURITY_TOKEN",
            "HWC_OBS_SECURITY_TOKEN",
            "SecurityToken",
        )

        missing = []
        if not access_key_id:
            missing.append("HWC_AK")
        if not secret_access_key:
            missing.append("HWC_SK")

        if missing:
            missing_fields = ", ".join(missing)
            raise ConfigError(f"Missing OBS configuration: {missing_fields}")

        normalized_region = _normalize_region(region) if region else None
        normalized_server = _normalize_server(server) if server else None

        return cls(
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            security_token=security_token,
            region=normalized_region,
            server=normalized_server,
        )


def _resolve_env_file() -> Path | None:
    configured_path = os.getenv("MCP_HWC_ENV_FILE")
    if configured_path:
        return Path(configured_path)
    discovered = find_dotenv(usecwd=True)
    if discovered:
        return Path(discovered)
    return None


def _load_env_values(env_file: str | Path | None) -> dict[str, str]:
    path = Path(env_file) if env_file else _resolve_env_file()
    if not path or not path.exists():
        return {}

    return {
        key: value
        for key, value in dotenv_values(path).items()
        if key is not None and value is not None
    }


def _first_present(env_values: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
        value = env_values.get(name)
        if value:
            return value
    return None


def _normalize_project_id(project_id: str | None) -> str | None:
    if project_id is None:
        return None
    value = project_id.strip()
    return value or None


def _normalize_region(region: str) -> str:
    try:
        return normalize_region(region)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _normalize_server(server: str) -> str:
    try:
        return normalize_server(server)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _normalize_cloud_region(region: str) -> str:
    try:
        return normalize_region_input(region)
    except ValueError as exc:
        raise ConfigError(str(exc)) from exc


def _normalize_endpoint(endpoint: str) -> str:
    value = endpoint.strip()
    if not value:
        raise ConfigError("Endpoint cannot be empty")

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ConfigError(
            "Endpoint must be a valid URL, for example "
            "https://ecs.ap-southeast-1.myhuaweicloud.com"
        )

    return value.rstrip("/")


def _infer_region_from_endpoint(endpoint: str | None) -> str | None:
    if endpoint is None:
        return None

    host = urlparse(endpoint).netloc.lower()
    match = _HUAWEI_ENDPOINT_REGION_PATTERN.fullmatch(host)
    if match is None:
        return None

    return match.group("region")
