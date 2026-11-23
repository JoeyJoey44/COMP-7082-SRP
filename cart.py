"""Shopping cart and discount logic."""
from decimal import Decimal

from models import CartLine, to_money

# Percentage discounts are multipliers; fixed discounts are amounts off.
PERCENT_DISCOUNTS = {'WELCOME10': Decimal('0.90'), 'STUDENT20': Decimal('0.80')}
FIXED_DISCOUNTS = {'SAVE15': Decimal('15.00')}
NO_AMOUNT_CODES = {'FREESHIP'}  # accepted, but this app has no shipping charge to remove


def _validate_quantity(quantity):
    # bool is a subclass of int, so reject it explicitly.
    if isinstance(quantity, bool) or not isinstance(quantity, int) or quantity <= 0:
        raise ValueError(f'Quantity must be a positive whole number, got {quantity!r}')


class ShoppingCart:
    def __init__(self, user_id, repository):
        if not user_id:
            raise ValueError('user_id is required')
        self.user_id = user_id
        self.repository = repository
        self.lines = []
        self.discount_code = None

    def _find(self, sku):
        return next((line for line in self.lines if line.sku == sku), None)

    def add_item(self, sku, quantity):
        """Add ``quantity`` units of ``sku``. Returns False if unknown or not enough stock."""
        _validate_quantity(quantity)
        product = self.repository.get_product(sku)
        if not product:
            return False
        existing = self._find(sku)
        already_in_cart = existing.quantity if existing else 0
        if product.stock < already_in_cart + quantity:
            return False
        if existing:
            existing.quantity += quantity
        else:
            self.lines.append(CartLine(sku, product.name, product.price, quantity))
        return True

    def remove_item(self, sku, quantity=None):
        """Remove a line entirely (quantity=None) or reduce it by ``quantity``."""
        if quantity is not None:
            _validate_quantity(quantity)
        line = self._find(sku)
        if line is None:
            return False
        if quantity is None or quantity >= line.quantity:
            self.lines.remove(line)
        else:
            line.quantity -= quantity
        return True

    def subtotal(self):
        return to_money(sum((line.line_total for line in self.lines), Decimal('0')))

    def discount_amount(self):
        """Discount is recomputed from the current subtotal so cart edits are reflected."""
        subtotal = self.subtotal()
        code = self.discount_code
        if code in PERCENT_DISCOUNTS:
            discount = subtotal - to_money(subtotal * PERCENT_DISCOUNTS[code])
        elif code in FIXED_DISCOUNTS:
            discount = FIXED_DISCOUNTS[code]
        else:
            discount = Decimal('0')
        return to_money(min(discount, subtotal))  # never discount below zero

    def total(self):
        return to_money(self.subtotal() - self.discount_amount())

    def apply_discount(self, code):
        """Apply one coupon. A new valid code replaces the previous one (no stacking)."""
        if not isinstance(code, str):
            return False
        code = code.strip().upper()
        if code not in PERCENT_DISCOUNTS and code not in FIXED_DISCOUNTS and code not in NO_AMOUNT_CODES:
            return False
        self.discount_code = code
        return True

    def remove_discount(self):
        self.discount_code = None

    def clear(self):
        self.lines.clear()
        self.discount_code = None

    def load(self):
        """Replace the in-memory cart with the saved cart (safe to call repeatedly).

        Prices and names come from the current product table. If stock has dropped,
        the quantity is capped to what is available; unavailable items are skipped.
        """
        self.lines = []
        for sku, quantity in self.repository.get_saved_cart(self.user_id):
            product = self.repository.get_product(sku)
            if not product or product.stock <= 0:
                continue
            self.add_item(sku, min(quantity, product.stock))

    def save(self):
        self.repository.save_cart(self.user_id, self.lines)
