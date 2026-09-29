"""Monthly report totals and the dashboard figures."""

import db
import logic
from tests.conftest import TODAY


def test_monthly_report_totals(conn, add, give):
    # May activity (should NOT appear in June's report)
    add(name="Paracetamol", qty=100, on="2026-05-10")
    give(name="Paracetamol", qty=7, on="2026-05-20", prescriber="Dr Old")

    # June activity
    add(name="Ibuprofen", qty=60, batch="I1", on="2026-06-01", reorder=10)
    give(name="Paracetamol", qty=10, on="2026-06-02", prescriber="Dr A")
    give(name="Paracetamol", qty=20, on="2026-06-02", prescriber="Dr B")
    give(name="Ibuprofen", qty=30, on="2026-06-05", prescriber="Dr A")

    report = logic.monthly_report(conn, 2026, 6, today=TODAY)

    assert report.total_dispensed == 60
    assert report.total_received == 60
    assert report.entry_count == 3
    assert report.medicines_dispensed == 2
    assert report.days_counted == 15            # current month: days so far
    assert report.avg_per_day == 4.0

    ranked = [(r["rank"], r["medicine"], r["dispensed"], r["percent"]) for r in report.medicines]
    assert ranked == [(1, "Ibuprofen", 30, 50.0), (2, "Paracetamol", 30, 50.0)]
    assert report.medicines[0]["received"] == 60
    assert report.medicines[1]["stock"] == 63   # 100 - 7 - 10 - 20

    assert [(d.isoformat(), q) for d, q in report.top_days] == [
        ("2026-06-02", 30), ("2026-06-05", 30)]
    assert {p["prescriber"]: (p["qty"], p["entries"]) for p in report.prescribers} == {
        "Dr A": (40, 2), "Dr B": (20, 1)}


def test_split_dispensing_counts_as_one_entry(conn, add, give):
    add(qty=5, batch="A", expiry="2026-12-01")
    add(qty=5, batch="B", expiry="2027-12-01")
    give(qty=8, on="2026-06-03")
    report = logic.monthly_report(conn, 2026, 6, today=TODAY)
    assert report.entry_count == 1 and report.total_dispensed == 8


def test_past_month_average_uses_all_days(conn, add, give):
    add(on="2026-04-01")
    give(qty=30, on="2026-04-10")
    report = logic.monthly_report(conn, 2026, 4, today=TODAY)
    assert report.days_counted == 30 and report.avg_per_day == 1.0


def test_dashboard_figures(conn, add, give):
    add(name="Paracetamol", qty=100, reorder=20)
    add(name="Insulin", qty=3, batch="V1", unit="vials", reorder=5, expiry="2026-08-01")
    give(name="Paracetamol", qty=12, on="2026-06-03")

    data = logic.dashboard_data(conn, today=TODAY)
    assert data.dispensed_this_month == 12
    assert data.medicine_count == 2
    assert data.low_or_out_count == 1                 # Insulin 3 <= 5
    assert data.expiry_alert_count == 1               # Insulin batch expires in 47 days
    assert data.top_dispensed == [("Paracetamol", 12)]
    assert data.lowest_stock[0] == ("Insulin", 3, logic.STATUS_LOW)
    assert len(data.daily) == 15 and data.daily[2][1] == 12 and data.daily[0][1] == 0


def test_backup_and_restore_roundtrip(conn, add, tmp_path):
    add(qty=10)
    backup = tmp_path / "backup.db"
    db.backup_to(conn, backup)
    assert db.is_valid_backup(backup)
    add(qty=5, batch="B2", expiry="2027-02-02")
    db.restore_from(conn, backup)
    assert len(logic.log_rows(conn)) == 1


def test_invalid_backup_is_rejected(tmp_path):
    bogus = tmp_path / "not_a_db.db"
    bogus.write_text("hello")
    assert not db.is_valid_backup(bogus)
