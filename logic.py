"""
logic.py - Business rules for MedTracker.

Everything here is independent of the user interface so it can be tested with
pytest. The UI calls these functions and shows any ValidationError to the user
as a friendly message.

Main rules
----------
* Quantities are whole numbers greater than 0.
* Medicine names and batch numbers are matched case-insensitively with spaces
  trimmed.
* Stock and dispensing dates cannot be in the future.
* Dispensing uses FEFO (first-expiry-first-out): take from the batch that
  expires soonest, skip expired batches, and split across batches if needed.
* A batch counts as expired for dispensing when its expiry date is BEFORE the
  dispensing date (it can still be used on its expiry day).
"""

import calendar
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

import db
from config import EXPIRY_WARNING_DAYS

STOCK_IN = "STOCK_IN"
DISPENSED = "DISPENSED"

# Status labels (also used by the UI for colour coding)
STATUS_OK = "OK"
STATUS_LOW = "LOW"
STATUS_OUT = "OUT OF STOCK"
BATCH_OK = "OK"
BATCH_EXPIRING = "Expiring soon"
BATCH_EXPIRED = "EXPIRED"
BATCH_USED_UP = "Used up"


# --------------------------------------------------------------------------
# Errors
# --------------------------------------------------------------------------

class ValidationError(ValueError):
    """A problem with what the user entered. The message is shown as-is."""


class InsufficientStockError(ValidationError):
    """Not enough (non-expired) stock to dispense the requested quantity."""


class ExpiredBatchError(ValidationError):
    """The chosen batch has expired."""


# --------------------------------------------------------------------------
# Small validation helpers
# --------------------------------------------------------------------------

def clean(text) -> str:
    """Trim spaces; treat None as an empty string."""
    return (text or "").strip()


