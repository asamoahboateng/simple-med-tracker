"""Update checking, downloading and verifying (updater.py) and scripts/make_manifest.py."""

import hashlib
import http.server
import json
import subprocess
import sys
import threading
from pathlib import Path

import pytest

import config
import updater

ROOT = Path(__file__).resolve().parent.parent
PAYLOAD = b"MedTracker installer " * 5000
SHA = hashlib.sha256(PAYLOAD).hexdigest()


def manifest_data(**changes):
    data = {"version": "1.2.0", "released": "2026-07-01", "sha256": SHA, "size": len(PAYLOAD),
            "url": "https://github.com/asamoahboateng/simple-med-tracker/releases/download/"
                   "v1.2.0/MedTracker-Setup-1.2.0.exe",
            "min_version": "1.2.0", "notes": "Auto updates"}
    data.update(changes)
    return {k: v for k, v in data.items() if v is not None}


# --- versions ------------------------------------------------------------------

def test_parse_version():
    assert updater.parse_version("1.2.0") == (1, 2, 0)
    assert updater.parse_version("v1.10.3") == (1, 10, 3)


@pytest.mark.parametrize("junk", ["", "abc", "1..2", "1.2.x", "1"])
def test_parse_version_rejects_junk(junk):
    with pytest.raises(updater.UpdateError):
        updater.parse_version(junk)


def test_is_newer():
    assert updater.is_newer("1.10.0", "1.9.9")
    assert updater.is_newer("v1.1.3", "1.1.2")
    assert not updater.is_newer("1.1.2", "1.1.2")
    assert not updater.is_newer("1.1.1", "1.1.2")


# --- manifest ------------------------------------------------------------------

def test_parse_manifest_ok():
    m = updater.parse_manifest(manifest_data(sha256=SHA.upper()))
    assert (m.version, m.sha256, m.size, m.min_version) == ("1.2.0", SHA, len(PAYLOAD), "1.2.0")
    assert m.filename == "MedTracker-Setup-1.2.0.exe"


def test_min_version_is_optional():
    assert updater.parse_manifest(manifest_data(min_version=None)).min_version == "0.0.0"


@pytest.mark.parametrize("field", ["version", "url", "sha256", "size"])
def test_manifest_missing_field(field):
    with pytest.raises(updater.UpdateError, match="incomplete"):
        updater.parse_manifest(manifest_data(**{field: None}))


@pytest.mark.parametrize("changes", [
    {"url": "http://github.com/x/MedTracker-Setup.exe"},
    {"url": "https://evil.example.com/MedTracker-Setup.exe"},
    {"sha256": "abc123"},
    {"sha256": "z" * 64},
    {"size": 0},
    {"size": "100"},
    {"version": "latest"},
    {"min_version": "soon"},
])
def test_manifest_rejected(changes):
    with pytest.raises(updater.UpdateError):
        updater.parse_manifest(manifest_data(**changes))


def test_manifest_not_a_dict():
    with pytest.raises(updater.UpdateError):
        updater.parse_manifest(["nope"])


def test_needs_manual_install():
    m = updater.parse_manifest(manifest_data())
    assert updater.needs_manual_install(m, "1.1.2")
    assert not updater.needs_manual_install(m, "1.2.0")
    assert not updater.needs_manual_install(m, "1.3.0")


# --- a small local web server for the network tests ---------------------------------

@pytest.fixture
def server(tmp_path):
    """Serves PAYLOAD at /MedTracker-Setup-1.2.0.exe and a manifest at /latest.json."""
    state = {"manifest": None, "slow": False}

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            if self.path == "/latest.json":
                body = json.dumps(state["manifest"]).encode()
            else:
                body = PAYLOAD
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{httpd.server_port}"
    state["base"] = base
    state["manifest"] = manifest_data(url=f"{base}/MedTracker-Setup-1.2.0.exe")
    yield state
    httpd.shutdown()
    httpd.server_close()


HOSTS = ("127.0.0.1",)


def local_manifest(server, **changes):
    return updater.parse_manifest(dict(server["manifest"], **changes), allowed_hosts=HOSTS)


def test_fetch_manifest_and_check_for_update(server):
    url = server["base"] + "/latest.json"
    assert updater.fetch_manifest(url, allowed_hosts=HOSTS).version == "1.2.0"
    assert updater.check_for_update("1.1.2", url, allowed_hosts=HOSTS).version == "1.2.0"
    assert updater.check_for_update("1.2.0", url, allowed_hosts=HOSTS) is None


def test_fetch_manifest_wrong_host(server):
    with pytest.raises(updater.UpdateError):
        updater.fetch_manifest(server["base"] + "/latest.json")      # 127.0.0.1 not allowed


def test_download_success(server, tmp_path):
    calls = []
    path = updater.download(local_manifest(server), tmp_path / "dl",
                            progress=lambda done, total: calls.append((done, total)),
                            allowed_hosts=HOSTS)
    assert path.name == "MedTracker-Setup-1.2.0.exe"
    assert path.read_bytes() == PAYLOAD
    assert calls and calls[-1] == (len(PAYLOAD), len(PAYLOAD))
    assert not list((tmp_path / "dl").glob("*.part"))


