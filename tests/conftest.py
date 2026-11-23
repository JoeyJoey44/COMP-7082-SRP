"""Shared fixtures: every test gets a fresh in-memory database."""
import pytest

from cart import ShoppingCart
from checkout import CheckoutService
from payments import FakePaymentGateway
from repository import StoreRepository


@pytest.fixture
def repo():
    repository = StoreRepository(':memory:')
    repository.initialize()  # seeds LAP-01 (999.99 x5), MOU-01 (29.95 x20), USB-01 (9.99 x50)
    return repository


@pytest.fixture
def cart(repo):
    return ShoppingCart('alice', repo)


@pytest.fixture
def gateway():
    return FakePaymentGateway(should_approve=True)


@pytest.fixture
def service(repo, gateway):
    return CheckoutService(repo, gateway)