def to_date(value) -> date:
    """Accept a date, a datetime or an ISO 'YYYY-MM-DD' string."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise ValidationError(f"'{value}' is not a valid date (expected YYYY-MM-DD).") from None


def validate_quantity(value) -> int:
    """Return the quantity as an int, or raise ValidationError."""
    message = "Quantity must be a whole number greater than 0."
    if isinstance(value, bool):
        raise ValidationError(message)
    if isinstance(value, float):
        if not value.is_integer():
            raise ValidationError(message)
        value = int(value)
    if isinstance(value, str):
        value = value.strip()
        if not value.isdigit():
            raise ValidationError(message)
        value = int(value)
    if not isinstance(value, int) or value <= 0:
        raise ValidationError(message)
    return value


def require_text(value, field_name: str) -> str:
    text = clean(value)
    if not text:
        raise ValidationError(f"{field_name} is required.")
    return text


def validate_not_future(d: date, today: date, what: str) -> None:
    if d > today:
        raise ValidationError(f"The {what} date cannot be in the future.")


def validate_reorder_level(value) -> int:
    try:
        level = int(value)
    except (TypeError, ValueError):
        raise ValidationError("Reorder level must be a whole number (0 or more).") from None
    if level < 0 or (isinstance(value, float) and not value.is_integer()):
        raise ValidationError("Reorder level must be a whole number (0 or more).")
    return level


def _now_text(now: datetime | None = None) -> str:
    return (now or datetime.now()).strftime("%Y-%m-%d %H:%M:%S")


# --------------------------------------------------------------------------
# Status helpers
# --------------------------------------------------------------------------

def stock_status(stock: int, reorder_level: int) -> str:
    if stock <= 0:
        return STATUS_OUT
    if stock <= reorder_level:
        return STATUS_LOW
    return STATUS_OK


def days_to_expiry(expiry, today: date) -> int:
    return (to_date(expiry) - today).days


def batch_status(remaining: int, expiry, today: date) -> str:
    if remaining <= 0:
        return BATCH_USED_UP
    days = days_to_expiry(expiry, today)
    if days < 0:
        return BATCH_EXPIRED
    if days <= EXPIRY_WARNING_DAYS:
        return BATCH_EXPIRING
    return BATCH_OK


# --------------------------------------------------------------------------
# FEFO allocation (pure function - easy to test)
# --------------------------------------------------------------------------

@dataclass
class BatchStock:
    batch_id: int
    batch_no: str
    expiry: date
    remaining: int


@dataclass
class Allocation:
    batch_id: int
    batch_no: str
    expiry: date
    quantity: int


def is_expired_on(expiry: date, on_date: date) -> bool:
    """A batch is expired for dispensing if it expires BEFORE the dispensing date."""
    return expiry < on_date


def usable_batches(batches: list[BatchStock], on_date: date) -> list[BatchStock]:
    """Non-expired batches with stock, soonest expiry first."""
    usable = [b for b in batches if b.remaining > 0 and not is_expired_on(b.expiry, on_date)]
    return sorted(usable, key=lambda b: (b.expiry, b.batch_id))


def allocate_fefo(batches: list[BatchStock], quantity: int, on_date: date) -> list[Allocation]:
    """
    Decide which batches to take `quantity` from (first-expiry-first-out).

    Raises InsufficientStockError if the non-expired stock is too small.
    """
    quantity = validate_quantity(quantity)
    usable = usable_batches(batches, on_date)
    available = sum(b.remaining for b in usable)
    if available < quantity:
        raise InsufficientStockError(
            f"Not enough usable stock: {quantity} requested but only {available} "
            f"available in non-expired batches."
        )
    allocations: list[Allocation] = []
    still_needed = quantity
    for b in usable:
        take = min(b.remaining, still_needed)
        allocations.append(Allocation(b.batch_id, b.batch_no, b.expiry, take))
        still_needed -= take
        if still_needed == 0:
            break
    return allocations


def load_batch_stock(conn, medicine_id: int) -> list[BatchStock]:
    return [
        BatchStock(r["id"], r["batch_no"], to_date(r["expiry_date"]), int(r["remaining"]))
        for r in db.batches_for_medicine(conn, medicine_id)
    ]


def dispensable_batches(conn, medicine_name: str, on_date) -> list[BatchStock]:
    """Batches the user may pick in the Record Dispensed dialog."""
    med = db.find_medicine(conn, clean(medicine_name))
    if med is None:
        return []
    return usable_batches(load_batch_stock(conn, med["id"]), to_date(on_date))


# --------------------------------------------------------------------------
# Add stock
# --------------------------------------------------------------------------

@dataclass
class AddStockCheck:
    """Things the UI must warn about BEFORE saving a stock entry."""
    medicine_exists: bool
    batch_exists: bool
    existing_expiry: date | None      # expiry already stored for this batch
    expiry_conflict: bool             # batch exists with a different expiry
    effective_expiry: date            # the expiry that will actually be used
    already_expired: bool             # expiry on or before the stock date


@dataclass
class AddStockResult:
    medicine_name: str
    unit: str
    batch_no: str
    expiry: date
    quantity: int
    new_stock: int
    created_medicine: bool
    created_batch: bool
    kept_original_expiry: bool


def check_add_stock(conn, stock_date, medicine_name, batch_no, expiry_date) -> AddStockCheck:
    stock_date = to_date(stock_date)
    expiry_date = to_date(expiry_date)
    medicine_name = require_text(medicine_name, "Medicine name")
    batch_no = require_text(batch_no, "Batch number")

    med = db.find_medicine(conn, medicine_name)
    batch = db.find_batch(conn, med["id"], batch_no) if med else None
    existing_expiry = to_date(batch["expiry_date"]) if batch else None
    effective = existing_expiry or expiry_date
    return AddStockCheck(
        medicine_exists=med is not None,
        batch_exists=batch is not None,
        existing_expiry=existing_expiry,
        expiry_conflict=existing_expiry is not None and existing_expiry != expiry_date,
        effective_expiry=effective,
        already_expired=effective <= stock_date,
    )


def add_stock(conn, stock_date, medicine_name, quantity, batch_no, expiry_date,
              unit: str | None = None, reorder_level: int | None = None,
              today: date | None = None, now: datetime | None = None) -> AddStockResult:
    """
    Record stock received. Creates the medicine (needs unit + reorder level)
    and/or the batch if they are new. If the batch already exists, its
    original expiry date is kept.
    """
    today = today or date.today()
    stock_date = to_date(stock_date)
    expiry_date = to_date(expiry_date)
    quantity = validate_quantity(quantity)
    medicine_name = require_text(medicine_name, "Medicine name")
    batch_no = require_text(batch_no, "Batch number")
    validate_not_future(stock_date, today, "stock")

    with db.transaction(conn):
        med = db.find_medicine(conn, medicine_name)
        created_medicine = med is None
        if created_medicine:
            unit = require_text(unit, "Unit (for a new medicine)")
            level = validate_reorder_level(0 if reorder_level is None else reorder_level)
            med = db.get_medicine(conn, db.create_medicine(conn, medicine_name, unit, level))

        batch = db.find_batch(conn, med["id"], batch_no)
        created_batch = batch is None
        if created_batch:
            batch_id = db.create_batch(conn, med["id"], batch_no, expiry_date.isoformat())
            used_expiry, used_batch_no = expiry_date, batch_no
        else:
            batch_id = batch["id"]
            used_expiry, used_batch_no = to_date(batch["expiry_date"]), batch["batch_no"]

        new_stock = db.medicine_stock(conn, med["id"]) + quantity
        db.insert_transaction(
            conn, tx_date=stock_date.isoformat(), medicine_id=med["id"], batch_id=batch_id,
            tx_type=STOCK_IN, quantity=quantity, balance_after=new_stock,
            entry_group=uuid.uuid4().hex, entered_at=_now_text(now),
        )

    return AddStockResult(
        medicine_name=med["name"], unit=med["unit"], batch_no=used_batch_no,
        expiry=used_expiry, quantity=quantity, new_stock=new_stock,
        created_medicine=created_medicine, created_batch=created_batch,
        kept_original_expiry=(not created_batch) and used_expiry != expiry_date,
    )


# --------------------------------------------------------------------------
# Dispense
# --------------------------------------------------------------------------

@dataclass
class DispenseResult:
    medicine_name: str
    unit: str
    quantity: int
    allocations: list[Allocation]
    remaining_stock: int
    reorder_level: int

    @property
    def status(self) -> str:
        return stock_status(self.remaining_stock, self.reorder_level)

    @property
    def low_stock(self) -> bool:
        """True when stock is now at or below the reorder level."""
        return self.remaining_stock <= self.reorder_level


def dispense(conn, dispense_date, medicine_name, quantity, batch_no: str | None = None,
             patient_id: str = "", prescriber: str = "",
             today: date | None = None, now: datetime | None = None) -> DispenseResult:
    """
    Record medicine dispensed.

    batch_no=None (or "") means automatic FEFO allocation, which may split the
    quantity across several batches (one transaction row per batch). All rows
    are saved in one database transaction.
    """
    today = today or date.today()
    dispense_date = to_date(dispense_date)
    quantity = validate_quantity(quantity)
    medicine_name = require_text(medicine_name, "Medicine")
    batch_no = clean(batch_no)
    validate_not_future(dispense_date, today, "dispensing")

    with db.transaction(conn):
        med = db.find_medicine(conn, medicine_name)
        if med is None:
            raise ValidationError(
                f"'{medicine_name}' is not in the list of medicines. Add stock for it first.")
        batches = load_batch_stock(conn, med["id"])

        if batch_no:
            chosen = next((b for b in batches if b.batch_no.casefold() == batch_no.casefold()), None)
            if chosen is None:
                raise ValidationError(f"Batch '{batch_no}' was not found for {med['name']}.")
            if is_expired_on(chosen.expiry, dispense_date):
                raise ExpiredBatchError(
                    f"Batch {chosen.batch_no} expired on {chosen.expiry.isoformat()} "
                    f"and cannot be dispensed.")
            if chosen.remaining < quantity:
                raise InsufficientStockError(
                    f"Batch {chosen.batch_no} only has {chosen.remaining} {med['unit']} left "
                    f"({quantity} requested).")
            allocations = [Allocation(chosen.batch_id, chosen.batch_no, chosen.expiry, quantity)]
        else:
            allocations = allocate_fefo(batches, quantity, dispense_date)

        balance = db.medicine_stock(conn, med["id"])
        group = uuid.uuid4().hex
        entered_at = _now_text(now)
        for alloc in allocations:
            balance -= alloc.quantity
            db.insert_transaction(
                conn, tx_date=dispense_date.isoformat(), medicine_id=med["id"],
                batch_id=alloc.batch_id, tx_type=DISPENSED, quantity=alloc.quantity,
                balance_after=balance, entry_group=group, entered_at=entered_at,
                patient_id=clean(patient_id), prescriber=clean(prescriber),
            )

    return DispenseResult(
        medicine_name=med["name"], unit=med["unit"], quantity=quantity,
        allocations=allocations, remaining_stock=balance,
        reorder_level=int(med["reorder_level"]),
    )


# --------------------------------------------------------------------------
# Undo
# --------------------------------------------------------------------------

def last_entry(conn) -> list:
    """Rows of the most recent entry (a split dispensing has several rows)."""
    return db.last_entry_rows(conn)


def undo_last_entry(conn, expected_group: str | None = None) -> list:
    """
    Delete the most recent entry. If `expected_group` is given, only delete
    if it is still the most recent one (protects against deleting the wrong
    entry if something changed after the user was asked to confirm).
    """
    with db.transaction(conn):
        rows = db.last_entry_rows(conn)
        if not rows:
            raise ValidationError("There is nothing to undo.")
        group = rows[0]["entry_group"]
        if expected_group is not None and group != expected_group:
            raise ValidationError("The latest entry has changed. Please try again.")
        db.delete_entry_group(conn, group)
    return rows


def create_medicine(conn, name, unit, reorder_level=0) -> int:
    """Add a new medicine (with no stock yet). Names must be unique, ignoring case."""
    name = require_text(name, "Medicine name")
    unit = require_text(unit, "Unit")
    level = validate_reorder_level(reorder_level)
    with db.transaction(conn):
        existing = db.find_medicine(conn, name)
        if existing is not None:
            raise ValidationError(f"'{existing['name']}' already exists.")
        return db.create_medicine(conn, name, unit, level)


def update_medicine_settings(conn, medicine_id: int, unit=None, reorder_level=None) -> None:
    """Edit a medicine's unit and/or reorder level (the only editable fields)."""
    if unit is not None:
        unit = require_text(unit, "Unit")
    if reorder_level is not None:
        reorder_level = validate_reorder_level(reorder_level)
    db.update_medicine(conn, medicine_id, unit=unit, reorder_level=reorder_level)


