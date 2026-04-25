from __future__ import annotations

from collections.abc import Callable
from typing import Any, Protocol

from obs import ObsClient

from .config import ObsConfig
from .obs_endpoints import build_obs_server, normalize_region


class ObsServiceError(RuntimeError):
    """Raised when the OBS SDK reports an operation failure."""


class ObsClientProtocol(Protocol):
    def listBuckets(self, isQueryLocation: bool = True, **kwargs: Any) -> Any:  # noqa: N802
        ...

    def createBucket(self, bucketName: str, **kwargs: Any) -> Any:  # noqa: N802
        ...

    def listObjects(self, bucketName: str, **kwargs: Any) -> Any:  # noqa: N802
        ...

    def getBucketLocation(self, bucketName: str, **kwargs: Any) -> Any:  # noqa: N802
        ...

    def headBucket(self, bucketName: str, **kwargs: Any) -> Any:  # noqa: N802
        ...

    def getObject(self, bucketName: str, objectKey: str, **kwargs: Any) -> Any:  # noqa: N802
        ...

    def headObject(self, bucketName: str, objectKey: str, **kwargs: Any) -> Any:  # noqa: N802
        ...

    def putContent(
        self, bucketName: str, objectKey: str, content: str, **kwargs: Any
    ) -> Any:  # noqa: N802
        ...

    def deleteBucket(self, bucketName: str, **kwargs: Any) -> Any:  # noqa: N802
        ...

    def deleteObject(self, bucketName: str, objectKey: str, **kwargs: Any) -> Any:  # noqa: N802
        ...


ObsClientFactory = Callable[..., ObsClientProtocol]


