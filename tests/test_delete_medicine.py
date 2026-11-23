"""Deleting a medicine: only one with no stock and nothing in the log, after confirmation."""

import pytest

import db
import logic


def _id(conn, name="Paracetamol"):
    return db.find_medicine(conn, name)["id"]


def test_delete_medicine_with_no_entries(conn):
    logic.create_medicine(conn, "Paracetamol", "tablets")
    assert logic.can_delete_medicine(conn, _id(conn))
    assert logic.delete_medicine(conn, _id(conn)) == "Paracetamol"
    assert db.find_medicine(conn, "Paracetamol") is None


def test_name_can_be_used_again_after_delete(conn):
    logic.create_medicine(conn, "Paracetamol", "tablets")
    logic.delete_medicine(conn, _id(conn))
    logic.create_medicine(conn, "Paracetamol", "bottles")
    assert db.find_medicine(conn, "Paracetamol")["unit"] == "bottles"


def test_refused_with_stock(conn, add):
    add(qty=100)
    assert not logic.can_delete_medicine(conn, _id(conn))
    with pytest.raises(logic.ValidationError,
                       match=r"'Paracetamol' can't be deleted because it has 1 entry in the log"):
        logic.delete_medicine(conn, _id(conn))
    assert db.find_medicine(conn, "Paracetamol") is not None


def test_refused_when_stock_is_zero_but_log_has_entries(conn, add, give):
    add(qty=10)
    give(qty=10)
    assert db.medicine_stock(conn, _id(conn)) == 0
    assert not logic.can_delete_medicine(conn, _id(conn))
    with pytest.raises(logic.ValidationError, match="has 2 entries in the log"):
        logic.delete_medicine(conn, _id(conn))


def test_deletable_once_its_only_entry_was_deleted(conn, add):
    add(qty=10)
    tx_id = logic.log_rows(conn)[0]["id"]
    logic.delete_entry(conn, tx_id, changed_by="Admin", reason="Wrong medicine")
    assert logic.can_delete_medicine(conn, _id(conn))
    logic.delete_medicine(conn, _id(conn))
    assert db.find_medicine(conn, "Paracetamol") is None
    assert logic.audit_rows(conn)                     # the audit trail is kept


def test_other_medicines_untouched(conn, add):
    add(name="Ibuprofen", qty=5)
    logic.create_medicine(conn, "Paracetamol", "tablets")
    logic.delete_medicine(conn, _id(conn))
    assert db.medicine_stock(conn, _id(conn, "Ibuprofen")) == 5


def test_missing_medicine(conn):
    with pytest.raises(logic.ValidationError, match="no longer exists"):
        logic.delete_medicine(conn, 999)


# --- the Edit Medicine pop-up ------------------------------------------------------

@pytest.fixture
def dialog_for(qapp, conn, monkeypatch):
    from ui import medicine as ui_medicine
    asked, infos = [], []
    monkeypatch.setattr(ui_medicine, "show_info", lambda parent, text, title="": infos.append(text))

    def make(name, answer=True):
        monkeypatch.setattr(ui_medicine, "ask_yes_no",
                            lambda parent, text, **k: asked.append((text, k)) or answer)
        row = next(r for r in logic.medicine_rows(conn) if r["name"] == name)
        return ui_medicine.EditMedicineDialog(conn, row, can_delete=lambda: True)
    make.asked, make.infos = asked, infos
    return make


def test_delete_button_disabled_when_medicine_has_log(dialog_for, add):
    add(qty=10)
    dialog = dialog_for("Paracetamol")
    assert not dialog.delete_button.isEnabled()
    assert "only be deleted when it has no stock and nothing in the log" in dialog.delete_button.toolTip()


def test_delete_asks_first_and_cancel_keeps_it(dialog_for, conn):
    logic.create_medicine(conn, "Paracetamol", "tablets")
    dialog = dialog_for("Paracetamol", answer=False)
    assert dialog.delete_button.isEnabled()
    dialog.delete_medicine()
    text, options = dialog_for.asked[0]
    assert "Delete 'Paracetamol'?" in text and "cannot be undone" in text
    assert options.get("yes_text") == "Delete"
    assert db.find_medicine(conn, "Paracetamol") is not None


def test_delete_confirmed(dialog_for, conn):
    from PySide6.QtWidgets import QDialog
    logic.create_medicine(conn, "Paracetamol", "tablets")
    dialog = dialog_for("Paracetamol", answer=True)
    dialog.delete_medicine()
    assert db.find_medicine(conn, "Paracetamol") is None
    assert dialog_for.infos == ["'Paracetamol' was deleted."]
    assert dialog.result() == QDialog.DialogCode.Accepted


def test_delete_button_hidden_without_permission(qapp, conn):
    from ui.medicine import EditMedicineDialog
    logic.create_medicine(conn, "Paracetamol", "tablets")
    row = logic.medicine_rows(conn)[0]
    assert EditMedicineDialog(conn, row, can_delete=lambda: False).delete_button.isHidden()
    assert not EditMedicineDialog(conn, row, can_delete=lambda: True).delete_button.isHidden()


def test_permission_checked_again_when_deleting(dialog_for, conn, monkeypatch):
    from ui import medicine as ui_medicine
    logic.create_medicine(conn, "Paracetamol", "tablets")
    allowed = [True]
    errors = []
    monkeypatch.setattr(ui_medicine, "show_error", lambda parent, text, title="": errors.append(text))
    row = logic.medicine_rows(conn)[0]
    monkeypatch.setattr(ui_medicine, "ask_yes_no", lambda *a, **k: True)
    dialog = ui_medicine.EditMedicineDialog(conn, row, can_delete=lambda: allowed[0])
    allowed[0] = False                                   # the superadmin took it away meanwhile
    dialog.delete_medicine()
    assert errors == ["You no longer have permission to delete medicines."]
    assert db.find_medicine(conn, "Paracetamol") is not None
