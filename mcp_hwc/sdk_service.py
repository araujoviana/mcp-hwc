from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from importlib import import_module
import re
from typing import Any, Callable

from huaweicloudsdkcore.auth.credentials import BasicCredentials
from huaweicloudsdkcore.exceptions import exceptions as sdk_exceptions
from huaweicloudsdkcore.utils.http_utils import sanitize_for_serialization
from huaweicloudsdkecs.v2 import EcsClient
from huaweicloudsdkecs.v2.region.ecs_region import EcsRegion
from huaweicloudsdkims.v2 import ImsClient
from huaweicloudsdkims.v2.region.ims_region import ImsRegion
from huaweicloudsdkrds.v3 import RdsClient
from huaweicloudsdkrds.v3.region.rds_region import RdsRegion
from huaweicloudsdkvpc.v2 import VpcClient
from huaweicloudsdkvpc.v2.region.vpc_region import VpcRegion

from .config import CloudApiConfig

_PRIMITIVE_TYPES = {"str", "int", "float", "bool", "object"}
_PASSTHROUGH_TYPES = _PRIMITIVE_TYPES | {"none_type", "NoneType"}


class HuaweiCloudSdkError(RuntimeError):
    """Raised when an SDK-backed service operation fails."""


@dataclass(frozen=True)
class ServiceSpec:
    name: str
    client_class: type[Any]
    region_class: type[Any]
    model_package: str
    endpoint_template: str

    def endpoint_for_region(self, region: str) -> str:
        return self.endpoint_template.format(region=region)


SERVICE_SPECS = {
    "ecs": ServiceSpec(
        name="ecs",
        client_class=EcsClient,
        region_class=EcsRegion,
        model_package="huaweicloudsdkecs.v2.model",
        endpoint_template="https://ecs.{region}.myhuaweicloud.com",
    ),
    "ims": ServiceSpec(
        name="ims",
        client_class=ImsClient,
        region_class=ImsRegion,
        model_package="huaweicloudsdkims.v2.model",
        endpoint_template="https://ims.{region}.myhuaweicloud.com",
    ),
    "rds": ServiceSpec(
        name="rds",
        client_class=RdsClient,
        region_class=RdsRegion,
        model_package="huaweicloudsdkrds.v3.model",
        endpoint_template="https://rds.{region}.myhuaweicloud.com",
    ),
    "vpc": ServiceSpec(
        name="vpc",
        client_class=VpcClient,
        region_class=VpcRegion,
        model_package="huaweicloudsdkvpc.v2.model",
        endpoint_template="https://vpc.{region}.myhuaweicloud.com",
    ),
}

ClientFactory = Callable[[CloudApiConfig, ServiceSpec], Any]


def build_sdk_client(config: CloudApiConfig, spec: ServiceSpec) -> Any:
    if config.project_id:
        credentials = BasicCredentials(
            config.access_key_id,
            config.secret_access_key,
            config.project_id,
        )
    else:
        credentials = BasicCredentials(
            config.access_key_id,
            config.secret_access_key,
        )
    if config.security_token:
        credentials = credentials.with_security_token(config.security_token)

    builder = spec.client_class.new_builder().with_credentials(credentials)
    if config.endpoint:
        if config.region is None and config.project_id is None:
            raise ValueError(
                f"{spec.name.upper()} region is required to resolve project_id automatically"
            )
        return builder.with_endpoint(config.endpoint).build()

    if config.region is None:
        raise ValueError(f"{spec.name.upper()} region is required to call the SDK")

    region = spec.region_class.value_of(config.region)
    if region is not None:
        return builder.with_region(region).build()

    return builder.with_endpoint(spec.endpoint_for_region(config.region)).build()