def test_download_checksum_mismatch(server, tmp_path):
    with pytest.raises(updater.UpdateError, match="damaged"):
        updater.download(local_manifest(server, sha256="0" * 64), tmp_path, allowed_hosts=HOSTS)
    assert list(tmp_path.iterdir()) == []


def test_download_size_mismatch(server, tmp_path):
    with pytest.raises(updater.UpdateError, match="size"):
        updater.download(local_manifest(server, size=len(PAYLOAD) + 1), tmp_path,
                         allowed_hosts=HOSTS)
    assert list(tmp_path.iterdir()) == []


def test_download_cancel_deletes_part(server, tmp_path):
    seen = []
    with pytest.raises(updater.UpdateError, match="cancelled"):
        updater.download(local_manifest(server), tmp_path,
                         progress=lambda d, t: seen.append(d),
                         cancelled=lambda: len(seen) >= 1, allowed_hosts=HOSTS)
    assert list(tmp_path.iterdir()) == []


def test_download_unreachable(tmp_path):
    m = updater.parse_manifest(manifest_data(url="https://127.0.0.1:1/x.exe"),
                               allowed_hosts=HOSTS)
    with pytest.raises(updater.UpdateError):
        updater.download(m, tmp_path, timeout=2, allowed_hosts=HOSTS)


def test_download_replaces_older_file(server, tmp_path):
    (tmp_path / "MedTracker-Setup-1.2.0.exe").write_bytes(b"old")
    path = updater.download(local_manifest(server), tmp_path, allowed_hosts=HOSTS)
    assert path.read_bytes() == PAYLOAD


# --- installing from a folder -------------------------------------------------------

def test_manifest_from_folder_ok(tmp_path):
    (tmp_path / "MedTracker-Setup-1.2.0.exe").write_bytes(PAYLOAD)
    (tmp_path / "latest.json").write_text(json.dumps(manifest_data()))
    for given in (tmp_path / "latest.json", tmp_path):
        m, installer = updater.manifest_from_folder(given)
        assert m.version == "1.2.0" and installer == tmp_path / "MedTracker-Setup-1.2.0.exe"


def test_manifest_from_folder_missing_installer(tmp_path):
    (tmp_path / "latest.json").write_text(json.dumps(manifest_data()))
    with pytest.raises(updater.UpdateError, match="same folder"):
        updater.manifest_from_folder(tmp_path / "latest.json")


def test_manifest_from_folder_bad_installer(tmp_path):
    (tmp_path / "MedTracker-Setup-1.2.0.exe").write_bytes(PAYLOAD + b"x")
    (tmp_path / "latest.json").write_text(json.dumps(manifest_data()))
    with pytest.raises(updater.UpdateError):
        updater.manifest_from_folder(tmp_path / "latest.json")


def test_manifest_from_folder_bad_json(tmp_path):
    (tmp_path / "latest.json").write_text("{not json")
    with pytest.raises(updater.UpdateError):
        updater.manifest_from_folder(tmp_path / "latest.json")
    with pytest.raises(updater.UpdateError):
        updater.manifest_from_folder(tmp_path / "missing.json")


# --- running the installer ---------------------------------------------------------------

def test_installer_command():
    cmd = updater.installer_command(Path("C:/x/Setup.exe"))
    assert cmd[0].endswith("Setup.exe")
    assert cmd[1:] == ["/VERYSILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/NORESTART"]


def test_run_installer_refuses_off_windows(monkeypatch):
    monkeypatch.setattr(sys, "platform", "darwin")
    with pytest.raises(updater.UpdateError):
        updater.run_installer("Setup.exe")


def test_can_self_install(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert updater.can_self_install()
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    assert not updater.can_self_install()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "platform", "linux")
    assert not updater.can_self_install()


def test_updates_dir_is_local(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "user_data_dir", lambda *a, **k: str(tmp_path / "MedTracker"))
    assert updater.updates_dir() == tmp_path / "MedTracker" / "updates"


# --- scripts/make_manifest.py -----------------------------------------------------------

def test_make_manifest_script(tmp_path):
    installer = tmp_path / "MedTracker-Setup-1.2.0.exe"
    installer.write_bytes(PAYLOAD)
    out = tmp_path / "latest.json"
    notes = tmp_path / "notes.txt"
    notes.write_text("Fixes and auto-update\n")
    subprocess.run([sys.executable, str(ROOT / "scripts" / "make_manifest.py"),
                    "--installer", str(installer), "--version", "v1.2.0",
                    "--url-base", "https://github.com/asamoahboateng/simple-med-tracker/releases/download/v1.2.0/",
                    "--notes-file", str(notes), "--out", str(out)], check=True,
                   capture_output=True)
    data = json.loads(out.read_text())
    assert (data["version"], data["sha256"], data["size"], data["min_version"]) == (
        "1.2.0", SHA, len(PAYLOAD), "1.2.0")
    assert data["url"].endswith("/v1.2.0/MedTracker-Setup-1.2.0.exe")
    assert data["notes"] == "Fixes and auto-update"
    assert len(data["released"]) == 10
    updater.parse_manifest(data)        # the app accepts what the script writes