# --------------------------------------------------------------------------
# Stock tables
# --------------------------------------------------------------------------

def medicine_rows(conn) -> list[dict]:
    """Rows for the Medicines table on the Stock & Batches page."""
    rows = []
    for r in db.medicine_summary(conn):
        stock = int(r["received"]) - int(r["dispensed"])
        rows.append({
            "id": r["id"], "name": r["name"], "unit": r["unit"],
            "reorder_level": int(r["reorder_level"]),
            "received": int(r["received"]), "dispensed": int(r["dispensed"]),
            "stock": stock, "status": stock_status(stock, int(r["reorder_level"])),
            "nearest_expiry": r["nearest_expiry"],
        })
    return rows


def batch_rows(conn, today: date | None = None) -> list[dict]:
    """Rows for the Batches table on the Stock & Batches page."""
    today = today or date.today()
    rows = []
    for r in db.batch_summary(conn):
        remaining = int(r["received"]) - int(r["dispensed"])
        rows.append({
            "id": r["id"], "medicine": r["medicine"], "unit": r["unit"],
            "batch_no": r["batch_no"], "expiry": r["expiry_date"],
            "received": int(r["received"]), "dispensed": int(r["dispensed"]),
            "remaining": remaining,
            "days_to_expiry": days_to_expiry(r["expiry_date"], today),
            "status": batch_status(remaining, r["expiry_date"], today),
        })
    return rows


