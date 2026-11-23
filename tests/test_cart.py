"""Unit tests for ShoppingCart: quantities, duplicates, removal, money, discounts, saved carts."""
from decimal import Decimal

import pytest

from cart import ShoppingCart


def add_product(repo, sku, price, stock):
    with repo._connection() as conn:
        conn.execute('INSERT INTO products VALUES (?, ?, ?, ?)', (sku, sku, price, stock))


# --- quantities and cart lines ------------------------------------------------------

@pytest.mark.parametrize('bad_qty', [0, -1, 1.5, '2', None, True])
def test_add_item_rejects_invalid_quantities(cart, bad_qty):
    with pytest.raises(ValueError):
        cart.add_item('USB-01', bad_qty)
    assert cart.lines == []


def test_add_unknown_product_returns_false(cart):
    assert cart.add_item('NOPE-99', 1) is False
    assert cart.lines == []


def test_adding_duplicate_product_merges_into_one_line(cart):
    assert cart.add_item('USB-01', 2)
    assert cart.add_item('USB-01', 3)
    assert len(cart.lines) == 1
    assert cart.lines[0].quantity == 5


def test_duplicate_add_cannot_exceed_stock(cart):
    # LAP-01 has 5 in stock: 3 + 3 must be refused even though each call is <= 5.
    assert cart.add_item('LAP-01', 3)
    assert cart.add_item('LAP-01', 3) is False
    assert cart.lines[0].quantity == 3
    assert cart.add_item('LAP-01', 2)  # exactly reaching stock is allowed
    assert cart.lines[0].quantity == 5


def test_remove_item_partial_full_and_missing(cart):
    cart.add_item('USB-01', 5)
    assert cart.remove_item('USB-01', 2)
    assert cart.lines[0].quantity == 3
    assert cart.remove_item('USB-01')
    assert cart.lines == []
    assert cart.remove_item('USB-01') is False


def test_remove_item_rejects_negative_quantity(cart):
    cart.add_item('USB-01', 2)
    with pytest.raises(ValueError):
        cart.remove_item('USB-01', -3)  # previously this *increased* the quantity to 5
    assert cart.lines[0].quantity == 2


# --- money ---------------------------------------------------------------------------

def test_subtotal_uses_exact_decimal_cents(cart):
    cart.add_item('USB-01', 3)  # 3 x 9.99 = 29.97 (float arithmetic gives 29.970000000000002)
    cart.add_item('MOU-01', 1)  # + 29.95
    assert cart.subtotal() == Decimal('59.92')
    assert isinstance(cart.total(), Decimal)


def test_empty_cart_totals_are_zero(cart):
    assert cart.subtotal() == Decimal('0.00')
    assert cart.total() == Decimal('0.00')


# --- discounts -----------------------------------------------------------------------

@pytest.mark.parametrize('code, expected', [
    ('WELCOME10', Decimal('53.91')),    # 59.90 * 0.9
    ('STUDENT20', Decimal('47.92')),    # 59.90 * 0.8
    ('SAVE15', Decimal('44.90')),       # 59.90 - 15
    ('FREESHIP', Decimal('59.90')),     # no shipping in this app, amount unchanged
    (' welcome10 ', Decimal('53.91')),  # codes are trimmed and case-insensitive
])
def test_discount_codes(cart, code, expected):
    cart.add_item('MOU-01', 2)
    assert cart.apply_discount(code)
    assert cart.total() == expected


def test_invalid_coupon_is_rejected_and_does_not_change_total(cart):
    cart.add_item('MOU-01', 2)
    assert cart.apply_discount('BOGUS') is False
    assert cart.discount_code is None
    assert cart.total() == Decimal('59.90')


@pytest.mark.parametrize('price, expected', [
    ('9.99', Decimal('0.00')),    # below 15: clamps to zero instead of -5.01
    ('15.00', Decimal('0.00')),   # exactly 15: boundary
    ('15.01', Decimal('0.01')),   # just above
])
def test_fixed_discount_boundaries_never_negative(repo, price, expected):
    add_product(repo, 'TEST-01', price, 10)
    c = ShoppingCart('bob', repo)
    c.add_item('TEST-01', 1)
    c.apply_discount('SAVE15')
    assert c.total() == expected


def test_percentage_discount_rounds_half_up_to_cents(repo):
    add_product(repo, 'TEST-02', '0.05', 10)
    c = ShoppingCart('bob', repo)
    c.add_item('TEST-02', 1)
    c.apply_discount('WELCOME10')       # 0.05 * 0.9 = 0.045 -> 0.05
    assert c.total() == Decimal('0.05')


def test_discounts_do_not_stack(cart):
    cart.add_item('MOU-01', 2)
    cart.apply_discount('WELCOME10')
    cart.apply_discount('WELCOME10')
    assert cart.total() == Decimal('53.91')  # not 59.90 * 0.9 * 0.9 = 48.52
    cart.apply_discount('STUDENT20')         # replaces, does not compound
    assert cart.total() == Decimal('47.92')


def test_total_updates_when_cart_edited_after_discount(cart):
    cart.add_item('MOU-01', 2)
    cart.apply_discount('WELCOME10')
    assert cart.total() == Decimal('53.91')
    cart.add_item('MOU-01', 2)              # 4 x 29.95 = 119.80
    assert cart.total() == Decimal('107.82')
    cart.remove_item('MOU-01')
    assert cart.total() == Decimal('0.00')  # the old cached total would still be 53.91


# --- saved carts ---------------------------------------------------------------------

def test_saved_cart_repeated_load_does_not_duplicate(repo, cart):
    cart.add_item('USB-01', 2)
    cart.add_item('MOU-01', 1)
    cart.save()

    restored = ShoppingCart('alice', repo)
    restored.load()
    restored.load()
    assert {(l.sku, l.quantity) for l in restored.lines} == {('USB-01', 2), ('MOU-01', 1)}


def test_saved_carts_are_isolated_per_user_including_quote_characters(repo, cart):
    cart.add_item('USB-01', 2)
    cart.save()
    # This user id used to break out of the string-built SQL and load every user's cart.
    other = ShoppingCart("x' OR '1'='1", repo)
    other.load()
    assert other.lines == []


def test_load_caps_quantity_when_stock_dropped(repo, cart):
    cart.add_item('LAP-01', 4)
    cart.save()
    repo.update_stock('LAP-01', 3)  # only 2 left now
    restored = ShoppingCart('alice', repo)
    restored.load()
    assert restored.lines[0].quantity == 2
