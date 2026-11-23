"""SQLite persistence for products, saved carts, inventory and orders."""
import sqlite3
from contextlib import contextmanager

from models import Product, to_cents
from setup_db import initialize_connection


class OutOfStockError(Exception):
    """Raised when stock cannot be reserved for one or more cart lines."""

    def __init__(self, sku):
        super().__init__(f'Insufficient stock for {sku}')
        self.sku = sku


class DuplicateRequestError(Exception):
    """Raised when an order with the same request_id already exists."""


class StoreRepository:
    def __init__(self, db_path='shop.db'):
        self.db_path = db_path
        # An in-memory database only lives as long as its connection, so keep one open.
        self._shared_conn = sqlite3.connect(db_path, isolation_level=None) if db_path == ':memory:' else None

    def initialize(self, seed=True):
        with self._connection() as conn:
            initialize_connection(conn, seed)

    @contextmanager
    def _connection(self):
        """Yield a connection; always closed afterwards (unless shared in-memory)."""
        conn = self._shared_conn or sqlite3.connect(self.db_path, timeout=2, isolation_level=None)
        try:
            yield conn
        finally:
            if conn is not self._shared_conn:
                conn.close()

    @contextmanager
    def _transaction(self):
        """Run statements atomically: commit on success, roll back on any error."""
        with self._connection() as conn:
            conn.execute('BEGIN IMMEDIATE')
            try:
                yield conn
            except BaseException:
                conn.rollback()
                raise
            conn.commit()

    # --- products -----------------------------------------------------------------

    def get_product(self, sku):
        with self._connection() as conn:
            row = conn.execute('SELECT sku, name, price, stock FROM products WHERE sku = ?',
                               (sku,)).fetchone()
        return Product(*row) if row else None

    # --- saved carts --------------------------------------------------------------

    def get_saved_cart(self, user_id):
        with self._connection() as conn:
            return conn.execute('SELECT sku, quantity FROM saved_cart WHERE user_id = ? ORDER BY rowid',
                                (user_id,)).fetchall()

    def save_cart(self, user_id, lines):
        with self._transaction() as conn:
            conn.execute('DELETE FROM saved_cart WHERE user_id = ?', (user_id,))
            conn.executemany('INSERT INTO saved_cart (user_id, sku, quantity) VALUES (?, ?, ?)',
                             [(user_id, line.sku, line.quantity) for line in lines])

    # --- inventory ----------------------------------------------------------------

    @staticmethod
    def _reserve(conn, lines):
        for line in lines:
            cur = conn.execute('UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?',
                               (line.quantity, line.sku, line.quantity))
            if cur.rowcount != 1:
                raise OutOfStockError(line.sku)

    @staticmethod
    def _release(conn, lines):
        for line in lines:
            conn.execute('UPDATE products SET stock = stock + ? WHERE sku = ?', (line.quantity, line.sku))

    def update_stock(self, sku, quantity):
        """Decrease stock for one SKU; refuses to go below zero."""
        if quantity <= 0:
            raise ValueError('quantity must be positive')
        with self._transaction() as conn:
            cur = conn.execute('UPDATE products SET stock = stock - ? WHERE sku = ? AND stock >= ?',
                               (quantity, sku, quantity))
            if cur.rowcount != 1:
                raise OutOfStockError(sku)

    # --- orders -------------------------------------------------------------------

    def create_pending_order(self, user_id, amount, request_id, lines):
        """Atomically record a pending order and reserve stock for all lines.

        Either everything succeeds or nothing is changed.
        """
        with self._transaction() as conn:
            try:
                cur = conn.execute(
                    'INSERT INTO orders (user_id, amount_cents, status, request_id) VALUES (?, ?, ?, ?)',
                    (user_id, to_cents(amount), 'pending', request_id))
            except sqlite3.IntegrityError as exc:
                raise DuplicateRequestError(request_id) from exc
            self._reserve(conn, lines)
            return cur.lastrowid

    def complete_order(self, order_id, status, lines=(), release_stock=False):
        """Set the final order status, returning reserved stock if the sale failed."""
        with self._transaction() as conn:
            if release_stock:
                self._release(conn, lines)
            conn.execute('UPDATE orders SET status = ? WHERE id = ?', (status, order_id))

    def get_order_by_request_id(self, request_id):
        with self._connection() as conn:
            return conn.execute('SELECT id, user_id, amount_cents, status FROM orders WHERE request_id = ?',
                                (request_id,)).fetchone()

    def list_orders(self, user_id):
        with self._connection() as conn:
            return conn.execute('SELECT id, user_id, amount_cents, status FROM orders '
                                'WHERE user_id = ? ORDER BY id DESC', (user_id,)).fetchall()