def log_rows(conn) -> list[dict]:
    return [dict(r) for r in db.log_rows(conn)]


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------

def month_bounds(year: int, month: int) -> tuple[date, date]:
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last_day)


def daily_series(conn, start: date, end: date) -> list[tuple[date, int]]:
    """Quantity dispensed per day, with 0 for days without dispensing."""
    by_day = {r["date"]: int(r["qty"])
              for r in db.dispensed_by_day(conn, start.isoformat(), end.isoformat())}
    days = (end - start).days + 1
    return [(start + timedelta(days=i), by_day.get((start + timedelta(days=i)).isoformat(), 0))
            for i in range(days)]


@dataclass
class DashboardData:
    dispensed_this_month: int
    medicine_count: int
    low_or_out_count: int
    expiry_alert_count: int
    top_dispensed: list[tuple[str, int]]           # (medicine, qty) - top 10
    lowest_stock: list[tuple[str, int, str]]       # (medicine, stock, status) - 15 lowest
    daily: list[tuple[date, int]]                  # current month, 1st day up to today
    stock_alerts: list[dict] = field(default_factory=list)
    expiry_alerts: list[dict] = field(default_factory=list)


def dashboard_data(conn, today: date | None = None) -> DashboardData:
    today = today or date.today()
    start, end = month_bounds(today.year, today.month)
    s, e = start.isoformat(), end.isoformat()

    medicines = medicine_rows(conn)
    stock_alerts = [m for m in medicines if m["stock"] <= m["reorder_level"]]
    stock_alerts.sort(key=lambda m: (m["stock"], m["name"].casefold()))

    # Only batches that still have stock matter for expiry alerts.
    expiry_alerts = [b for b in batch_rows(conn, today)
                     if b["status"] in (BATCH_EXPIRED, BATCH_EXPIRING)]
    expiry_alerts.sort(key=lambda b: b["expiry"])

    lowest = sorted(medicines, key=lambda m: (m["stock"], m["name"].casefold()))[:15]

    return DashboardData(
        dispensed_this_month=db.total_quantity(conn, DISPENSED, s, e),
        medicine_count=len(medicines),
        low_or_out_count=len(stock_alerts),
        expiry_alert_count=len(expiry_alerts),
        top_dispensed=[(r["name"], int(r["qty"]))
                       for r in db.quantity_by_medicine(conn, DISPENSED, s, e)[:10]],
        lowest_stock=[(m["name"], m["stock"], m["status"]) for m in lowest],
        daily=daily_series(conn, start, min(end, today)),
        stock_alerts=stock_alerts,
        expiry_alerts=expiry_alerts,
    )


