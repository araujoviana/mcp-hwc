from types import SimpleNamespace
from pathlib import Path

import pytest

from mcp_hwc.core.config import ObsConfig
from mcp_hwc.cloud_services.obs_endpoints import OBS_GLOBAL_SERVER, build_obs_server
from mcp_hwc.cloud_services.obs_service import ObsService, ObsServiceError


def make_response(
    status: int, body: object | None = None, **extra: object
) -> SimpleNamespace:
    payload = {
        "status": status,
        "body": body,
        "errorCode": None,
        "errorMessage": None,
        "requestId": "req-123",
    }
    payload.update(extra)
    return SimpleNamespace(**payload)


class FakeClientFactory:
    def __init__(self, clients_by_server: dict[str, object]):
        self._clients_by_server = clients_by_server
        self.created_servers: list[str] = []

    def __call__(
        self,
        *,
        access_key_id: str,
        secret_access_key: str,
        security_token: str | None,
        server: str,
    ) -> object:
        self.created_servers.append(server)
        return self._clients_by_server[server]


def make_config() -> ObsConfig:
    return ObsConfig(access_key_id="test-ak", secret_access_key="test-sk")


def test_list_buckets_returns_serializable_shape() -> None:
    factory = FakeClientFactory(
        {
            OBS_GLOBAL_SERVER: SimpleNamespace(
                listBuckets=lambda isQueryLocation=True: make_response(
                    200,
                    SimpleNamespace(
                        buckets=[
                            SimpleNamespace(
                                name="alpha",
                                location="ap-southeast-1",
                                create_date="2026-01-01T00:00:00.000Z",
                            )
                        ]
                    ),
                )
            )
        }
    )

    service = ObsService(make_config(), client_factory=factory)

    result = service.list_buckets()

    assert result == {
        "endpoint": OBS_GLOBAL_SERVER,
        "bucket_count": 1,
        "buckets": [
            {
                "name": "alpha",
                "location": "ap-southeast-1",
                "endpoint": build_obs_server("ap-southeast-1"),
                "created_at": "2026-01-01T00:00:00.000Z",
            }
        ],
    }


def test_list_objects_auto_resolves_bucket_region() -> None:
    regional_server = build_obs_server("ap-southeast-1")
    factory = FakeClientFactory(
        {
            OBS_GLOBAL_SERVER: SimpleNamespace(
                listBuckets=lambda isQueryLocation=True: make_response(
                    200,
                    SimpleNamespace(
                        buckets=[
                            SimpleNamespace(
                                name="demo-bucket",
                                location="ap-southeast-1",
                            )
                        ]
                    ),
                )
            ),
            regional_server: SimpleNamespace(
                listObjects=lambda bucketName, **kwargs: make_response(
                    200,
                    SimpleNamespace(
                        name=bucketName,
                        location="ap-southeast-1",
                        prefix=kwargs["prefix"],
                        marker=kwargs["marker"],
                        max_keys=kwargs["max_keys"],
                        is_truncated=False,
                        next_marker=None,
                        commonPrefixs=[SimpleNamespace(prefix="logs/")],
                        contents=[
                            SimpleNamespace(
                                key="logs/app.log",
                                size=42,
                                etag="etag-1",
                                lastModified="2026-01-01T00:00:00.000Z",
                                storageClass="STANDARD",
                                owner=SimpleNamespace(
                                    owner_id="123", owner_name="demo"
                                ),
                            )
                        ],
                    ),
                )
            ),
        }
    )

    service = ObsService(make_config(), client_factory=factory)

    result = service.list_objects("demo-bucket", prefix="logs/", max_keys=25)

    assert result["bucket"] == "demo-bucket"
    assert result["region"] == "ap-southeast-1"
    assert result["endpoint"] == regional_server
    assert result["common_prefixes"] == ["logs/"]
    assert result["objects"] == [
        {
            "key": "logs/app.log",
            "size": 42,
            "etag": "etag-1",
            "last_modified": "2026-01-01T00:00:00.000Z",
            "storage_class": "STANDARD",
            "owner_id": "123",
            "owner_name": "demo",
        }
    ]


def test_create_bucket_uses_target_region() -> None:
    regional_server = build_obs_server("ap-southeast-1")
    factory = FakeClientFactory(
        {
            regional_server: SimpleNamespace(
                createBucket=lambda bucketName, **kwargs: make_response(200, None),
            )
        }
    )

    service = ObsService(make_config(), client_factory=factory)

    result = service.create_bucket("demo-bucket", region="ap-southeast-1")

    assert result == {
        "bucket": "demo-bucket",
        "location": "ap-southeast-1",
        "endpoint": regional_server,
        "created": True,
    }


def test_get_object_text_decodes_bytes() -> None:
    regional_server = build_obs_server("ap-southeast-1")
    factory = FakeClientFactory(
        {
            regional_server: SimpleNamespace(
                getObject=lambda bucketName, objectKey, **kwargs: make_response(
                    200,
                    SimpleNamespace(buffer=b"hello world"),
                )
            )
        }
    )

    service = ObsService(make_config(), client_factory=factory)

    result = service.get_object_text(
        "demo-bucket",
        "hello.txt",
        region="ap-southeast-1",
    )

    assert result["region"] == "ap-southeast-1"
    assert result["text"] == "hello world"
    assert result["size_bytes"] == 11


