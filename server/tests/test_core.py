"""The sync server's rules (sync_server/core.py), on the in-memory store."""

from datetime import datetime, timedelta

import pytest

from sync_schema import BAD_CODE, REVOKED, USERNAME_TAKEN, new_uid
from sync_server.core import Core, SyncError
from sync_server.store_memory import MemoryStore

NOW = datetime(2026, 11, 25, 9, 0)


@pytest.fixture
def core():
    return Core(MemoryStore())


def device(core, name="pc1"):
    return core.join(core.make_code(NOW), name, NOW)["device"]


def change(table, key, op="upsert", data=None, into=None):
    return {"change_uid": new_uid(), "table": table, "key": key, "op": op, "data": data, "into": into}


def medicine(name="Paracetamol", uid=None):
    return change("medicines", uid or new_uid(), data={
        "name": name, "unit": "tablets", "reorder_level": 10, "note": "", "created_at": "2026-11-25 09:00:00"})


def batch(medicine_uid, batch_no="B001", uid=None):
    return change("batches", uid or new_uid(), data={
        "medicine_uid": medicine_uid, "batch_no": batch_no, "expiry_date": "2027-01-31",
        "created_at": "2026-11-25 09:00:00"})


def entry(medicine_uid, batch_uid, quantity=10, kind="STOCK_IN", uid=None):
    return change("transactions", uid or new_uid(), data={
        "date": "2026-11-25", "medicine_uid": medicine_uid, "batch_uid": batch_uid, "type": kind,
        "quantity": quantity, "patient_id": "", "prescriber": "", "entry_group": new_uid(),
        "entered_at": "2026-11-25 09:00:00", "entered_by": "Ama", "reason": "", "made_on": "pc1"})


def user(username="ama", uid=None):
    return change("users", uid or new_uid(), data={
        "username": username, "full_name": "Ama Mensah", "password_hash": "pbkdf2$x", "pin_hash": "",
        "can_delete_medicines": 0, "role": "user", "status": "pending",
        "created_at": "2026-11-25 09:00:00", "decided_by": "", "decided_at": ""})


def stocked(core, dev, name="Paracetamol", batch_no="B001"):
    """Push a medicine, a batch and a delivery; return their changes."""
    m = medicine(name)
    b = batch(m["key"], batch_no)
    e = entry(m["key"], b["key"])
    core.push(dev, [m, b, e])
    return m, b, e


# --- joining ---------------------------------------------------------------------

def test_join_code_single_use_and_expires(core):
    code = core.make_code(NOW)
    assert len(code) == 9 and code[4] == "-"
    core.join(code, "pc1", NOW)
    with pytest.raises(SyncError) as err:
        core.join(code, "pc2", NOW)
    assert (err.value.status, err.value.message) == (404, BAD_CODE)
    late = core.make_code(NOW)
    with pytest.raises(SyncError):
        core.join(late, "pc2", NOW + timedelta(hours=25))


def test_join_code_ignores_case_and_dash(core):
    code = core.make_code(NOW)
    assert core.join(code.replace("-", "").lower(), "pc1", NOW)["device"]


def test_first_join_reports_empty_then_not(core):
    first = core.join(core.make_code(NOW), "pc1", NOW)
    assert first["empty"] is True
    core.push(first["device"], [medicine()])
    assert core.join(core.make_code(NOW), "pc2", NOW)["empty"] is False


def test_token_hash_only_stored(core):
    joined = core.join(core.make_code(NOW), "pc1", NOW)
    assert joined["token"] not in repr(vars(core.store))
    assert core.device_for(joined["token"], NOW) == joined["device"]


def test_unknown_token_refused(core):
    with pytest.raises(SyncError) as err:
        core.device_for("nope", NOW)
    assert err.value.status == 401


def test_revoked_device_refused(core):
    joined = core.join(core.make_code(NOW), "front-desk", NOW)
    core.revoke("front-desk")
    with pytest.raises(SyncError) as err:
        core.device_for(joined["token"], NOW)
    assert (err.value.status, err.value.message) == (403, REVOKED)
    assert [c["revoked"] for c in core.computers()] == [True]


