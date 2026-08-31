from __future__ import annotations

import json

import pytest

from mcp_hwc.core.result_spooling import spool_rows_if_large


def test_small_result_returned_unchanged() -> None:
    rows = [{"id": i} for i in range(10)]
    calls: list[str] = []

    def factory():
        calls.append("called")
        raise AssertionError("obs_service_factory should not be invoked for small results")

    result = spool_rows_if_large(
        rows,
        source="test",
        bucket_name=None,
        region=None,
        obs_service_factory=factory,
        threshold=50,
    )

    assert result == {"rows": rows, "total_rows": 10, "spooled": False}
    assert calls == []


def test_large_result_without_bucket_returns_full_result_with_hint() -> None:
    rows = [{"id": i} for i in range(60)]

    result = spool_rows_if_large(
        rows,
        source="test",
        bucket_name=None,
        region=None,
        obs_service_factory=lambda: None,
        threshold=50,
    )

    assert result["rows"] == rows
    assert result["spooled"] is False
    assert result["total_rows"] == 60
    assert "spool_bucket" in result["spool_hint"]


def test_large_result_without_factory_returns_full_result_with_hint() -> None:
    rows = [{"id": i} for i in range(60)]

    result = spool_rows_if_large(
        rows,
        source="test",
        bucket_name="my-bucket",
        region=None,
        obs_service_factory=None,
        threshold=50,
    )

    assert result["rows"] == rows
    assert result["spooled"] is False
    assert "spool_hint" in result


def test_large_result_spools_to_obs_and_returns_preview() -> None:
    rows = [{"id": i, "name": f"row-{i}"} for i in range(60)]
    put_calls: list[dict[str, object]] = []

    class FakeObsService:
        def head_bucket(self, bucket_name, region=None):
            raise RuntimeError("bucket does not exist yet")

        def create_bucket(self, bucket_name, region=None):
            return {"bucket": bucket_name, "created": True}

        def put_text_object(self, bucket_name, object_key, content, region=None):
            put_calls.append(
                {"bucket_name": bucket_name, "object_key": object_key, "content": content}
            )
            return {"bucket": bucket_name, "key": object_key, "region": region or "sa-brazil-1"}

    result = spool_rows_if_large(
        rows,
        source="test",
        bucket_name="spool-bucket",
        region="sa-brazil-1",
        obs_service_factory=lambda: FakeObsService(),
        threshold=50,
    )

    assert result["rows"] is None
    assert result["spooled"] is True
    assert result["total_rows"] == 60
    assert result["obs_bucket"] == "spool-bucket"
    assert result["obs_location"].startswith("obs://spool-bucket/")
    assert "row-0" in result["preview"]
    assert "row-9" in result["preview"]
    assert "row-10" not in result["preview"]

    assert len(put_calls) == 1
    uploaded_rows = json.loads(put_calls[0]["content"])
    assert len(uploaded_rows) == 60


def test_large_result_reuses_existing_bucket() -> None:
    rows = [{"id": i} for i in range(51)]
    create_calls: list[str] = []

    class FakeObsService:
        def head_bucket(self, bucket_name, region=None):
            return {"bucket": bucket_name}

        def create_bucket(self, bucket_name, region=None):
            create_calls.append(bucket_name)
            return {"bucket": bucket_name}

        def put_text_object(self, bucket_name, object_key, content, region=None):
            return {"bucket": bucket_name, "key": object_key, "region": region}

    spool_rows_if_large(
        rows,
        source="test",
        bucket_name="existing-bucket",
        region=None,
        obs_service_factory=lambda: FakeObsService(),
        threshold=50,
    )

    assert create_calls == []


def test_create_bucket_failure_does_not_mask_upload() -> None:
    rows = [{"id": i} for i in range(60)]

    class FakeObsService:
        def head_bucket(self, bucket_name, region=None):
            raise RuntimeError("head failed (transient)")

        def create_bucket(self, bucket_name, region=None):
            raise RuntimeError("bucket already exists and is owned by another account")

        def put_text_object(self, bucket_name, object_key, content, region=None):
            return {"bucket": bucket_name, "key": object_key, "region": "sa-brazil-1"}

    result = spool_rows_if_large(
        rows,
        source="test",
        bucket_name="shared-bucket",
        region=None,
        obs_service_factory=lambda: FakeObsService(),
        threshold=50,
    )

    assert result["spooled"] is True
    assert result["obs_bucket"] == "shared-bucket"
