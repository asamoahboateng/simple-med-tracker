"""The sync server over HTTP (sync_server/app.py), on the in-memory store."""

from datetime import datetime

import pytest
from fastapi.testclient import TestClient

from sync_schema import FORMAT, REVOKED, TOO_OLD
from sync_server.app import create_app
from sync_server.core import Core, SyncError
from sync_server.store_memory import MemoryStore
from test_core import medicine

HEADERS = {"X-MedTracker-Format": str(FORMAT)}


@pytest.fixture
def server():
    core = Core(MemoryStore())
    return core, TestClient(create_app(core))


def joined(server, name="pc1"):
    core, client = server
    reply = client.post("/v1/join", json={"code": core.make_code(datetime.now()), "computer": name},
                        headers=HEADERS)
    assert reply.status_code == 200
    return reply.json()


def auth(token):
    return dict(HEADERS, Authorization=f"Bearer {token}")


def test_health(server):
    assert server[1].get("/v1/health").json() == {"ok": True}


def test_join_then_push_and_pull(server):
    _, client = server
    pc = joined(server)
    assert pc["empty"] is True
    m = medicine()
    pushed = client.post("/v1/changes", json={"changes": [m]}, headers=auth(pc["token"]))
    assert pushed.json() == {"seq": 1, "rejected": []}
    pulled = client.get("/v1/changes", params={"after": 0}, headers=auth(pc["token"])).json()
    assert [c["change_uid"] for c in pulled["changes"]] == [m["change_uid"]]
    snap = client.get("/v1/snapshot", headers=auth(pc["token"])).json()
    assert snap["seq"] == 1 and snap["rows"]["medicines"][0]["name"] == "Paracetamol"


def test_bad_join_code_404_with_message(server):
    reply = server[1].post("/v1/join", json={"code": "AAAA-AAAA", "computer": "pc"}, headers=HEADERS)
    assert reply.status_code == 404
    assert reply.json() == {"message": "That join code is not valid or has expired."}


def test_missing_token_401_and_revoked_403_with_message(server):
    core, client = server
    assert client.get("/v1/changes", params={"after": 0}, headers=HEADERS).status_code == 401
    pc = joined(server, "front-desk")
    core.revoke("front-desk")
    reply = client.get("/v1/changes", params={"after": 0}, headers=auth(pc["token"]))
    assert reply.status_code == 403 and reply.json() == {"message": REVOKED}


def test_old_format_426_too_old(server):
    pc = joined(server)
    reply = server[1].get("/v1/snapshot", headers=dict(auth(pc["token"]), **{"X-MedTracker-Format": "0"}))
    assert reply.status_code == 426 and reply.json() == {"message": TOO_OLD}
    assert server[1].get("/v1/snapshot", headers={"Authorization": f"Bearer {pc['token']}"}).status_code == 426


def test_invalid_change_400(server):
    pc = joined(server)
    bad = medicine()
    bad["data"]["reorder_level"] = -1
    reply = server[1].post("/v1/changes", json={"changes": [bad]}, headers=auth(pc["token"]))
    assert reply.status_code == 400 and "below zero" in reply.json()["message"]


def test_malformed_body_400(server):
    pc = joined(server)
    reply = server[1].post("/v1/changes", json={"nope": 1}, headers=auth(pc["token"]))
    assert reply.status_code == 400 and reply.json()["message"]


def test_huge_body_413(server):
    pc = joined(server)
    reply = server[1].post("/v1/changes", content=b"x" * (20 * 1024 * 1024 + 1),
                           headers=dict(auth(pc["token"]), **{"Content-Type": "application/json"}))
    assert reply.status_code == 413


# --- the admin command -----------------------------------------------------------

def test_admin_make_code_computers_and_revoke():
    from sync_server import admin
    core = Core(MemoryStore())
    out = admin.run(core, ["make-code"], datetime(2026, 11, 25, 9, 0))
    code = out.split()[2]
    assert out.startswith("Join code: ") and len(code) == 9
    assert admin.run(core, ["computers"]) == "No computers have joined yet."
    core.join(code, "front-desk", datetime(2026, 11, 25, 9, 5))
    assert admin.run(core, ["computers"]).startswith("front-desk")
    assert admin.run(core, ["revoke", "front-desk"]) == "'front-desk' can no longer sync."
    assert admin.run(core, ["computers"]).endswith("REVOKED")
    with pytest.raises(SyncError):
        admin.run(core, ["revoke", "nobody"])


# --- /status ---------------------------------------------------------------------

def status_client(password="s3cret"):
    core = Core(MemoryStore())
    return core, TestClient(create_app(core, status_password=password))


def test_status_off_without_a_password():
    _, client = status_client(password=None)
    assert client.get("/status").status_code == 404


def test_status_needs_the_password():
    _, client = status_client()
    reply = client.get("/status")
    assert reply.status_code == 401 and reply.headers["WWW-Authenticate"].startswith("Basic")
    assert client.get("/status", auth=("admin", "wrong")).status_code == 401


def test_status_page_shows_computers_escaped():
    core, client = status_client()
    core.join(core.make_code(datetime.now()), "<b>front</b>", datetime.now())
    reply = client.get("/status", auth=("admin", "s3cret"))
    assert reply.status_code == 200 and reply.headers["content-type"].startswith("text/html")
    assert "&lt;b&gt;front&lt;/b&gt;" in reply.text and "<b>front</b>" not in reply.text
    assert "Database" in reply.text and "medicines" in reply.text


def test_status_page_when_the_database_fails():
    core, client = status_client()
    core.status = lambda now: (_ for _ in ()).throw(RuntimeError("connection refused"))
    reply = client.get("/status", auth=("admin", "s3cret"))
    assert reply.status_code == 503 and "not reachable" in reply.text
