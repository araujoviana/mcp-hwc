from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Sequence

from mcp_hwc.core.sdk_service import format_list_as_markdown_table

DEFAULT_SPOOL_ROW_THRESHOLD = 50
DEFAULT_PREVIEW_ROWS = 10


def spool_rows_if_large(
    rows: Sequence[Any],
    *,
    source: str,
    data_key: str = "rows",
    bucket_name: str | None,
    region: str | None,
    obs_service_factory: Callable[[], Any] | None,
    threshold: int = DEFAULT_SPOOL_ROW_THRESHOLD,
    preview_rows: int = DEFAULT_PREVIEW_ROWS,
    object_key: str | None = None,
    auto_create_bucket: bool = True,
) -> dict[str, object]:
    """Return rows unchanged when small; otherwise upload the full set to OBS
    as JSON and return a compact Markdown preview + OBS location.

    `obs_service_factory` is only invoked when spooling is actually needed (i.e.
    never for the common small-result path), so callers can pass a zero-arg
    getter like `server.get_obs_service` without eagerly constructing an OBS
    client for every call.
    """
    total = len(rows)
    if total <= threshold:
        return {data_key: list(rows), "total_rows": total, "spooled": False}

    if not bucket_name:
        raise ValueError(
            f"{source} returned {total} rows (> {threshold}); pass a spool bucket "
            f"(spool_bucket param, or set MCP_HWC_SPOOL_BUCKET) to store the full "
            f"result in OBS."
        )
    if obs_service_factory is None:
        raise ValueError(f"{source} spooling requires an OBS service factory, none was provided")

    obs = obs_service_factory()
    if auto_create_bucket:
        try:
            obs.head_bucket(bucket_name=bucket_name, region=region)
        except Exception:
            obs.create_bucket(bucket_name=bucket_name, region=region)

    key = object_key or _default_object_key(source)
    body = json.dumps(list(rows), ensure_ascii=False, default=str)
    upload = obs.put_text_object(
        bucket_name=bucket_name, object_key=key, content=body, region=region
    )

    return {
        data_key: None,
        "preview": format_list_as_markdown_table(list(rows[:preview_rows])),
        "total_rows": total,
        "spooled": True,
        "obs_location": f"obs://{bucket_name}/{key}",
        "obs_bucket": bucket_name,
        "obs_region": upload.get("region"),
    }


def _default_object_key(source: str) -> str:
    now = datetime.now(timezone.utc)
    return f"mcp-hwc-spool/{source}/{now:%Y/%m/%d}/{now:%H%M%S}-{uuid.uuid4().hex[:8]}.json"
