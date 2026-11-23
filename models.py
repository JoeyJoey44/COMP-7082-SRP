"""Domain models for the order-management application."""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

CENT = Decimal('0.01')


def to_money(value) -> Decimal:
    """Convert a number to a Decimal rounded to whole cents.

    Floats are converted through ``str`` so 29.95 becomes Decimal('29.95')
    rather than Decimal('29.949999999999999289457264239899814128875732421875').
    """
    if isinstance(value, float):
        value = str(value)
    return Decimal(value).quantize(CENT, rounding=ROUND_HALF_UP)


def to_cents(amount: Decimal) -> int:
    return int((to_money(amount) * 100).to_integral_value())


def from_cents(cents: int) -> Decimal:
    return to_money(Decimal(cents) / 100)


@dataclass
class Product:
    sku: str
    name: str
    price: Decimal
    stock: int

    def __post_init__(self):
        self.price = to_money(self.price)


@dataclass
class CartLine:
    sku: str
    name: str
    unit_price: Decimal
    quantity: int

    @property
    def line_total(self) -> Decimal:
        return to_money(self.unit_price * self.quantity)


@dataclass
class OrderResult:
    order_id: Optional[int]
    status: str
    total: Decimal