# --- pushing and pulling ---------------------------------------------------------

def test_push_numbers_changes_and_pull_returns_them_in_order(core):
    dev = device(core)
    m, b, e = stocked(core, dev)
    pulled = core.pull(0)
    assert [c["change_uid"] for c in pulled["changes"]] == [m["change_uid"], b["change_uid"], e["change_uid"]]
    assert [c["seq"] for c in pulled["changes"]] == [1, 2, 3]
    assert {c["device"] for c in pulled["changes"]} == {dev}
    assert pulled["more"] is False
    assert core.pull(2)["changes"][0]["change_uid"] == e["change_uid"]


def test_repeated_push_is_ignored(core):
    dev = device(core)
    m = medicine()
    first = core.push(dev, [m])
    again = core.push(dev, [m])
    assert first["seq"] == again["seq"] == 1
    assert len(core.pull(0)["changes"]) == 1


@pytest.mark.parametrize("broken", [
    lambda c: c["data"].update(quantity=0),
    lambda c: c["data"].update(quantity="5"),
    lambda c: c["data"].update(type="STOLEN"),
    lambda c: c["data"].pop("date"),
    lambda c: c["data"].update(batch_uid=new_uid()),          # unknown reference
    lambda c: c.update(table="patients"),
    lambda c: c.update(op="explode"),
])
def test_invalid_change_refuses_whole_push(core, broken):
    dev = device(core)
    m = medicine()
    b = batch(m["key"])
    bad = entry(m["key"], b["key"])
    broken(bad)
    with pytest.raises(SyncError) as err:
        core.push(dev, [m, b, bad])
    assert err.value.status == 400
    assert core.pull(0)["changes"] == []
    assert core.snapshot()["rows"]["medicines"] == []


def test_empty_name_refused(core):
    with pytest.raises(SyncError):
        core.push(device(core), [medicine(" ")])


def test_duplicate_medicine_name_becomes_merge(core):
    dev = device(core)
    first = medicine("Amoxicillin")
    core.push(dev, [first])
    second = medicine("amoxicillin")
    core.push(dev, [second])
    last = core.pull(1)["changes"]
    assert [(c["op"], c["key"], c["into"], c["device"]) for c in last] == \
        [("merge", second["key"], first["key"], None)]
    assert len(core.snapshot()["rows"]["medicines"]) == 1


def test_reference_to_merged_medicine_is_rewritten(core):
    dev = device(core)
    first = medicine("Amoxicillin")
    core.push(dev, [first])
    second = medicine("AMOXICILLIN")
    b = batch(second["key"], "X9")
    core.push(dev, [second, b])
    stored = core.snapshot()["rows"]["batches"]
    assert [r["medicine_uid"] for r in stored] == [first["key"]]


def test_duplicate_batch_becomes_merge(core):
    dev = device(core)
    m, b, _ = stocked(core, dev, batch_no="B001")
    other = batch(m["key"], "b001")
    e = entry(m["key"], other["key"])
    core.push(dev, [other, e])
    merges = [c for c in core.pull(0)["changes"] if c["op"] == "merge"]
    assert [(c["table"], c["key"], c["into"]) for c in merges] == [("batches", other["key"], b["key"])]
    assert {r["batch_uid"] for r in core.snapshot()["rows"]["transactions"]} == {b["key"]}


def test_duplicate_username_rejected(core):
    dev = device(core)
    core.push(dev, [user("ama")])
    late = user("AMA")
    result = core.push(dev, [late])
    assert result["rejected"] == [{"change_uid": late["change_uid"], "table": "users", "key": late["key"],
                                   "reason": USERNAME_TAKEN, "current": None}]
    assert len(core.snapshot()["rows"]["users"]) == 1


def test_renaming_onto_another_medicine_rejected(core):
    dev = device(core)
    core.push(dev, [medicine("Ibuprofen")])
    m = medicine("Paracetamol")
    core.push(dev, [m])
    rename = change("medicines", m["key"], data=dict(m["data"], name="ibuprofen"))
    rejected = core.push(dev, [rename])["rejected"]
    assert rejected[0]["current"]["name"] == "Paracetamol"


