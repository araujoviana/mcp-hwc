from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


_VALID_PERIOD_TYPES = ("on_demand", "month", "year")
_HOURS_PER_MONTH = 730


@dataclass(frozen=True)
class ResourceDescriptor:
    service: str
    spec: str
    region: str
    period_type: str
    period_num: int = 1
    quantity: int = 1

    def __post_init__(self) -> None:
        if self.period_type not in _VALID_PERIOD_TYPES:
            raise ValueError(
                f"period_type must be one of {_VALID_PERIOD_TYPES}, got '{self.period_type}'"
            )
        if self.period_num < 1:
            raise ValueError("period_num must be >= 1")
        if self.quantity < 1:
            raise ValueError("quantity must be >= 1")


@dataclass(frozen=True)
class QuoteItem:
    service: str
    spec: str
    region: str
    period_type: str
    period_num: int
    quantity: int
    unit_price: float
    currency: str

    @property
    def total_price(self) -> float:
        return self.unit_price * self.quantity

    def to_dict(self) -> dict[str, Any]:
        return {
            "service": self.service,
            "spec": self.spec,
            "region": self.region,
            "period_type": self.period_type,
            "period_num": self.period_num,
            "quantity": self.quantity,
            "unit_price": self.unit_price,
            "total_price": self.total_price,
            "currency": self.currency,
        }


@dataclass(frozen=True)
class QuoteResult:
    quote_id: uuid.UUID
    items: tuple[QuoteItem, ...]
    currency: str
    created_at: datetime

    @property
    def total_monthly(self) -> float:
        total = 0.0
        for item in self.items:
            if item.period_type == "on_demand":
                total += item.unit_price * _HOURS_PER_MONTH * item.quantity
            elif item.period_type == "month":
                total += item.unit_price * item.period_num * item.quantity
            elif item.period_type == "year":
                total += (item.unit_price / 12) * item.period_num * item.quantity
        return total

    @property
    def total_annual(self) -> float:
        return self.total_monthly * 12

    def to_dict(self) -> dict[str, Any]:
        return {
            "quote_id": str(self.quote_id),
            "items": [item.to_dict() for item in self.items],
            "total_monthly": round(self.total_monthly, 2),
            "total_annual": round(self.total_annual, 2),
            "currency": self.currency,
            "created_at": self.created_at.isoformat(),
        }
