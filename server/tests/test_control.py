"""Companies, join codes and computers (sync_server/control.py), on the in-memory stores."""

from datetime import datetime, timedelta

import pytest

from sync_schema import BAD_CODE, REVOKED
from sync_server.apps import database_name
from sync_server.control import NOT_ALLOWED, NOT_FOUND, UNAVAILABLE, Control
from sync_server.core import SyncError
from sync_server.store_memory import memory_control
from test_core import medicine, stocked

NOW = datetime(2026, 11, 26, 9, 0)


@pytest.fixture
def control():
    """A Control whose company databases live in `control.databases` (name -> Core)."""
    return memory_control()


def joined(control, company="acme", name="pc1", app="medtracker"):
    control.create_company(app, company, NOW)
    return control.join(control.make_code(app, company, NOW), name, NOW)


def refused(status, message=None):
    def check(call):
        with pytest.raises(SyncError) as err:
            call()
        assert err.value.status == status
        if message:
            assert err.value.message == message
    return check


# --- names -----------------------------------------------------------------------

def test_database_names():
    assert database_name("medtracker", "kumasi-clinic") == "medtracker__kumasi_clinic"
    assert database_name("medtracker", "a-b") != database_name("medtracker", "ab")
    assert len(database_name("medtracker", "x" * 40)) <= 63


@pytest.mark.parametrize("app,company", [
    ("Med", "x1"), ("medtracker", "A_B"), ("medtracker", ""), ("nope", "acme"),
    ("medtracker", "x" * 41), ("medtracker", "a_b"), ("medtracker", "-acme"), ("medtracker", "ac me"),
    ("medtracker", "a--b")])
def test_bad_names_not_found(control, app, company):
    refused(404, NOT_FOUND)(lambda: control.create_company(app, company, NOW))
    assert control.databases == {}


# --- companies -------------------------------------------------------------------

def test_create_company_once(control):
    first = control.create_company("medtracker", "acme", NOW)
    again = control.create_company("medtracker", "acme", NOW)
    assert (first["created"], again["created"]) == (True, False)
    assert first["code"] != again["code"]
    assert list(control.databases) == ["medtracker__acme"]
    assert [(c["app"], c["company"], c["database"]) for c in control.companies()] == \
        [("medtracker", "acme", "medtracker__acme")]


def test_code_for_unknown_company_not_found(control):
    refused(404, NOT_FOUND)(lambda: control.make_code("medtracker", "acme", NOW))


# --- joining ---------------------------------------------------------------------

def test_join_code_belongs_to_its_company(control):
    pc = joined(control, "acme")
    assert (pc["app"], pc["company"], pc["empty"]) == ("medtracker", "acme", True)


def test_join_code_single_use_and_expires(control):
    control.create_company("medtracker", "acme", NOW)
    code = control.make_code("medtracker", "acme", NOW)
    assert len(code) == 9 and code[4] == "-"
    control.join(code, "pc1", NOW)
    refused(404, BAD_CODE)(lambda: control.join(code, "pc2", NOW))
    late = control.make_code("medtracker", "acme", NOW)
    refused(404, BAD_CODE)(lambda: control.join(late, "pc2", NOW + timedelta(hours=25)))


def test_join_code_ignores_case_and_dash(control):
    control.create_company("medtracker", "acme", NOW)
    code = control.make_code("medtracker", "acme", NOW)
    assert control.join(code.replace("-", "").lower(), "pc1", NOW)["device"]


def test_later_join_is_not_empty(control):
    pc = joined(control, "acme")
    control.core_for(pc["token"], "medtracker", "acme", NOW).push(pc["device"], [medicine()])
    assert joined(control, "acme", "pc2")["empty"] is False


def test_token_hash_only_stored(control):
    pc = joined(control)
    assert pc["token"] not in repr(vars(control.store))
    assert control.core_for(pc["token"], "medtracker", "acme", NOW) is control.databases["medtracker__acme"]


# --- keys only work for their own company ------------------------------------------

def test_unknown_key_refused(control):
    refused(401)(lambda: control.core_for("nope", "medtracker", "acme", NOW))


def test_key_only_works_for_its_company(control):
    pc = joined(control, "acme")
    control.create_company("medtracker", "beta", NOW)
    for app, company in (("medtracker", "beta"), ("medtracker", "no-such-co"), ("other", "acme")):
        refused(403, NOT_ALLOWED)(lambda: control.core_for(pc["token"], app, company, NOW))


def test_pushes_land_in_own_company(control):
    a, b = joined(control, "acme"), joined(control, "beta")
    stocked(control.core_for(a["token"], "medtracker", "acme", NOW), a["device"])
    assert control.databases["medtracker__beta"].snapshot()["rows"]["medicines"] == []
    assert len(control.databases["medtracker__acme"].snapshot()["rows"]["medicines"]) == 1
    assert b["company"] == "beta"


def test_revoke_and_disabled(control):
    pc = joined(control, "acme", "front-desk")
    control.revoke("medtracker", "acme", "front-desk")
    refused(403, REVOKED)(lambda: control.core_for(pc["token"], "medtracker", "acme", NOW))
    assert [c["revoked"] for c in control.computers("medtracker", "acme")] == [True]
    refused(404)(lambda: control.revoke("medtracker", "acme", "nobody"))

    other = joined(control, "acme", "back-office")
    control.set_disabled("medtracker", "acme", True)
    refused(403)(lambda: control.core_for(other["token"], "medtracker", "acme", NOW))
    refused(403)(lambda: control.join(control.make_code("medtracker", "acme", NOW), "pc3", NOW))
    control.set_disabled("medtracker", "acme", False)
    assert control.core_for(other["token"], "medtracker", "acme", NOW)


def test_missing_database_503(control):
    pc = joined(control, "acme")
    del control.databases["medtracker__acme"]            # dropped behind the server's back
    refused(503, UNAVAILABLE)(lambda: control.core_for(pc["token"], "medtracker", "acme", NOW))
    assert "medtracker__acme" not in control.databases   # not re-created


# --- status page ---------------------------------------------------------------------

def test_status_lists_companies_with_counts(control):
    front = joined(control, "acme", "front-desk")
    back = joined(control, "acme", "back-office")
    core = control.core_for(front["token"], "medtracker", "acme", NOW)
    stocked(core, front["device"])
    core.push(back["device"], [medicine("Ibuprofen")])
    control.revoke("medtracker", "acme", "back-office")
    control.make_code("medtracker", "acme", NOW)
    control.create_company("medtracker", "beta", NOW)     # its first code is open too

    status = control.status(NOW)
    acme, beta = status["companies"]
    assert (acme["app"], acme["company"], beta["company"]) == ("medtracker", "acme", "beta")
    assert acme["last_seq"] == 4 and acme["changes_24h"] == 4
    assert acme["tables"]["medicines"] == 2 and acme["tables"]["users"] == 0
    assert acme["open_codes"] == 3 and beta["open_codes"] == 1   # each create_company hands out a code
    computers = {c["name"]: c for c in acme["computers"]}
    assert computers["front-desk"]["changes_total"] == 3 and not computers["front-desk"]["revoked"]
    assert computers["back-office"]["changes_24h"] == 1 and computers["back-office"]["revoked"]
    assert beta["computers"] == [] and beta["last_seq"] == 0


def test_status_marks_unavailable_company(control):
    control.create_company("medtracker", "acme", NOW)
    del control.databases["medtracker__acme"]
    (acme,) = control.status(NOW)["companies"]
    assert acme["error"] == UNAVAILABLE and acme["computers"] == []


def test_status_with_no_companies(control):
    assert control.status(NOW) == {"companies": []}
