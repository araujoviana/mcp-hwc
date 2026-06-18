from __future__ import annotations

import os
from functools import lru_cache
from typing import Callable, TypeVar, TYPE_CHECKING
from pydantic import ValidationError

from mcp_hwc.core.config import CloudApiConfig, ObsConfig
from mcp_hwc.cloud_services.obs_service import ObsService
from mcp_hwc.cloud_services.ssh_service import SshService
from mcp_hwc.cloud_services.cli_service import CliService
from mcp_hwc.pricing.bss_pricing import BssPricingBackend
from mcp_hwc.pricing.persistence import QuoteStore
from mcp_hwc.core.sdk_service import HuaweiCloudSdkService, resolve_service_spec

if TYPE_CHECKING:
    from mcp_hwc.pricing.bss_pricing import BssPricingBackend
    from mcp_hwc.pricing.persistence import QuoteStore

T = TypeVar("T")

@lru_cache(maxsize=1)
def get_obs_service() -> ObsService:
    return ObsService.from_config(ObsConfig.from_env())

@lru_cache(maxsize=1)
def get_ssh_service() -> SshService:
    return SshService()

@lru_cache(maxsize=1)
def get_cli_service() -> CliService:
    return CliService()

@lru_cache(maxsize=1)
def get_bss_pricing_backend() -> BssPricingBackend:
    return BssPricingBackend(CloudApiConfig.from_env("BSS"))

@lru_cache(maxsize=1)
def get_quote_store() -> QuoteStore:
    return QuoteStore()

@lru_cache(maxsize=None)
def get_sdk_service(
    service_name: str,
    api_version: str | None = None,
    region: str | None = None,
    project_id: str | None = None,
    domain_id: str | None = None,
    endpoint: str | None = None,
) -> HuaweiCloudSdkService:
    resolved_spec = resolve_service_spec(service_name, api_version)
    return HuaweiCloudSdkService(
        CloudApiConfig.from_env(
            resolved_spec.env_key,
            region=region,
            project_id=project_id,
            domain_id=domain_id,
            endpoint=endpoint,
        ),
        resolved_spec.name,
        api_version=resolved_spec.api_version,
    )

def _run_tool_call(call: Callable[[], T]) -> T:
    from mcp.server.fastmcp.exceptions import ToolError
    from mcp_hwc.core.errors import HelperToolError
    from mcp_hwc.cloud_services.obs_service import ObsServiceError
    from mcp_hwc.cloud_services.ssh_service import SshServiceError
    from mcp_hwc.cloud_services.cli_service import CliServiceError
    from mcp_hwc.core.config import ConfigError
    from mcp_hwc.core.sdk_service import HuaweiCloudSdkError
    from mcp_hwc.pricing.bss_pricing import PricingNotAvailable

    try:
        return call()
    except ValidationError as exc:
        # Self-correcting error for LLM: provide explicit instructions on schema failure
        errors = []
        for error in exc.errors():
            loc = ".".join(str(i) for i in error["loc"])
            msg = error["msg"]
            errors.append(f"- {loc}: {msg}")

        error_details = "\n".join(errors)
        raise ToolError(
            f"Invalid tool parameters provided. Please correct the following and try again:\n{error_details}"
        ) from exc
    except (
        ConfigError,
        CliServiceError,
        HelperToolError,
        ObsServiceError,
        HuaweiCloudSdkError,
        PricingNotAvailable,
        SshServiceError,
        ValueError,
    ) as exc:
        msg = str(exc)
        # Enhance common flavor compatibility errors
        if "subeni quota is 0" in msg or "Eni network is not supported" in msg:
            msg += (
                ". Try using a different flavor that supports ENI. "
                "You can use `ecs_list_compatible_flavors` with `eni_required=True` to find one."
            )
        raise ToolError(msg) from exc

def clear_caches() -> None:
    get_obs_service.cache_clear()
    get_ssh_service.cache_clear()
    get_cli_service.cache_clear()
    get_sdk_service.cache_clear()
    get_bss_pricing_backend.cache_clear()
    get_quote_store.cache_clear()
