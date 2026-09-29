"""Shared pytest fixtures: every test gets its own fresh, empty database file."""

from datetime import date

import pytest

import db
import logic

# A fixed "today" so tests never depend on the real calendar.
TODAY = date(2026, 6, 15)


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def add(conn):
    """Helper: add stock with sensible defaults."""
    def _add(name="Paracetamol", qty=100, batch="B001", expiry="2027-01-31",
             on="2026-06-01", unit="tablets", reorder=20):
        return logic.add_stock(conn, on, name, qty, batch, expiry,
                               unit=unit, reorder_level=reorder, today=TODAY)
    return _add


@pytest.fixture
def give(conn):
    """Helper: dispense with sensible defaults."""
    def _give(name="Paracetamol", qty=10, batch=None, on="2026-06-10",
              patient="P1", prescriber="Dr A"):
        return logic.dispense(conn, on, name, qty, batch_no=batch, patient_id=patient,
                              prescriber=prescriber, today=TODAY)
    return _give