class ObsService:
    def __init__(
        self,
        config: ObsConfig,
        client_factory: ObsClientFactory = ObsClient,
    ):
        self._config = config
        self._client_factory = client_factory
        self._clients: dict[str, ObsClientProtocol] = {}
        self._bucket_locations: dict[str, str] = {}

    @classmethod
    def from_config(cls, config: ObsConfig) -> "ObsService":
        return cls(config)

    def list_buckets(self) -> dict[str, object]:
        response = self._require_success(
            self._discovery_client().listBuckets(isQueryLocation=True),
            "list buckets",
        )

        buckets = []
        for bucket in getattr(response.body, "buckets", []) or []:
            name = _get_attr(bucket, "name")
            location = _get_attr(bucket, "location")
            normalized_location = normalize_region(location) if location else None
            if name and normalized_location:
                self._bucket_locations[name] = normalized_location

            buckets.append(
                {
                    "name": name,
                    "location": normalized_location,
                    "endpoint": build_obs_server(normalized_location)
                    if normalized_location
                    else None,
                    "created_at": _get_attr(bucket, "create_date", "createDate"),
                }
            )

        return {
            "endpoint": self._config.discovery_server,
            "bucket_count": len(buckets),
            "buckets": buckets,
        }

    def create_bucket(
        self,
        bucket_name: str,
        region: str | None = None,
    ) -> dict[str, object]:
        resolved_region = self._resolve_create_bucket_region(region)
        endpoint = build_obs_server(resolved_region)
        self._require_success(
            self._client_for_region(resolved_region).createBucket(
                bucket_name,
                location=resolved_region,
            ),
            f"create bucket '{bucket_name}'",
        )
        self._bucket_locations[bucket_name] = resolved_region

        return {
            "bucket": bucket_name,
            "location": resolved_region,
            "endpoint": endpoint,
            "created": True,
        }

    def list_objects(
        self,
        bucket_name: str,
        prefix: str | None = None,
        max_keys: int = 100,
        marker: str | None = None,
        region: str | None = None,
    ) -> dict[str, object]:
        if not 1 <= max_keys <= 1000:
            raise ValueError("max_keys must be between 1 and 1000")

        resolved_region = self._resolve_bucket_region(bucket_name, region)
        endpoint = build_obs_server(resolved_region)
        response = self._require_success(
            self._client_for_region(resolved_region).listObjects(
                bucket_name,
                prefix=prefix,
                marker=marker,
                max_keys=max_keys,
                encoding_type="url",
            ),
            f"list objects in bucket '{bucket_name}'",
        )

        body = response.body
        objects = []
        for content in getattr(body, "contents", []) or []:
            owner = _get_attr(content, "owner")
            objects.append(
                {
                    "key": _get_attr(content, "key"),
                    "size": _get_attr(content, "size"),
                    "etag": _get_attr(content, "etag"),
                    "last_modified": _get_attr(
                        content, "lastModified", "last_modified"
                    ),
                    "storage_class": _get_attr(
                        content, "storageClass", "storage_class"
                    ),
                    "owner_id": _get_attr(owner, "owner_id", "ownerId"),
                    "owner_name": _get_attr(owner, "owner_name", "ownerName"),
                }
            )

        common_prefixes = [
            _get_attr(prefix_item, "prefix")
            for prefix_item in getattr(body, "commonPrefixs", []) or []
        ]

        return {
            "bucket": _get_attr(body, "name", default=bucket_name),
            "region": resolved_region,
            "endpoint": endpoint,
            "location": _get_attr(body, "location", default=resolved_region),
            "prefix": _get_attr(body, "prefix"),
            "marker": _get_attr(body, "marker"),
            "max_keys": _get_attr(body, "max_keys", "maxKeys", default=max_keys),
            "is_truncated": _get_attr(
                body, "is_truncated", "isTruncated", default=False
            ),
            "next_marker": _get_attr(body, "next_marker", "nextMarker"),
            "common_prefixes": common_prefixes,
            "objects": objects,
        }

    def get_bucket_location(self, bucket_name: str) -> dict[str, str | None]:
        location = self._discover_bucket_region(bucket_name)
        return {
            "bucket": bucket_name,
            "location": location,
            "endpoint": build_obs_server(location),
        }

    def head_bucket(
        self,
        bucket_name: str,
        region: str | None = None,
    ) -> dict[str, object]:
        resolved_region = self._resolve_bucket_region(bucket_name, region)
        endpoint = build_obs_server(resolved_region)
        response = self._require_success(
            self._client_for_region(resolved_region).headBucket(bucket_name),
            f"head bucket '{bucket_name}'",
        )

        return {
            "bucket": bucket_name,
            "region": resolved_region,
            "endpoint": endpoint,
            "status": getattr(response, "status", None),
            "request_id": getattr(response, "requestId", None),
        }

    def get_object_text(
        self,
        bucket_name: str,
        object_key: str,
        encoding: str = "utf-8",
        region: str | None = None,
    ) -> dict[str, object]:
        resolved_region = self._resolve_bucket_region(bucket_name, region)
        endpoint = build_obs_server(resolved_region)
        response = self._require_success(
            self._client_for_region(resolved_region).getObject(
                bucket_name,
                object_key,
                loadStreamInMemory=True,
            ),
            f"get object '{object_key}' from bucket '{bucket_name}'",
        )

        buffer = _get_attr(response.body, "buffer")
        if buffer is None:
            raise ObsServiceError(
                f"OBS did not return in-memory data for '{bucket_name}/{object_key}'"
            )

        if isinstance(buffer, str):
            text = buffer
            size_bytes = len(buffer.encode(encoding))
        else:
            try:
                text = buffer.decode(encoding)
            except UnicodeDecodeError as exc:
                raise ObsServiceError(
                    f"Object '{bucket_name}/{object_key}' could not be decoded as {encoding}"
                ) from exc
            size_bytes = len(buffer)

        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": resolved_region,
            "endpoint": endpoint,
            "encoding": encoding,
            "size_bytes": size_bytes,
            "text": text,
        }

    def head_object(
        self,
        bucket_name: str,
        object_key: str,
        region: str | None = None,
        version_id: str | None = None,
    ) -> dict[str, object]:
        resolved_region = self._resolve_bucket_region(bucket_name, region)
        endpoint = build_obs_server(resolved_region)
        response = self._require_success(
            self._client_for_region(resolved_region).headObject(
                bucket_name,
                object_key,
                versionId=version_id,
            ),
            f"head object '{object_key}' in bucket '{bucket_name}'",
        )
        header = _get_attr(response, "header", "body")

        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": resolved_region,
            "endpoint": endpoint,
            "etag": _get_attr(header, "etag"),
            "content_length": _get_attr(
                header, "contentLength", "content_length", "content_length_value"
            ),
            "content_type": _get_attr(header, "contentType", "content_type"),
            "last_modified": _get_attr(header, "lastModified", "last_modified"),
            "version_id": _get_attr(header, "versionId", "version_id"),
            "metadata": _get_attr(header, "metadata", default={}) or {},
        }

    def put_text_object(
        self,
        bucket_name: str,
        object_key: str,
        content: str,
        region: str | None = None,
    ) -> dict[str, object]:
        resolved_region = self._resolve_bucket_region(bucket_name, region)
        endpoint = build_obs_server(resolved_region)
        response = self._require_success(
            self._client_for_region(resolved_region).putContent(
                bucket_name,
                object_key,
                content,
            ),
            f"put object '{object_key}' into bucket '{bucket_name}'",
        )

        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": resolved_region,
            "endpoint": endpoint,
            "etag": _get_attr(response.body, "etag"),
            "version_id": _get_attr(response.body, "versionId", "version_id"),
            "object_url": _get_attr(response.body, "objectUrl", "object_url"),
        }

    def delete_bucket(
        self,
        bucket_name: str,
        region: str | None = None,
    ) -> dict[str, object]:
        resolved_region = self._resolve_bucket_region(bucket_name, region)
        endpoint = build_obs_server(resolved_region)
        self._require_success(
            self._client_for_region(resolved_region).deleteBucket(bucket_name),
            f"delete bucket '{bucket_name}'",
        )
        self._bucket_locations.pop(bucket_name, None)

        return {
            "bucket": bucket_name,
            "region": resolved_region,
            "endpoint": endpoint,
            "deleted": True,
        }

    def delete_object(
        self,
        bucket_name: str,
        object_key: str,
        region: str | None = None,
        version_id: str | None = None,
    ) -> dict[str, object]:
        resolved_region = self._resolve_bucket_region(bucket_name, region)
        endpoint = build_obs_server(resolved_region)
        self._require_success(
            self._client_for_region(resolved_region).deleteObject(
                bucket_name,
                object_key,
                versionId=version_id,
            ),
            f"delete object '{object_key}' from bucket '{bucket_name}'",
        )

        return {
            "bucket": bucket_name,
            "key": object_key,
            "region": resolved_region,
            "endpoint": endpoint,
            "version_id": version_id,
            "deleted": True,
        }

    def _resolve_bucket_region(self, bucket_name: str, region: str | None) -> str:
        if region:
            normalized = normalize_region(region)
            self._bucket_locations[bucket_name] = normalized
            return normalized

        return self._discover_bucket_region(bucket_name)

    def _resolve_create_bucket_region(self, region: str | None) -> str:
        if region:
            return normalize_region(region)
        if self._config.region:
            return self._config.region
        raise ValueError("region is required to create a bucket")

    def _discover_bucket_region(self, bucket_name: str) -> str:
        cached = self._bucket_locations.get(bucket_name)
        if cached:
            return cached

        try:
            response = self._require_success(
                self._discovery_client().listBuckets(isQueryLocation=True),
                "list buckets for region discovery",
            )
            for bucket in getattr(response.body, "buckets", []) or []:
                name = _get_attr(bucket, "name")
                location = _get_attr(bucket, "location")
                if name and location:
                    self._bucket_locations[name] = normalize_region(location)

            cached = self._bucket_locations.get(bucket_name)
            if cached:
                return cached
        except ObsServiceError:
            pass

        response = self._require_success(
            self._discovery_client().getBucketLocation(bucket_name),
            f"get bucket location for '{bucket_name}'",
        )
        location = _get_attr(response.body, "location")
        if not location:
            raise ObsServiceError(
                f"OBS did not return a location for bucket '{bucket_name}'"
            )

        normalized = normalize_region(location)
        self._bucket_locations[bucket_name] = normalized
        return normalized

    def _discovery_client(self) -> ObsClientProtocol:
        return self._client_for_server(self._config.discovery_server)

    def _client_for_region(self, region: str) -> ObsClientProtocol:
        return self._client_for_server(build_obs_server(region))

    def _client_for_server(self, server: str) -> ObsClientProtocol:
        client = self._clients.get(server)
        if client is None:
            client = self._client_factory(
                access_key_id=self._config.access_key_id,
                secret_access_key=self._config.secret_access_key,
                security_token=self._config.security_token,
                server=server,
            )
            self._clients[server] = client
        return client

    def _require_success(self, response: Any, operation: str) -> Any:
        status = getattr(response, "status", None)
        if status is not None and status < 300:
            return response

        details = []
        if status is not None:
            details.append(f"status={status}")
        error_code = getattr(response, "errorCode", None)
        error_message = getattr(response, "errorMessage", None)
        request_id = getattr(response, "requestId", None)
        if error_code:
            details.append(f"error_code={error_code}")
        if error_message:
            details.append(f"error_message={error_message}")
        if request_id:
            details.append(f"request_id={request_id}")

        details_text = (
            ", ".join(details) if details else "no details returned by OBS SDK"
        )
        raise ObsServiceError(f"Failed to {operation}: {details_text}")


def _get_attr(obj: Any, *names: str, default: Any = None) -> Any:
    if obj is None:
        return default
    for name in names:
        if hasattr(obj, name):
            return getattr(obj, name)
    return default