def test_head_object_returns_serializable_metadata() -> None:
    regional_server = build_obs_server("ap-southeast-1")
    factory = FakeClientFactory(
        {
            regional_server: SimpleNamespace(
                headObject=lambda bucketName, objectKey, **kwargs: make_response(
                    200,
                    None,
                    header=SimpleNamespace(
                        etag="etag-1",
                        contentLength=11,
                        contentType="text/plain",
                        lastModified="2026-01-01T00:00:00.000Z",
                        versionId="v1",
                        metadata={"env": "dev"},
                    ),
                )
            )
        }
    )

    service = ObsService(make_config(), client_factory=factory)

    result = service.head_object(
        "demo-bucket",
        "hello.txt",
        region="ap-southeast-1",
    )

    assert result == {
        "bucket": "demo-bucket",
        "key": "hello.txt",
        "region": "ap-southeast-1",
        "endpoint": regional_server,
        "etag": "etag-1",
        "content_length": 11,
        "content_type": "text/plain",
        "last_modified": "2026-01-01T00:00:00.000Z",
        "version_id": "v1",
        "metadata": {"env": "dev"},
    }


def test_put_text_object_returns_sdk_metadata() -> None:
    regional_server = build_obs_server("ap-southeast-1")
    factory = FakeClientFactory(
        {
            regional_server: SimpleNamespace(
                putContent=lambda bucketName, objectKey, content: make_response(
                    200,
                    SimpleNamespace(
                        etag="etag-2",
                        versionId="v1",
                        objectUrl="https://example/object",
                    ),
                )
            )
        }
    )

    service = ObsService(make_config(), client_factory=factory)

    result = service.put_text_object(
        "demo-bucket",
        "notes.txt",
        "payload",
        region="ap-southeast-1",
    )

    assert result == {
        "bucket": "demo-bucket",
        "key": "notes.txt",
        "region": "ap-southeast-1",
        "endpoint": regional_server,
        "etag": "etag-2",
        "version_id": "v1",
        "object_url": "https://example/object",
    }


def test_upload_file_uses_local_path(tmp_path: Path) -> None:
    regional_server = build_obs_server("ap-southeast-1")
    source_file = tmp_path / "payload.bin"
    source_file.write_bytes(b"demo-bytes")
    factory = FakeClientFactory(
        {
            regional_server: SimpleNamespace(
                putFile=lambda bucketName, objectKey, file_path: make_response(
                    200,
                    SimpleNamespace(
                        etag="etag-3",
                        versionId="v2",
                        objectUrl="https://example/uploaded",
                    ),
                )
            )
        }
    )

    service = ObsService(make_config(), client_factory=factory)

    result = service.upload_file(
        "demo-bucket",
        str(source_file),
        object_key="artifacts/payload.bin",
        region="ap-southeast-1",
    )

    assert result == {
        "bucket": "demo-bucket",
        "key": "artifacts/payload.bin",
        "region": "ap-southeast-1",
        "endpoint": regional_server,
        "source_path": str(source_file.resolve()),
        "size_bytes": 10,
        "etag": "etag-3",
        "version_id": "v2",
        "object_url": "https://example/uploaded",
    }


def test_download_object_writes_local_file(tmp_path: Path) -> None:
    regional_server = build_obs_server("ap-southeast-1")

    def fake_get_object(bucketName, objectKey, **kwargs):
        Path(kwargs["downloadPath"]).write_bytes(b"downloaded")
        return make_response(200, SimpleNamespace(url=kwargs["downloadPath"]))

    factory = FakeClientFactory(
        {
            regional_server: SimpleNamespace(
                getObject=fake_get_object,
            )
        }
    )

    service = ObsService(make_config(), client_factory=factory)
    destination = tmp_path / "nested" / "file.bin"

    result = service.download_object(
        "demo-bucket",
        "artifacts/file.bin",
        str(destination),
        region="ap-southeast-1",
    )

    assert destination.read_bytes() == b"downloaded"
    assert result == {
        "bucket": "demo-bucket",
        "key": "artifacts/file.bin",
        "region": "ap-southeast-1",
        "endpoint": regional_server,
        "destination_path": str(destination.resolve()),
        "size_bytes": 10,
        "etag": None,
        "downloaded": True,
    }


def test_delete_object_returns_deleted_shape() -> None:
    regional_server = build_obs_server("ap-southeast-1")
    factory = FakeClientFactory(
        {
            regional_server: SimpleNamespace(
                deleteObject=lambda bucketName, objectKey, **kwargs: make_response(
                    204,
                    None,
                )
            )
        }
    )

    service = ObsService(make_config(), client_factory=factory)

    result = service.delete_object(
        "demo-bucket",
        "notes.txt",
        region="ap-southeast-1",
    )

    assert result == {
        "bucket": "demo-bucket",
        "key": "notes.txt",
        "region": "ap-southeast-1",
        "endpoint": regional_server,
        "version_id": None,
        "deleted": True,
    }


def test_service_raises_with_obs_error_details() -> None:
    factory = FakeClientFactory(
        {
            OBS_GLOBAL_SERVER: SimpleNamespace(
                listBuckets=lambda isQueryLocation=True: make_response(
                    403,
                    None,
                    errorCode="AccessDenied",
                    errorMessage="denied",
                ),
                getBucketLocation=lambda bucketName: make_response(
                    403,
                    None,
                    errorCode="AccessDenied",
                    errorMessage="denied",
                ),
            )
        }
    )

    service = ObsService(make_config(), client_factory=factory)

    with pytest.raises(ObsServiceError, match="AccessDenied"):
        service.get_bucket_location("demo-bucket")
