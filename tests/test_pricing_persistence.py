from __future__ import annotations

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from mcp_hwc.pricing.models import QuoteItem, QuoteResult
from mcp_hwc.pricing.persistence import QuoteStore


@pytest.fixture
def store(tmp_path: Path) -> QuoteStore:
    return QuoteStore(quotes_dir=tmp_path / "quotes")


def test_save_and_get_quote(store: QuoteStore) -> None:
    quote_id = uuid.uuid4()
    result = QuoteResult(
        quote_id=quote_id,
        items=(
            QuoteItem(
                service="ecs",
                spec="c6.large.2",
                region="sa-brazil-1",
                period_type="month",
                period_num=1,
                quantity=1,
                unit_price=100.0,
                currency="USD",
            ),
        ),
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    store.save(result)
    loaded = store.get(quote_id)
    assert loaded.quote_id == quote_id
    assert len(loaded.items) == 1
    assert loaded.items[0].service == "ecs"


def test_get_nonexistent_quote_raises(store: QuoteStore) -> None:
    with pytest.raises(FileNotFoundError):
        store.get(uuid.uuid4())


def test_list_quotes_empty(store: QuoteStore) -> None:
    assert store.list_quotes() == []


def test_list_quotes_returns_saved(store: QuoteStore) -> None:
    result = QuoteResult(
        quote_id=uuid.uuid4(),
        items=(
            QuoteItem(
                service="rds",
                spec="mysql.ha.xlarge.4",
                region="sa-brazil-1",
                period_type="year",
                period_num=1,
                quantity=1,
                unit_price=5000.0,
                currency="USD",
            ),
        ),
        currency="USD",
        created_at=datetime.now(timezone.utc),
    )
    store.save(result)
    summaries = store.list_quotes()
    assert len(summaries) == 1
    assert summaries[0]["quote_id"] == str(result.quote_id)
    assert summaries[0]["services"] == ["rds"]
