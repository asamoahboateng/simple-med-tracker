"""
s3client.py - Uploading, downloading and listing files on an S3-compatible server (MinIO).

Pure Python (no Qt, no extra packages) so it can be tested like updater.py. Requests are
signed with AWS Signature Version 4, which MinIO understands, and sent with urllib.
Error messages never contain the keys and are safe to show to the user.
"""

import hashlib
import hmac
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from urllib.parse import quote, unquote, urlencode, urlparse

import config

USER_AGENT = f"{config.APP_NAME}/{config.APP_VERSION} (cloud backup)"
S3_NS = "{http://s3.amazonaws.com/doc/2006-03-01/}"
LOCAL_HOSTS = ("127.0.0.1", "localhost")


class S3Error(Exception):
    """Something went wrong talking to the backup server; the message is safe to show."""


@dataclass
class S3Config:
    endpoint: str          # e.g. https://s3.kalourmade.com
    bucket: str
    access_key: str
    secret_key: str
    region: str = "us-east-1"


@dataclass
class ObjectInfo:
    key: str
    size: int
    modified: datetime


# --------------------------------------------------------------------------
# Signing (AWS Signature Version 4)
# --------------------------------------------------------------------------

def _hmac(key: bytes, text: str) -> bytes:
    return hmac.new(key, text.encode(), hashlib.sha256).digest()


def _canonical_path(path: str) -> str:
    """The URL path encoded exactly once (it may arrive already encoded)."""
    return quote(unquote(path or "/"), safe="/-_.~")


def _canonical_query(query: str) -> str:
    """Query parameters sorted and encoded exactly once (they may arrive already encoded)."""
    pairs = sorted((quote(unquote(k), safe="-_.~"), quote(unquote(v), safe="-_.~"))
                   for k, _, v in (p.partition("=") for p in query.split("&") if p))
    return "&".join(f"{k}={v}" for k, v in pairs)


def sign(method: str, url: str, headers: dict[str, str], payload_hash: str, cfg: S3Config,
         when: datetime) -> dict[str, str]:
    """`headers` plus the x-amz-date, x-amz-content-sha256 and Authorization headers."""
    parts = urlparse(url)
    stamp = when.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    day = stamp[:8]
    signed = dict(headers)
    signed["x-amz-date"] = stamp
    signed["x-amz-content-sha256"] = payload_hash

    canonical_headers = {"host": parts.netloc}
    canonical_headers.update({k.lower(): " ".join(str(v).split()) for k, v in signed.items()})
    names = sorted(canonical_headers)
    canonical = "\n".join([
        method,
        _canonical_path(parts.path),
        _canonical_query(parts.query),
        "".join(f"{n}:{canonical_headers[n]}\n" for n in names),
        ";".join(names),
        payload_hash,
    ])
    scope = f"{day}/{cfg.region}/s3/aws4_request"
    to_sign = "\n".join(["AWS4-HMAC-SHA256", stamp, scope,
                         hashlib.sha256(canonical.encode()).hexdigest()])
    key = _hmac(_hmac(_hmac(_hmac(f"AWS4{cfg.secret_key}".encode(), day), cfg.region), "s3"),
                "aws4_request")
    signature = hmac.new(key, to_sign.encode(), hashlib.sha256).hexdigest()
    signed["Authorization"] = (f"AWS4-HMAC-SHA256 Credential={cfg.access_key}/{scope}, "
                               f"SignedHeaders={';'.join(names)}, Signature={signature}")
    return signed


# --------------------------------------------------------------------------
# Requests
# --------------------------------------------------------------------------

def _url(cfg: S3Config, key: str = "", query: dict | None = None) -> str:
    endpoint = cfg.endpoint.rstrip("/")
    parts = urlparse(endpoint)
    if parts.scheme != "https" and not (parts.scheme == "http" and parts.hostname in LOCAL_HOSTS):
        raise S3Error("The backup server address must start with https://")
    path = f"/{cfg.bucket}/{key}" if key else f"/{cfg.bucket}"
    url = endpoint + quote(path, safe="/-_.~")
    if query:
        url += "?" + urlencode(sorted(query.items()), quote_via=quote, safe="-_.~")
    return url


def _error_message(cfg: S3Config, status: int, body: bytes) -> str:
    try:
        code = ET.fromstring(body).findtext("Code") or ""
    except ET.ParseError:
        code = ""
    if code == "NoSuchBucket":
        return f"The bucket '{cfg.bucket}' does not exist."
    if code == "NoSuchKey":
        return "That backup is no longer on the server."
    if status in (401, 403):
        return "The backup server refused access. Check the MedTracker version or ask for support."
    return f"The backup server had a problem ({code or status}). Try again later."


def _request(cfg: S3Config, method: str, key: str = "", query: dict | None = None,
             data: bytes = b"", timeout: float = 30) -> bytes:
    url = _url(cfg, key, query)
    headers = sign(method, url, {"User-Agent": USER_AGENT}, hashlib.sha256(data).hexdigest(),
                   cfg, datetime.now(timezone.utc))
    request = urllib.request.Request(url, data=data if method == "PUT" else None,
                                     headers=headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.read()
    except urllib.error.HTTPError as exc:
        raise S3Error(_error_message(cfg, exc.code, exc.read())) from None
    except (urllib.error.URLError, OSError):
        raise S3Error("Cannot reach the backup server. Check the internet connection.") from None


def put_object(cfg: S3Config, key: str, data: bytes, timeout: float = 30) -> None:
    _request(cfg, "PUT", key, data=data, timeout=timeout)


def get_object(cfg: S3Config, key: str, timeout: float = 30) -> bytes:
    return _request(cfg, "GET", key, timeout=timeout)


def list_objects(cfg: S3Config, prefix: str, timeout: float = 30) -> list[ObjectInfo]:
    """Every object whose key starts with `prefix` (all pages)."""
    found, token = [], None
    while True:
        query = {"list-type": "2", "prefix": prefix}
        if token:
            query["continuation-token"] = token
        body = _request(cfg, "GET", query=query, timeout=timeout)
        try:
            root = ET.fromstring(body)
        except ET.ParseError:
            raise S3Error("The backup server sent an unexpected answer.") from None
        for item in root.iter(f"{S3_NS}Contents"):
            modified = item.findtext(f"{S3_NS}LastModified", "").replace("Z", "+00:00")
            found.append(ObjectInfo(item.findtext(f"{S3_NS}Key", ""),
                                    int(item.findtext(f"{S3_NS}Size", "0")),
                                    datetime.fromisoformat(modified)))
        token = root.findtext(f"{S3_NS}NextContinuationToken")
        if root.findtext(f"{S3_NS}IsTruncated") != "true" or not token:
            return found
