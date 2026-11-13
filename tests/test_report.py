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
    assert [m["name"] for m in data.running_low] == ["Insulin", "Paracetamol"]  # 3/5, 88/20
    assert data.medicine_health == {logic.STATUS_OK: 1, logic.STATUS_LOW: 1, logic.STATUS_OUT: 0}
    assert data.batch_health == {logic.BATCH_OK: 1, logic.BATCH_EXPIRING: 1, logic.BATCH_EXPIRED: 0}
    timeline = [(b["label"], b["year"], len(b["batches"]), b["status"]) for b in data.expiry_timeline]
    assert timeline[0] == ("Expired", "", 0, logic.BATCH_EXPIRED)
    assert timeline[1:4] == [("Jun", "2026", 0, logic.BATCH_EXPIRING),
                             ("Jul", "2026", 0, logic.BATCH_EXPIRING),
                             ("Aug", "2026", 1, logic.BATCH_EXPIRING)]
    assert data.expiry_timeline[3]["batches"][0]["medicine"] == "Insulin"
    assert len(timeline) == 13
    assert data.reorder_levels_set == 2
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


def test_date_range_report_and_comparison(conn, add, give):
    # TODAY is Monday 15 June 2026.
    add(name="Paracetamol", qty=500, on="2026-05-01", expiry="2027-06-30")
    give(name="Paracetamol", qty=10, on="2026-06-01")          # previous 7 days
    give(name="Paracetamol", qty=4, on="2026-06-03")
    give(name="Paracetamol", qty=21, on="2026-06-09")          # this range: 9-15 June
    give(name="Paracetamol", qty=7, on="2026-06-12")
    give(name="Paracetamol", qty=7, on="2026-06-15")           # today

    r = logic.period_report(conn, "2026-06-09", "2026-06-15", today=TODAY)
    assert (r.total_dispensed, r.days_counted, r.avg_per_day) == (35, 7, 5.0)
    assert r.title == "9 June to 15 June 2026" and r.file_stem == "2026-06-09_to_2026-06-15"
    assert [q for _, q in r.daily] == [21, 0, 0, 7, 0, 0, 7]
    assert (r.prev_start.isoformat(), r.prev_end.isoformat()) == ("2026-06-02", "2026-06-08")
    assert r.prev_avg_per_day == round(4 / 7, 1) and r.prev_title == "the previous 7 days"
    assert r.change_vs_prev == round(100 * (5.0 - 0.6) / 0.6)
    # Weekday averages use finished days only: today (Monday 15th) is left out.
    assert r.weekday_avg[1] == 21.0 and r.weekday_days[1] == 1  # Tuesday 9 June
    assert r.weekday_days[0] == 0
    assert r.weekday_avg[4] == 7.0                              # Friday 12 June
    cover = r.stock_cover[0]
    assert cover["medicine"] == "Paracetamol" and cover["per_day"] == 5.0
    assert round(cover["days"]) == (500 - 49) // 5


def test_month_report_compares_with_previous_month(conn, add, give):
    add(name="Paracetamol", qty=500, on="2026-04-01", expiry="2027-06-30")
    give(name="Paracetamol", qty=31, on="2026-05-10")
    r = logic.monthly_report(conn, 2026, 6, today=TODAY)
    assert r.is_month and r.title == "June 2026" and r.prev_title == "May"
    assert r.prev_avg_per_day == 1.0 and len(r.prev_daily) == 31
    assert r.calendar_end.isoformat() == "2026-06-30" and r.end == TODAY


def test_no_comparison_before_the_first_record(conn, add, give):
    add(name="Paracetamol", qty=50, on="2026-06-10", expiry="2027-06-30")
    r = logic.period_report(conn, "2026-06-10", "2026-06-15", today=TODAY)
    assert r.prev_start is None and r.change_vs_prev is None and r.prev_title == ""


def test_entries_by_hour_and_deliveries(conn, add, give):
    from datetime import datetime
    add(name="Paracetamol", qty=50, on="2026-06-01", expiry="2027-06-30")
    add(name="Paracetamol", qty=50, batch="B2", on="2026-06-02", expiry="2027-06-30")
    for hour in (9, 9, 14):
        logic.dispense(conn, "2026-06-03", "Paracetamol", 1, today=TODAY,
                       now=datetime(2026, 6, 3, hour, 30))
    r = logic.period_report(conn, "2026-06-01", "2026-06-15", today=TODAY)
    assert r.hourly == {9: 2, 14: 1}
    assert r.deliveries == 2 and r.entry_count == 3


def test_invalid_ranges_are_rejected(conn):
    for start, end in (("2026-06-10", "2026-06-01"), ("2026-07-01", "2026-07-05")):
        try:
            logic.period_report(conn, start, end, today=TODAY)
        except logic.ValidationError:
            continue
        raise AssertionError(f"{start}..{end} should be rejected")