class HuaweiCloudSdkService:
    def __init__(
        self,
        config: CloudApiConfig,
        service_name: str,
        client_factory: ClientFactory = build_sdk_client,
    ):
        try:
            self._spec = SERVICE_SPECS[service_name]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported Huawei Cloud service: {service_name}"
            ) from exc

        self._config = config
        self._client_factory = client_factory
        self._client: Any | None = None

    @property
    def endpoint(self) -> str | None:
        if self._config.endpoint:
            return self._config.endpoint
        if self._config.region is None:
            return None
        return self._spec.endpoint_for_region(self._config.region)

    def list_operations(
        self,
        query: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> dict[str, object]:
        if not 1 <= limit <= 500:
            raise ValueError("limit must be between 1 and 500")
        if offset < 0:
            raise ValueError("offset must be zero or greater")

        operations = self._operations()
        if query:
            query_text = query.strip().lower()
            operations = [
                operation for operation in operations if query_text in operation.lower()
            ]

        page = operations[offset : offset + limit]
        return {
            "service": self._spec.name,
            "region": self._config.region,
            "endpoint": self.endpoint,
            "total_count": len(operations),
            "returned_count": len(page),
            "offset": offset,
            "limit": limit,
            "operations": page,
        }

    def describe_operation(
        self,
        operation: str,
        max_depth: int = 4,
    ) -> dict[str, object]:
        if not 1 <= max_depth <= 8:
            raise ValueError("max_depth must be between 1 and 8")

        normalized_operation = self._normalize_operation(operation)
        request_class = self._request_class(normalized_operation)
        schema = self._describe_type(request_class.__name__, max_depth, set())
        template = self._build_template(request_class.__name__, max_depth, set())

        return {
            "service": self._spec.name,
            "operation": normalized_operation,
            "request_model": request_class.__name__,
            "request_schema": schema,
            "request_template": template,
            "notes": "Use SDK attribute names for request fields. API header/query names are also accepted.",
        }

    def call_operation(
        self,
        operation: str,
        parameters: dict[str, object] | None = None,
    ) -> dict[str, object]:
        normalized_operation = self._normalize_operation(operation)
        request_class = self._request_class(normalized_operation)
        request_payload = parameters or {}
        if not isinstance(request_payload, dict):
            raise ValueError("parameters must be an object")

        request = self._coerce_value(request_class.__name__, request_payload)

        try:
            response = getattr(self._get_client(), normalized_operation)(request)
        except sdk_exceptions.ClientRequestException as exc:
            raise HuaweiCloudSdkError(str(exc)) from exc
        except sdk_exceptions.SdkException as exc:
            raise HuaweiCloudSdkError(str(exc)) from exc

        return {
            "service": self._spec.name,
            "operation": normalized_operation,
            "region": self._config.region,
            "endpoint": self.endpoint,
            "response": sanitize_for_serialization(response),
        }

    def _get_client(self) -> Any:
        if self._client is None:
            self._client = self._client_factory(self._config, self._spec)
        return self._client

    def _operations(self) -> list[str]:
        return [
            name
            for name in self._all_operations()
            if not name.endswith("_invoker") and name not in {"call_api", "new_builder"}
        ]

    @lru_cache(maxsize=None)
    def _all_operations(self) -> list[str]:
        return sorted(
            name
            for name in dir(self._spec.client_class)
            if not name.startswith("_")
            and callable(getattr(self._spec.client_class, name))
        )

    def _normalize_operation(self, operation: str) -> str:
        candidate = operation.strip()
        if not candidate:
            raise ValueError("operation cannot be empty")
        if candidate not in self._operations():
            raise ValueError(
                f"Unsupported {self._spec.name.upper()} operation '{candidate}'"
            )
        return candidate

    def _describe_type(
        self,
        type_name: str,
        depth: int,
        visited: set[str],
    ) -> dict[str, object]:
        list_item_type = _parse_list_type(type_name)
        if list_item_type is not None:
            return {
                "kind": "list",
                "type": type_name,
                "items": self._describe_type(list_item_type, depth - 1, visited),
            }

        dict_types = _parse_dict_types(type_name)
        if dict_types is not None:
            _, value_type = dict_types
            return {
                "kind": "dict",
                "type": type_name,
                "values": self._describe_type(value_type, depth - 1, visited),
            }

        if type_name in _PASSTHROUGH_TYPES:
            return {"kind": "primitive", "type": type_name}

        if type_name == "datetime":
            return {"kind": "primitive", "type": "datetime"}

        if depth <= 0 or type_name in visited:
            return {"kind": "object", "model": type_name, "truncated": True}

        try:
            model_class = self._model_class(type_name)
        except (AttributeError, ModuleNotFoundError):
            return {"kind": "opaque", "type": type_name}

        fields = []
        next_visited = visited | {type_name}
        for attribute_name, attribute_type in model_class.openapi_types.items():
            fields.append(
                {
                    "name": attribute_name,
                    "api_name": model_class.attribute_map.get(
                        attribute_name, attribute_name
                    ),
                    "type": attribute_type,
                    "schema": self._describe_type(
                        attribute_type, depth - 1, next_visited
                    ),
                }
            )

        return {
            "kind": "object",
            "model": type_name,
            "fields": fields,
        }

    def _build_template(
        self,
        type_name: str,
        depth: int,
        visited: set[str],
    ) -> Any:
        list_item_type = _parse_list_type(type_name)
        if list_item_type is not None:
            return [self._build_template(list_item_type, depth - 1, visited)]

        dict_types = _parse_dict_types(type_name)
        if dict_types is not None:
            _, value_type = dict_types
            return {"<key>": self._build_template(value_type, depth - 1, visited)}

        if type_name == "datetime":
            return "<iso-8601-datetime>"

        if type_name in _PASSTHROUGH_TYPES:
            return f"<{type_name}>"

        if depth <= 0 or type_name in visited:
            return f"<{type_name}>"

        try:
            model_class = self._model_class(type_name)
        except (AttributeError, ModuleNotFoundError):
            return f"<{type_name}>"

        next_visited = visited | {type_name}
        return {
            attribute_name: self._build_template(
                attribute_type, depth - 1, next_visited
            )
            for attribute_name, attribute_type in model_class.openapi_types.items()
        }

    def _coerce_value(self, expected_type: str, value: Any) -> Any:
        if value is None:
            return None

        list_item_type = _parse_list_type(expected_type)
        if list_item_type is not None:
            if not isinstance(value, list):
                raise ValueError(f"Expected a list for {expected_type}")
            return [self._coerce_value(list_item_type, item) for item in value]

        dict_types = _parse_dict_types(expected_type)
        if dict_types is not None:
            key_type, value_type = dict_types
            if not isinstance(value, dict):
                raise ValueError(f"Expected an object for {expected_type}")
            if key_type != "str":
                raise ValueError(f"Unsupported dict key type: {key_type}")
            return {
                str(key): self._coerce_value(value_type, item)
                for key, item in value.items()
            }

        if expected_type in _PRIMITIVE_TYPES:
            return _coerce_primitive(expected_type, value)

        if expected_type in {"none_type", "NoneType"}:
            return value

        if expected_type == "datetime":
            if isinstance(value, datetime):
                return value
            if isinstance(value, str):
                return datetime.fromisoformat(value.replace("Z", "+00:00"))
            raise ValueError("datetime values must be ISO-8601 strings")

        model_class = self._model_class(expected_type)
        if isinstance(value, model_class):
            return value
        if not isinstance(value, dict):
            raise ValueError(f"Expected an object for {expected_type}")

        attribute_types = model_class.openapi_types
        api_names = {
            api_name: attribute_name
            for attribute_name, api_name in model_class.attribute_map.items()
        }

        kwargs = {}
        unknown_fields = []
        for key, item in value.items():
            attribute_name = key if key in attribute_types else api_names.get(key)
            if attribute_name is None:
                unknown_fields.append(key)
                continue

            kwargs[attribute_name] = self._coerce_value(
                attribute_types[attribute_name], item
            )

        if unknown_fields:
            unknown_text = ", ".join(sorted(unknown_fields))
            raise ValueError(f"Unknown fields for {expected_type}: {unknown_text}")

        return model_class(**kwargs)

    @lru_cache(maxsize=None)
    def _request_class(self, operation: str) -> type[Any]:
        return self._import_model_class(
            f"{operation}_request",
            f"{_snake_to_pascal(operation)}Request",
        )

    @lru_cache(maxsize=None)
    def _model_class(self, type_name: str) -> type[Any]:
        return self._import_model_class(_pascal_to_snake(type_name), type_name)

    def _import_model_class(self, module_name: str, class_name: str) -> type[Any]:
        module = import_module(f"{self._spec.model_package}.{module_name}")
        return getattr(module, class_name)


def _coerce_primitive(expected_type: str, value: Any) -> Any:
    if expected_type == "object":
        return value
    if expected_type == "str":
        if isinstance(value, (str, int, float, bool)):
            return str(value)
        raise ValueError("String fields must be strings, numbers, or booleans")
    if expected_type == "int":
        if isinstance(value, bool):
            raise ValueError("Integer fields cannot be booleans")
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            return int(value)
        raise ValueError("Integer fields must be integers")
    if expected_type == "float":
        if isinstance(value, bool):
            raise ValueError("Float fields cannot be booleans")
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            return float(value)
        raise ValueError("Float fields must be numeric")
    if expected_type == "bool":
        if isinstance(value, bool):
            return value
        raise ValueError("Boolean fields must be true or false")
    return value


def _parse_list_type(type_name: str) -> str | None:
    if type_name.startswith("list[") and type_name.endswith("]"):
        return type_name[5:-1].strip()
    return None


def _parse_dict_types(type_name: str) -> tuple[str, str] | None:
    if not type_name.startswith("dict(") or not type_name.endswith(")"):
        return None

    inner = type_name[5:-1]
    parts = _split_top_level(inner)
    if len(parts) != 2:
        raise ValueError(f"Unsupported dict type declaration: {type_name}")
    return parts[0].strip(), parts[1].strip()


def _split_top_level(value: str) -> list[str]:
    parts = []
    current = []
    depth = 0
    for char in value:
        if char in "[(":
            depth += 1
        elif char in "])":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue

        current.append(char)

    if current:
        parts.append("".join(current))
    return parts


def _snake_to_pascal(value: str) -> str:
    return "".join(part.capitalize() for part in value.split("_"))


def _pascal_to_snake(value: str) -> str:
    first_pass = re.sub(r"(.)([A-Z][a-z]+)", r"\1_\2", value)
    return re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", first_pass).lower()
