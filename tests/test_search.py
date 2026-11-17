"""Search finds medicines by name or note; the detail view lists their log and batches."""

import db
import logic


def test_search_matches_name_or_note_ignoring_case(conn, add):
    add(name="Paracetamol 500mg")
    add(name="Amoxicillin", batch="A1")
    logic.create_medicine(conn, "Insulin", "vials", 2, note="Keep in FRIDGE")
    names = lambda text: [r["name"] for r in logic.search_medicines(conn, text)]
    assert names("para") == ["Paracetamol 500mg"]
    assert names("  fridge ") == ["Insulin"]
    assert names("") == ["Amoxicillin", "Insulin", "Paracetamol 500mg"]
    assert names("nothing like this") == []


def test_medicine_log_and_batches_only_cover_that_medicine(conn, add, give):
    add(qty=100, batch="B1")
    add(qty=50, batch="B2", expiry="2027-06-30")
    add(name="Ibuprofen", qty=30, batch="I1")
    give(qty=10)
    med_id = db.find_medicine(conn, "Paracetamol")["id"]

    log = logic.medicine_log(conn, med_id)
    assert [(r["type"], r["quantity"]) for r in log] == [
        (logic.DISPENSED, 10), (logic.STOCK_IN, 50), (logic.STOCK_IN, 100)]
    batches = logic.medicine_batches(conn, med_id)
    assert sorted(b["batch_no"] for b in batches) == ["B1", "B2"]
