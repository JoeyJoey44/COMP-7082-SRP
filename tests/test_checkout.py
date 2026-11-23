"""Unit tests for CheckoutService and the repository functions it relies on."""
from decimal import Decimal
from unittest.mock import Mock

import pytest

from cart import ShoppingCart
from checkout import CheckoutService
from payments import FakePaymentGateway
from repository import OutOfStockError


def stock(repo, sku):
    return repo.get_product(sku).stock


def test_empty_cart_checkout_does_not_charge(service, cart, gateway):
    result = service.checkout(cart, 'TEST_TOKEN', 'req-empty')
    assert result.status == 'empty'
    assert result.order_id is None
    assert gateway.calls == []


def test_successful_checkout_charges_discounted_total_and_reduces_stock(repo, cart, service, gateway):
    cart.add_item('MOU-01', 2)
    cart.apply_discount('WELCOME10')
    result = service.checkout(cart, 'TEST_TOKEN', 'req-1')

    assert result.status == 'paid'
    assert result.total == Decimal('53.91')
    assert gateway.calls == [(Decimal('53.91'), 'TEST_TOKEN')]
    assert stock(repo, 'MOU-01') == 18
    assert cart.lines == [] and cart.discount_code is None
    assert repo.list_orders('alice')[0][2:] == (5391, 'paid')


def test_declined_payment_restores_stock_and_keeps_cart(repo, cart):
    service = CheckoutService(repo, FakePaymentGateway(should_approve=False))
    cart.add_item('LAP-01', 2)
    result = service.checkout(cart, 'TEST_TOKEN', 'req-declined')

    assert result.status == 'declined'
    assert stock(repo, 'LAP-01') == 5          # previously 2 units were lost
    assert len(cart.lines) == 1                 # user can retry with another card
    assert repo.list_orders('alice')[0][3] == 'declined'


def test_unexpected_gateway_exception_is_handled(repo, cart):
    gateway = Mock()
    gateway.charge.side_effect = TimeoutError('gateway unreachable')
    service = CheckoutService(repo, gateway)
    cart.add_item('USB-01', 3)

    result = service.checkout(cart, 'TEST_TOKEN', 'req-error')

    assert result.status == 'payment_error'
    assert stock(repo, 'USB-01') == 50
    assert len(cart.lines) == 1


def test_malformed_gateway_response_is_not_treated_as_paid(repo, cart):
    gateway = Mock()
    gateway.charge.return_value = {'transaction_id': None}  # no 'approved' key
    cart.add_item('USB-01', 1)
    result = CheckoutService(repo, gateway).checkout(cart, 'TEST_TOKEN', 'req-bad')
    assert result.status == 'declined'
    assert stock(repo, 'USB-01') == 50


def test_repeated_checkout_with_same_request_id_charges_once(repo, cart, service, gateway):
    cart.add_item('MOU-01', 1)
    first = service.checkout(cart, 'TEST_TOKEN', 'req-dup')
    # Simulate a double-click / client retry sending the same request again.
    cart.add_item('MOU-01', 1)
    second = service.checkout(cart, 'TEST_TOKEN', 'req-dup')

    assert second == first
    assert len(gateway.calls) == 1
    assert stock(repo, 'MOU-01') == 19
    assert len(repo.list_orders('alice')) == 1


def test_checkout_requires_request_id(service, cart, gateway):
    cart.add_item('USB-01', 1)
    with pytest.raises(ValueError):
        service.checkout(cart, 'TEST_TOKEN', None)
    assert gateway.calls == []


def test_stock_changed_after_adding_to_cart_blocks_checkout(repo, service, gateway):
    alice = ShoppingCart('alice', repo)
    bob = ShoppingCart('bob', repo)
    assert alice.add_item('LAP-01', 4)
    assert bob.add_item('LAP-01', 4)          # both fit when added (stock is 5)

    assert service.checkout(alice, 'TEST_TOKEN', 'req-a').status == 'paid'
    result = service.checkout(bob, 'TEST_TOKEN', 'req-b')

    assert result.status == 'out_of_stock'
    assert len(gateway.calls) == 1             # bob was never charged
    assert stock(repo, 'LAP-01') == 1          # previously went to -3


def test_out_of_stock_on_one_line_reserves_nothing(repo, service, cart):
    cart.add_item('USB-01', 2)
    cart.add_item('LAP-01', 3)
    repo.update_stock('LAP-01', 4)             # only 1 laptop left
    result = service.checkout(cart, 'TEST_TOKEN', 'req-partial')
    assert result.status == 'out_of_stock'
    assert stock(repo, 'USB-01') == 50         # all-or-nothing reservation


def test_update_stock_never_goes_negative(repo):
    with pytest.raises(OutOfStockError):
        repo.update_stock('LAP-01', 6)
    assert stock(repo, 'LAP-01') == 5


def test_list_orders_only_returns_that_users_orders(repo, service):
    for user, req in [('alice', 'r1'), ('bob', 'r2')]:
        c = ShoppingCart(user, repo)
        c.add_item('USB-01', 1)
        service.checkout(c, 'TEST_TOKEN', req)
    orders = repo.list_orders('alice')
    assert len(orders) == 1 and orders[0][1] == 'alice'


def test_payment_token_is_not_printed(cart, service, capsys):
    cart.add_item('USB-01', 1)
    service.checkout(cart, 'SECRET_TOKEN_123', 'req-log')
    assert 'SECRET_TOKEN_123' not in capsys.readouterr().out
