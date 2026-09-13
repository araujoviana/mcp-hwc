from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
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
    allow_local_spool: bool = False,
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

    if not bucket_name or obs_service_factory is None:
        if allow_local_spool:
            spool_dir = Path("/tmp/mcp-hwc-spool")
            spool_dir.mkdir(parents=True, exist_ok=True)
            local_path = spool_dir / f"{source}-{uuid.uuid4().hex[:8]}.json"
            local_path.write_text(
                json.dumps(list(rows), ensure_ascii=False, default=str), encoding="utf-8"
            )
            return {
                data_key: None,
                "preview": format_list_as_markdown_table(list(rows[:preview_rows])),
                "total_rows": total,
                "spooled": True,
                "local_file_path": str(local_path),
            }

        # No spool target configured: return the full result as before rather than
        # failing the query, but tell the caller how to opt into offloading.
        return {
            data_key: list(rows),
            "total_rows": total,
            "spooled": False,
            "spool_hint": (
                f"{source} returned {total} rows (> {threshold}). Pass spool_bucket "
                f"(or set MCP_HWC_SPOOL_BUCKET) to offload large results to OBS and "
                f"get a compact preview instead of the full payload."
            ),
        }

    obs = obs_service_factory()
    if auto_create_bucket:
        try:
            obs.head_bucket(bucket_name=bucket_name, region=region)
        except Exception:
            try:
                obs.create_bucket(bucket_name=bucket_name, region=region)
            except Exception:
                # The bucket may already exist (owned elsewhere, or a transient
                # head failure); let the upload below surface the real error.
                pass

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