def test_delete_medicine_with_entries_rejected_with_current_row(core):
    dev = device(core)
    m, b, _ = stocked(core, dev)
    result = core.push(dev, [change("batches", b["key"], "delete"), change("medicines", m["key"], "delete")])
    assert [(r["table"], r["current"]["uid"]) for r in result["rejected"]] == \
        [("batches", b["key"]), ("medicines", m["key"])]
    assert len(core.snapshot()["rows"]["medicines"]) == 1


def test_delete_unused_medicine_accepted(core):
    dev = device(core)
    m = medicine()
    core.push(dev, [m])
    assert core.push(dev, [change("medicines", m["key"], "delete")])["rejected"] == []
    assert core.snapshot()["rows"]["medicines"] == []


def test_edit_after_delete_rejected(core):
    dev = device(core)
    m, b, e = stocked(core, dev)
    core.push(dev, [change("transactions", e["key"], "delete")])
    edit = change("transactions", e["key"], data=dict(e["data"], quantity=12))
    rejected = core.push(dev, [edit])["rejected"]
    assert [(r["key"], r["current"]) for r in rejected] == [(e["key"], None)]


def test_entry_for_deleted_medicine_brings_it_back(core):
    """Deleted on one computer while another recorded stock for it: the stock wins."""
    dev = device(core)
    m = medicine()
    b = batch(m["key"])
    core.push(dev, [m, b])
    core.push(dev, [change("batches", b["key"], "delete"), change("medicines", m["key"], "delete")])
    e = entry(m["key"], b["key"])
    assert core.push(dev, [e])["rejected"] == []
    rows = core.snapshot()["rows"]
    assert len(rows["medicines"]) == len(rows["batches"]) == len(rows["transactions"]) == 1
    restored = [c for c in core.pull(0)["changes"] if c["device"] is None]
    assert [(c["table"], c["op"]) for c in restored] == [("medicines", "upsert"), ("batches", "upsert")]


def test_unit_names_ignore_case(core):
    dev = device(core)
    core.push(dev, [change("units", "Tablets", data={})])
    core.push(dev, [change("units", "tablets", data={})])
    assert core.snapshot()["rows"]["units"] == [{"name": "Tablets"}]


def test_snapshot_has_every_live_row_and_seq(core):
    dev = device(core)
    m, b, e = stocked(core, dev)
    core.push(dev, [user()])
    snap = core.snapshot()
    assert snap["seq"] == 4
    assert snap["rows"]["transactions"] == [dict(e["data"], uid=e["key"])]
    assert set(snap["rows"]) == {"units", "users", "medicines", "batches", "transactions", "audit_log"}


def test_pull_limit_and_more_flag(core):
    dev = device(core)
    core.push(dev, [medicine(f"Med {i}") for i in range(5)])
    page = core.pull(0, limit=3)
    assert [c["seq"] for c in page["changes"]] == [1, 2, 3] and page["more"] is True
    assert core.pull(3, limit=3)["more"] is False


# --- status page data ------------------------------------------------------------

def test_status_counts_changes_computers_rows_and_codes(core):
    front, back = device(core, "front-desk"), device(core, "back-office")
    stocked(core, front)
    core.push(back, [medicine("Ibuprofen")])
    core.revoke("back-office")
    core.make_code(NOW)

    status = core.status(NOW)
    assert status["last_seq"] == 4 and status["changes_24h"] == 4
    assert status["last_change_at"] is not None
    assert status["tables"]["medicines"] == 2 and status["tables"]["batches"] == 1
    assert status["tables"]["users"] == 0
    assert status["open_codes"] == 1                       # the two used to join are not counted
    computers = {c["name"]: c for c in status["computers"]}
    assert computers["front-desk"]["changes_total"] == 3 and not computers["front-desk"]["revoked"]
    assert computers["back-office"]["changes_24h"] == 1 and computers["back-office"]["revoked"]


def test_status_of_an_empty_server(core):
    status = core.status(NOW)
    assert status["last_seq"] == 0 and status["last_change_at"] is None
    assert status["computers"] == [] and status["open_codes"] == 0
