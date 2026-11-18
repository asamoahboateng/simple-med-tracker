"""
updater.py - Checking for, downloading and starting MedTracker updates.

Pure Python (no Qt) so it can be tested like logic.py. The window code in
ui/update_bar.py and ui/main_window.py calls these functions from a background thread.

How it works: every release publishes `latest.json` (see scripts/make_manifest.py) next to
the Windows installer. The app reads that file, and if it names a newer version it
downloads the installer, checks its size and SHA-256, and runs it silently.
"""

import hashlib
import json
import re
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlparse

import config

USER_AGENT = f"{config.APP_NAME}/{config.APP_VERSION} (updater)"
CHUNK = 64 * 1024
REQUIRED_FIELDS = ("version", "url", "sha256", "size")


class UpdateError(Exception):
    """Something went wrong with an update; the message is safe to show to the user."""


# --------------------------------------------------------------------------
# Versions
# --------------------------------------------------------------------------

def parse_version(text) -> tuple[int, ...]:
    """'1.2.0' or 'v1.2.0' -> (1, 2, 0)."""
    value = str(text).strip()
    if value[:1] in ("v", "V"):
        value = value[1:]
    if not re.fullmatch(r"\d+(\.\d+){1,3}", value):
        raise UpdateError(f"'{text}' is not a valid version number.")
    return tuple(int(part) for part in value.split("."))


def _pad(version: tuple[int, ...]) -> tuple[int, ...]:
    return version + (0,) * (4 - len(version))


def is_newer(candidate, current) -> bool:
    return _pad(parse_version(candidate)) > _pad(parse_version(current))


# --------------------------------------------------------------------------
# The manifest (latest.json)
# --------------------------------------------------------------------------

@dataclass
class Manifest:
    version: str
    url: str
    sha256: str
    size: int
    released: str = ""
    min_version: str = "0.0.0"
    notes: str = ""

    @property
    def filename(self) -> str:
        """File name of the installer (last part of the URL)."""
        return PurePosixPath(unquote(urlparse(self.url).path)).name


def _host(url: str) -> str:
    return (urlparse(url).hostname or "").lower()


def _check_host(url: str, allowed_hosts) -> None:
    if _host(url) not in {h.lower() for h in allowed_hosts}:
        raise UpdateError("The update is not hosted on an approved web site, so it was not used.")


def parse_manifest(data, allowed_hosts=config.UPDATE_ALLOWED_HOSTS) -> Manifest:
    """Validate the decoded latest.json and turn it into a Manifest."""
    if not isinstance(data, dict):
        raise UpdateError("The update information is not in the expected format.")
    missing = [key for key in REQUIRED_FIELDS if data.get(key) in (None, "")]
    if missing:
        raise UpdateError(f"The update information is incomplete (missing: {', '.join(missing)}).")
    version = str(data["version"]).strip().lstrip("vV")
    parse_version(version)
    url = str(data["url"]).strip()
    # https only (plain http is accepted just for this computer itself, used by the tests)
    if urlparse(url).scheme != "https" and _host(url) not in ("127.0.0.1", "localhost"):
        raise UpdateError("The update must be downloaded over a secure (https) link.")
    _check_host(url, allowed_hosts)
    sha256 = str(data["sha256"]).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", sha256):
        raise UpdateError("The update's checksum is not valid.")
    size = data["size"]
    if isinstance(size, bool) or not isinstance(size, int) or size <= 0:
        raise UpdateError("The update's file size is not valid.")
    min_version = str(data.get("min_version") or "0.0.0").strip().lstrip("vV")
    parse_version(min_version)
    manifest = Manifest(version=version, url=url, sha256=sha256, size=size,
                        released=str(data.get("released") or ""), min_version=min_version,
                        notes=str(data.get("notes") or ""))
    name = manifest.filename
    if not name or "\\" in name or name in (".", ".."):
        raise UpdateError("The update's file name is not valid.")
    return manifest


