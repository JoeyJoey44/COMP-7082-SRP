# Defect Report

This lists the defects found in the starter order-processing app, what could go wrong, and how each was fixed. The test that shows each fix is listed beside it (`tests/test_cart.py`, `tests/test_checkout.py`).

| # | Where | What goes wrong | Fix | Test(s) |
|---|-------|-----------------|-----|---------|
| 1 | `cart.py` `add_item` / `remove_item` | No quantity validation. `add_item('X', 0)`, `-5`, `1.5` or `'2'` are accepted, so carts can hold zero, negative or fractional quantities. `remove_item(sku, -3)` *increases* the quantity. | `_validate_quantity` requires a positive `int` (and rejects `bool`). Invalid input raises `ValueError`. | `test_add_item_rejects_invalid_quantities`, `test_remove_item_rejects_negative_quantity` |
| 2 | `cart.py` `add_item` | The stock check compares only the *new* quantity with stock and ignores what is already in the cart. Adding 3 laptops twice (stock 5) gives 6. | The check now uses `existing quantity + new quantity`. | `test_duplicate_add_cannot_exceed_stock` |
| 3 | `models.py`, `cart.py`, `repository.py` | Money is stored as `float`. `3 × 9.99 = 29.970000000000002`, and discounted totals such as `59.9 × 0.9` are never rounded to cents. This causes wrong charges and failed equality checks. | Every amount is a `Decimal` rounded to cents with ROUND_HALF_UP (`to_money`). Orders store `amount_cents INTEGER`. | `test_subtotal_uses_exact_decimal_cents`, `test_percentage_discount_rounds_half_up_to_cents` |
| 4 | `cart.py` `apply_discount` / `total` | The discounted total is cached as a number when the coupon is applied. Editing the cart afterwards does not change it, so removing every item still charges the old total and adding items charges too little. | Only the coupon *code* is stored. `discount_amount()` and `total()` are recalculated from the current subtotal every time. | `test_total_updates_when_cart_edited_after_discount` |
| 5 | `cart.py` `apply_discount` | Coupons stack. The discount is taken from `self.total()`, which already includes the earlier discount, so applying `WELCOME10` twice gives 19% off. | Discounts are always calculated from the subtotal. A new valid code replaces the old one. | `test_discounts_do_not_stack` |
| 6 | `cart.py` `apply_discount` (`SAVE15`) | A fixed $15 discount on a cart under $15 gives a **negative total**. | The discount is capped at the subtotal, so the total is never below $0.00. | `test_fixed_discount_boundaries_never_negative` (9.99 / 15.00 / 15.01) |
| 7 | `cart.py` `load` | `load()` adds the saved items to the lines already in memory, so each repeated load doubles the cart. | `load()` clears the in-memory lines first. It also uses current product data and caps quantities to the stock now available. | `test_saved_cart_repeated_load_does_not_duplicate`, `test_load_caps_quantity_when_stock_dropped` |
| 8 | `repository.py` `get_product`, `get_saved_cart` | The SQL is built with f-strings (**SQL injection**). The user id `x' OR '1'='1` loads every user's saved cart, and any `'` in input breaks the query. | All queries use `?` parameters. | `test_saved_carts_are_isolated_per_user_including_quote_characters` |
| 9 | `checkout.py` | **Stock is taken before payment and never given back.** A declined payment or a gateway error permanently loses inventory. The cart is also cleared after a failed payment. | Stock is reserved together with a `pending` order. If the payment is not approved, the stock is released and the order is marked `declined`/`payment_error` in one transaction. The cart is cleared only when the order is `paid`. | `test_declined_payment_restores_stock_and_keeps_cart`, `test_unexpected_gateway_exception_is_handled` |
| 10 | `checkout.py`, `repository.update_stock` | Stock is not checked again at checkout. Stock can change after an item is added to the cart, and `stock = stock - ?` can go **negative** (overselling). Updates run line by line, so a failure partway leaves some lines deducted. | The conditional `UPDATE … WHERE stock >= ?` runs for every line inside one `BEGIN IMMEDIATE` transaction. Any shortfall rolls back everything and returns `out_of_stock` before the customer is charged. | `test_stock_changed_after_adding_to_cart_blocks_checkout`, `test_out_of_stock_on_one_line_reserves_nothing`, `test_update_stock_never_goes_negative` |
| 11 | `checkout.py`, `orders` table | **Duplicate transactions.** `request_id` is stored but never enforced, so a double-click or retry charges the customer twice and creates two orders. A missing `request_id` only prints a message. | `request_id` is required and is `UNIQUE` in the schema. A repeated request returns the original `OrderResult` without charging again. A concurrent duplicate is caught by the unique constraint (`DuplicateRequestError`). | `test_repeated_checkout_with_same_request_id_charges_once`, `test_checkout_requires_request_id` |
| 12 | `checkout.py` | A payment response with no `approved` key raised `KeyError` and was reported as a vague error. Any truthy value counted as approved. | `response.get('approved') is True` is required for `paid`. Unexpected exceptions are logged (`logger.exception`) and become `payment_error`, with stock released. | `test_malformed_gateway_response_is_not_treated_as_paid` |
| 13 | `repository.py` `list_orders` | The `user_id` parameter is ignored, so every customer's orders are returned to any user. | Results are filtered with `WHERE user_id = ?`. | `test_list_orders_only_returns_that_users_orders` |
| 14 | `checkout.py` | The payment token is `print`ed to stdout (leaks sensitive data into logs). The `amount > 1000` block did nothing useful. | Both were removed. Only non-sensitive events are logged with `logging`. | `test_payment_token_is_not_printed` |
| 15 | `repository.py` (all methods) | Connections leak if a query raises, because `close()` is skipped. Writes that should go together (such as delete and re-insert of the saved cart) are not atomic. | The `_connection()` and `_transaction()` context managers always close the connection and roll back on error. `save_cart` runs in one transaction. | covered by the saved-cart tests |
| 16 | `setup_db.py` schema | There are no constraints: `saved_cart` can hold duplicate `(user_id, sku)` rows, and stock, price and quantity can be negative. | Added `PRIMARY KEY(user_id, sku)`, `CHECK` constraints, `NOT NULL` and `UNIQUE(request_id)`. | — |
| 17 | `models.py` | `int \| None` fails with a `TypeError` on Python < 3.10 when the module is imported. | `Optional[int]` plus `from __future__ import annotations`. | all tests import it |

## Assumptions

- **One coupon per cart.** Applying a new valid code replaces the previous one. Codes are case-insensitive and surrounding whitespace is ignored.
- **FREESHIP** is accepted but does not change the total, because the app has no shipping charge.
- **SAVE15** is capped so the total is never below $0.00. It has no minimum order value because none was specified.
- **Discounts are not rounded in the customer's favour.** Percentage discounts are rounded half-up to the cent (`0.045 → 0.05`).
- **Invalid quantities raise `ValueError`.** This is a programming or input error. Business failures (unknown SKU, not enough stock) still return `False`, as the original API did.
- **A `request_id` identifies one checkout attempt.** Repeating it returns the original result, including a declined one. To retry after a decline, the client sends a new `request_id`. The cart is kept after a decline so the customer can do this.
- **Unknown gateway outcomes are not charged.** On an unexpected gateway exception the order is marked `payment_error` and stock is released. In production this status would be checked against the payment provider.
- **Saved carts follow current stock.** When a saved cart is loaded, quantities are capped to current stock and unavailable items are skipped. Prices come from the current product table.
- **Prices at checkout.** The price captured when an item is added to the cart is the price charged at checkout.
- **The payment gateway is unchanged.** The supplied `FakePaymentGateway` is still used. Tests use it, or a `Mock`, to simulate declines and exceptions.

## Test results

Run `python -m pytest -q`:

```
..........................................                               [100%]
42 passed in 0.06s
```

The suite has 42 test cases: 31 test functions, some of them parametrized. Every test uses a fresh in-memory SQLite database (`tests/conftest.py`).

## CI

The workflow is `.github/workflows/tests.yml`. It runs on every push and pull request with Python 3.10 and 3.12, installs `requirements.txt`, and runs `python -m pytest -q`.

Successful run: https://github.com/JoeyJoey44/COMP-7082-SRP/actions/runs/45102873078 (Python 3.10 and 3.12, all tests passing)
