"""Checkout coordinator."""
import logging

from models import OrderResult, from_cents
from repository import DuplicateRequestError, OutOfStockError

logger = logging.getLogger(__name__)


class CheckoutService:
    def __init__(self, repository, payment_gateway):
        self.repository = repository
        self.payment_gateway = payment_gateway

    def _existing_result(self, request_id):
        row = self.repository.get_order_by_request_id(request_id)
        order_id, _user, amount_cents, status = row
        return OrderResult(order_id, status, from_cents(amount_cents))

    def checkout(self, cart, payment_token, request_id):
        """Place an order for ``cart``.

        Flow: (1) validate, (2) idempotency check on request_id, (3) atomically record a
        pending order and reserve stock, (4) charge the gateway, (5) mark the order paid,
        or release the stock and mark it declined / payment_error.
        """
        if not request_id:
            raise ValueError('request_id is required to prevent duplicate charges')

        # Repeated request (e.g. double-click or client retry): return the original
        # outcome and never charge twice. Checked first because a paid cart is now empty.
        if self.repository.get_order_by_request_id(request_id):
            return self._existing_result(request_id)

        if not cart.lines:
            return OrderResult(None, 'empty', from_cents(0))
        if not payment_token:
            raise ValueError('payment_token is required')

        amount = cart.total()
        lines = list(cart.lines)
        try:
            order_id = self.repository.create_pending_order(cart.user_id, amount, request_id, lines)
        except DuplicateRequestError:  # lost a race with a concurrent identical request
            return self._existing_result(request_id)
        except OutOfStockError as exc:
            logger.info('Checkout rejected, out of stock: %s', exc.sku)
            return OrderResult(None, 'out_of_stock', amount)

        try:
            response = self.payment_gateway.charge(amount, payment_token)
            status = 'paid' if response.get('approved') is True else 'declined'
        except Exception:
            logger.exception('Unexpected payment gateway error for order %s', order_id)
            status = 'payment_error'

        self.repository.complete_order(order_id, status, lines, release_stock=(status != 'paid'))

        if status == 'paid':
            cart.clear()
            cart.save()
        return OrderResult(order_id, status, amount)