# --------------------------------------------------------------------------
# Monthly report
# --------------------------------------------------------------------------

@dataclass
class MonthlyReport:
    year: int
    month: int
    total_dispensed: int
    total_received: int
    entry_count: int
    medicines_dispensed: int
    days_counted: int
    avg_per_day: float
    medicines: list[dict]                 # ranked table rows
    top_days: list[tuple[date, int]]      # top 5 busiest days
    prescribers: list[dict]               # prescriber, qty, entries

    @property
    def title(self) -> str:
        return f"{calendar.month_name[self.month]} {self.year}"


def monthly_report(conn, year: int, month: int, today: date | None = None) -> MonthlyReport:
    today = today or date.today()
    start, end = month_bounds(year, month)
    s, e = start.isoformat(), end.isoformat()

    dispensed = {r["id"]: int(r["qty"]) for r in db.quantity_by_medicine(conn, DISPENSED, s, e)}
    received = {r["id"]: int(r["qty"]) for r in db.quantity_by_medicine(conn, STOCK_IN, s, e)}
    total_dispensed = sum(dispensed.values())
    total_received = sum(received.values())

    rows = []
    for m in medicine_rows(conn):
        if m["id"] not in dispensed and m["id"] not in received:
            continue  # no activity this month
        qty = dispensed.get(m["id"], 0)
        rows.append({
            "medicine": m["name"], "unit": m["unit"], "dispensed": qty,
            "percent": round(100.0 * qty / total_dispensed, 1) if total_dispensed else 0.0,
            "received": received.get(m["id"], 0),
            "stock": m["stock"], "status": m["status"],
        })
    rows.sort(key=lambda r: (-r["dispensed"], r["medicine"].casefold()))
    for rank, r in enumerate(rows, start=1):
        r["rank"] = rank

    # Average per day: over the days elapsed so far for the current month,
    # over the whole month for past months.
    if start <= today <= end:
        days_counted = today.day
    else:
        days_counted = (end - start).days + 1

    daily = daily_series(conn, start, end)
    top_days = sorted((d for d in daily if d[1] > 0), key=lambda d: (-d[1], d[0]))[:5]

    return MonthlyReport(
        year=year, month=month,
        total_dispensed=total_dispensed, total_received=total_received,
        entry_count=db.dispensing_entry_count(conn, s, e),
        medicines_dispensed=len(dispensed),
        days_counted=days_counted,
        avg_per_day=round(total_dispensed / days_counted, 1) if days_counted else 0.0,
        medicines=rows, top_days=top_days,
        prescribers=[{"prescriber": r["prescriber"], "qty": int(r["qty"]),
                      "entries": int(r["entries"])}
                     for r in db.dispensed_by_prescriber(conn, s, e)],
    )
