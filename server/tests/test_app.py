"""The sync server over HTTP (sync_server/app.py), on the in-memory stores."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from sync_schema import FORMAT, REVOKED, TOO_OLD
from sync_server.app import create_app
from sync_server.control import NOT_ALLOWED
from sync_server.core import SyncError
from sync_server.store_memory import memory_control
from test_core import medicine

HEADERS = {"X-MedTracker-Format": str(FORMAT)}
ADMIN = {"Authorization": "Bearer admin-key-123"}
BASE = "/v1/medtracker/acme"


@pytest.fixture
def server():
    control = memory_control()
    return control, TestClient(create_app(control, status_password="s3cret", admin_key="admin-key-123"))


def create(client, company="acme"):
    reply = client.put(f"/v1/admin/medtracker/{company}", headers=ADMIN)
    assert reply.status_code == 200
    return reply.json()


def joined(server, company="acme", name="pc1"):
    _, client = server
    reply = client.post("/v1/join", json={"code": create(client, company)["code"], "computer": name},
                        headers=HEADERS)
    assert reply.status_code == 200
    return reply.json()


def auth(token):
    return dict(HEADERS, Authorization=f"Bearer {token}")


def test_health(server):
    assert server[1].get("/v1/health").json() == {"ok": True}


# --- admin -----------------------------------------------------------------------

def test_admin_create_needs_key(server):
    _, client = server
    assert client.put("/v1/admin/medtracker/acme").status_code == 401
    assert client.put("/v1/admin/medtracker/acme", headers={"Authorization": "Bearer nope"}).status_code == 401
    assert server[0].companies() == []
    no_admin = TestClient(create_app(memory_control()))
    assert no_admin.put("/v1/admin/medtracker/acme", headers=ADMIN).status_code == 404


def test_admin_create_twice(server):
    _, client = server
    first, again = create(client), create(client)
    assert (first["created"], again["created"]) == (True, False)
    assert len(first["code"]) == 9
    assert client.put("/v1/admin/nope/acme", headers=ADMIN).status_code == 404
    assert client.put("/v1/admin/medtracker/Bad_Name", headers=ADMIN).status_code == 404


def test_admin_codes_computers_revoke(server):
    _, client = server
    pc = joined(server, name="front-desk")
    assert len(client.post("/v1/admin/medtracker/acme/codes", headers=ADMIN).json()["code"]) == 9
    computers = client.get("/v1/admin/medtracker/acme/computers", headers=ADMIN).json()["computers"]
    assert [c["name"] for c in computers] == ["front-desk"]
    reply = client.post("/v1/admin/medtracker/acme/revoke", json={"computer": "front-desk"}, headers=ADMIN)
    assert reply.status_code == 200
    assert client.get(f"{BASE}/snapshot", headers=auth(pc["token"])).json() == {"message": REVOKED}
    assert client.get("/v1/admin/medtracker/other/computers", headers=ADMIN).status_code == 404


# --- computers -------------------------------------------------------------------

def test_admin_create_then_join_push_pull(server):
    _, client = server
    pc = joined(server)
    assert (pc["app"], pc["company"], pc["empty"]) == ("medtracker", "acme", True)
    m = medicine()
    pushed = client.post(f"{BASE}/changes", json={"changes": [m]}, headers=auth(pc["token"]))
    assert pushed.json() == {"seq": 1, "rejected": []}
    pulled = client.get(f"{BASE}/changes", params={"after": 0}, headers=auth(pc["token"])).json()
    assert [c["change_uid"] for c in pulled["changes"]] == [m["change_uid"]]
    snap = client.get(f"{BASE}/snapshot", headers=auth(pc["token"])).json()
    assert snap["seq"] == 1 and snap["rows"]["medicines"][0]["name"] == "Paracetamol"


def test_key_refused_for_other_company(server):
    _, client = server
    pc = joined(server, "acme")
    create(client, "beta")
    for path in ("/v1/medtracker/beta/snapshot", "/v1/medtracker/no-such-co/snapshot", "/v1/nope/acme/snapshot"):
        reply = client.get(path, headers=auth(pc["token"]))
        assert (reply.status_code, reply.json()) == (403, {"message": NOT_ALLOWED})


def test_bad_join_code_404_with_message(server):
    reply = server[1].post("/v1/join", json={"code": "AAAA-AAAA", "computer": "pc"}, headers=HEADERS)
    assert reply.status_code == 404
    assert reply.json() == {"message": "That join code is not valid or has expired."}


def test_missing_token_401(server):
    assert server[1].get(f"{BASE}/changes", params={"after": 0}, headers=HEADERS).status_code == 401


def test_old_format_426_too_old(server):
    pc = joined(server)
    reply = server[1].get(f"{BASE}/snapshot", headers=dict(auth(pc["token"]), **{"X-MedTracker-Format": "0"}))
    assert reply.status_code == 426 and reply.json() == {"message": TOO_OLD}
    assert server[1].get(f"{BASE}/snapshot", headers={"Authorization": f"Bearer {pc['token']}"}).status_code == 426


def test_invalid_change_400(server):
    pc = joined(server)
    bad = medicine()
    bad["data"]["reorder_level"] = -1
    reply = server[1].post(f"{BASE}/changes", json={"changes": [bad]}, headers=auth(pc["token"]))
    assert reply.status_code == 400 and "below zero" in reply.json()["message"]


def test_malformed_body_400(server):
    pc = joined(server)
    reply = server[1].post(f"{BASE}/changes", json={"nope": 1}, headers=auth(pc["token"]))
    assert reply.status_code == 400 and reply.json()["message"]


def test_huge_body_413(server):
    pc = joined(server)
    reply = server[1].post(f"{BASE}/changes", content=b"x" * (20 * 1024 * 1024 + 1),
                           headers=dict(auth(pc["token"]), **{"Content-Type": "application/json"}))
    assert reply.status_code == 413


def test_missing_company_database_503(server):
    control, client = server
    pc = joined(server)
    del control.databases["medtracker__acme"]
    reply = client.get(f"{BASE}/snapshot", headers=auth(pc["token"]))
    assert reply.status_code == 503 and reply.json()["message"] == "The company's data is not available right now."


# --- the admin command -----------------------------------------------------------

def test_admin_cli_create_codes_computers_revoke():
    from sync_server import admin
    control = memory_control()
    when = datetime(2026, 11, 26, 9, 0)
    out = admin.run(control, ["create", "medtracker", "acme"], when)
    assert out.startswith("Created medtracker/acme (database medtracker__acme).\nJoin code: ")
    assert admin.run(control, ["create", "medtracker", "acme"], when).startswith("medtracker/acme already exists.")
    code = admin.run(control, ["make-code", "medtracker", "acme"], when).split()[2]
    assert admin.run(control, ["computers", "medtracker", "acme"]) == "No computers have joined yet."
    control.join(code, "front-desk", when)
    assert admin.run(control, ["computers", "medtracker", "acme"]).startswith("front-desk")
    assert admin.run(control, ["companies"]).startswith("medtracker/acme")
    assert admin.run(control, ["revoke", "medtracker", "acme", "front-desk"]) == "'front-desk' can no longer sync."
    assert admin.run(control, ["computers", "medtracker", "acme"]).endswith("REVOKED")
    with pytest.raises(SyncError):
        admin.run(control, ["revoke", "medtracker", "acme", "nobody"])


# --- /status ---------------------------------------------------------------------

def test_status_off_without_a_password():
    assert TestClient(create_app(memory_control())).get("/status").status_code == 404


def test_status_needs_the_password(server):
    _, client = server
    reply = client.get("/status")
    assert reply.status_code == 401 and reply.headers["WWW-Authenticate"].startswith("Basic")
    assert client.get("/status", auth=("admin", "wrong")).status_code == 401


def test_status_page_lists_companies_escaped(server):
    _, client = server
    joined(server, "acme", "<b>front</b>")
    create(client, "beta")
    reply = client.get("/status", auth=("admin", "s3cret"))
    assert reply.status_code == 200 and reply.headers["content-type"].startswith("text/html")
    assert "&lt;b&gt;front&lt;/b&gt;" in reply.text and "<b>front</b>" not in reply.text
    assert "medtracker/acme" in reply.text and "medtracker/beta" in reply.text and "medicines" in reply.text


def test_status_page_shows_unavailable_company(server):
    control, client = server
    create(client, "acme")
    del control.databases["medtracker__acme"]
    reply = client.get("/status", auth=("admin", "s3cret"))
    assert reply.status_code == 200 and "not available" in reply.text


def test_status_page_when_the_database_fails(server):
    control, client = server
    control.status = lambda now: (_ for _ in ()).throw(RuntimeError("connection refused"))
    reply = client.get("/status", auth=("admin", "s3cret"))
    assert reply.status_code == 503 and "not reachable" in reply.text
