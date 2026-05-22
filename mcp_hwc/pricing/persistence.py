from __future__ import annotations

import json
import uuid
from pathlib import Path
from typing import Any

from .models import QuoteItem, QuoteResult


class QuoteStore:
    def __init__(self, quotes_dir: Path | None = None) -> None:
        if quotes_dir is None:
            quotes_dir = Path.home() / ".config" / "mcp-hwc" / "quotes"
        self._dir = quotes_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def save(self, result: QuoteResult) -> Path:
        path = self._dir / f"{result.quote_id}.json"
        path.write_text(json.dumps(result.to_dict(), indent=2), encoding="utf-8")
        return path

    def get(self, quote_id: uuid.UUID) -> QuoteResult:
        path = self._dir / f"{quote_id}.json"
        if not path.exists():
            raise FileNotFoundError(f"Quote {quote_id} not found")
        data = json.loads(path.read_text(encoding="utf-8"))
        return self._from_dict(data)

    def list_quotes(self, limit: int = 20, service: str | None = None) -> list[dict[str, Any]]:
        files = sorted(self._dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
        summaries: list[dict[str, Any]] = []
        for f in files:
            data = json.loads(f.read_text(encoding="utf-8"))
            services = list({item["service"] for item in data.get("items", [])})
            if service and service.lower() not in [s.lower() for s in services]:
                continue
            summaries.append({
                "quote_id": data["quote_id"],
                "services": services,
                "total_monthly": data.get("total_monthly"),
                "total_annual": data.get("total_annual"),
                "currency": data.get("currency", "USD"),
                "created_at": data.get("created_at"),
            })
            if len(summaries) >= limit:
                break
        return summaries

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> QuoteResult:
        from datetime import datetime

        items = []
        for item_data in data.get("items", []):
            items.append(QuoteItem(
                service=item_data["service"],
                spec=item_data["spec"],
                region=item_data["region"],
                period_type=item_data["period_type"],
                period_num=item_data["period_num"],
                quantity=item_data["quantity"],
                unit_price=item_data["unit_price"],
                currency=item_data["currency"],
            ))
        return QuoteResult(
            quote_id=uuid.UUID(data["quote_id"]),
            items=tuple(items),
            currency=data.get("currency", "USD"),
            created_at=datetime.fromisoformat(data["created_at"]),
        )