def _open(url: str, timeout: float, allowed_hosts):
    """Open `url` and make sure we ended up on an approved host after redirects."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        response = urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        raise UpdateError(f"The update server answered with an error ({exc.code}).") from exc
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise UpdateError("Could not reach the update server. Check the internet connection.") from exc
    try:
        _check_host(response.geturl(), allowed_hosts)
    except UpdateError:
        response.close()
        raise
    return response


def fetch_manifest(url=config.UPDATE_MANIFEST_URL, timeout=10,
                   allowed_hosts=config.UPDATE_ALLOWED_HOSTS) -> Manifest:
    response = _open(url, timeout, allowed_hosts)
    try:
        raw = response.read(1_000_000)      # the manifest is tiny
    except OSError as exc:
        raise UpdateError("Could not read the update information.") from exc
    finally:
        response.close()
    try:
        data = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as exc:
        raise UpdateError("The update information could not be read.") from exc
    return parse_manifest(data, allowed_hosts)


def check_for_update(current_version=config.APP_VERSION, url=config.UPDATE_MANIFEST_URL,
                     timeout=10, allowed_hosts=config.UPDATE_ALLOWED_HOSTS):
    """The Manifest of a newer version, or None when this version is up to date."""
    manifest = fetch_manifest(url, timeout, allowed_hosts)
    return manifest if is_newer(manifest.version, current_version) else None


def needs_manual_install(manifest: Manifest, current_version=config.APP_VERSION) -> bool:
    """True when this version is too old to update itself (e.g. the single-file 1.1.x)."""
    return is_newer(manifest.min_version, current_version)


# --------------------------------------------------------------------------
# Downloading and verifying
# --------------------------------------------------------------------------

def verify_file(path, sha256: str, size: int) -> None:
    """Raise UpdateError unless the file has exactly this size and SHA-256."""
    path = Path(path)
    try:
        if path.stat().st_size != size:
            raise UpdateError("The update file has the wrong size. It was not used.")
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for chunk in iter(lambda: handle.read(CHUNK), b""):
                digest.update(chunk)
    except OSError as exc:
        raise UpdateError(f"The update file could not be read: {exc}") from exc
    if digest.hexdigest() != sha256.lower():
        raise UpdateError("The update file is damaged (checksum mismatch). It was not used.")


def download(manifest: Manifest, dest_dir, progress=None, cancelled=None,
             timeout=30, allowed_hosts=config.UPDATE_ALLOWED_HOSTS) -> Path:
    """
    Download and verify the installer into `dest_dir`; returns its path.
    progress(done, total) is called after each chunk; cancelled() -> True stops the download.
    """
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    final = dest_dir / manifest.filename
    part = final.with_name(final.name + ".part")
    response = _open(manifest.url, timeout, allowed_hosts)
    try:
        try:
            with response, open(part, "wb") as out:
                done = 0
                while True:
                    if cancelled is not None and cancelled():
                        raise UpdateError("Download cancelled.")
                    chunk = response.read(CHUNK)
                    if not chunk:
                        break
                    out.write(chunk)
                    done += len(chunk)
                    if progress is not None:
                        progress(done, manifest.size)
            verify_file(part, manifest.sha256, manifest.size)
        except OSError as exc:
            raise UpdateError(f"The download failed: {exc}") from exc
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    final.unlink(missing_ok=True)
    part.replace(final)
    return final


def manifest_from_folder(folder_or_json, allowed_hosts=config.UPDATE_ALLOWED_HOSTS):
    """
    For updating a PC without internet: `latest.json` plus the installer copied next to it
    (for example on a USB stick). Returns (Manifest, installer_path), already verified.
    """
    path = Path(folder_or_json)
    json_path = path / "latest.json" if path.is_dir() else path
    try:
        data = json.loads(json_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise UpdateError(f"Could not read {json_path.name}. Choose the latest.json file.") from exc
    manifest = parse_manifest(data, allowed_hosts)
    installer = json_path.parent / manifest.filename
    if not installer.is_file():
        raise UpdateError(f"The installer {manifest.filename} must be in the same folder as "
                          f"{json_path.name}.")
    verify_file(installer, manifest.sha256, manifest.size)
    return manifest, installer


# --------------------------------------------------------------------------
# Running the installer
# --------------------------------------------------------------------------

def can_self_install() -> bool:
    """Only the installed Windows program updates itself; others open the download page."""
    return sys.platform == "win32" and bool(getattr(sys, "frozen", False))


def installer_command(installer_path) -> list[str]:
    """Inno Setup options: no windows, close MedTracker if needed, never reboot."""
    return [str(installer_path), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS",
            "/NORESTART"]


def run_installer(installer_path) -> None:
    """Start the installer and return at once (the caller then quits the app)."""
    if sys.platform != "win32":
        raise UpdateError("Updates can only be installed automatically on Windows.")
    flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    try:
        subprocess.Popen(installer_command(installer_path), creationflags=flags,
                         close_fds=True)
    except OSError as exc:
        raise UpdateError(f"The installer could not be started: {exc}") from exc


def updates_dir() -> Path:
    """Local folder for downloaded installers."""
    return config.updates_dir()
