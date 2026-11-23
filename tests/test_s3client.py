"""Talking to MinIO over the S3 API (s3client.py), against a local fake server."""

import hashlib
from datetime import datetime, timezone

import pytest

from s3client import S3Config, S3Error, get_object, list_objects, put_object, sign


def test_sign_matches_aws_get_object_example():
    # AWS Signature V4 documentation, "Example: GET Object"
    cfg = S3Config("https://s3.amazonaws.com", "examplebucket",
                   "AKIAIOSFODNN7EXAMPLE", "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY")
    headers = sign("GET", "https://examplebucket.s3.amazonaws.com/test.txt", {"Range": "bytes=0-9"},
                   hashlib.sha256(b"").hexdigest(), cfg, datetime(2013, 5, 24, tzinfo=timezone.utc))
    assert headers["Authorization"].endswith(
        "Signature=f0e8bdb87c964420e857bd35b5d6ed310bd44f0170aba48dd91039c6036bdb41")
    assert "SignedHeaders=host;range;x-amz-content-sha256;x-amz-date" in headers["Authorization"]


def test_put_get_list_round_trip(fake_s3):
    put_object(fake_s3.cfg, "pc/a.enc", b"one")
    put_object(fake_s3.cfg, "pc/b.enc", b"two")
    assert get_object(fake_s3.cfg, "pc/b.enc") == b"two"
    assert [o.key for o in list_objects(fake_s3.cfg, "pc/")] == ["pc/a.enc", "pc/b.enc"]


def test_list_reports_size_and_time(fake_s3):
    put_object(fake_s3.cfg, "pc/a.enc", b"12345")
    info = list_objects(fake_s3.cfg, "")[0]
    assert info.size == 5 and info.modified == datetime(2026, 11, 23, 9, 0, tzinfo=timezone.utc)


def test_list_follows_continuation_token(fake_s3):
    for i in range(1001):
        fake_s3.store[f"s/{i:04}"] = b""
    assert len(list_objects(fake_s3.cfg, "s/")) == 1001


@pytest.mark.parametrize("status,code,message", [
    (403, "AccessDenied", "The backup server refused access. Check the MedTracker version or ask for support."),
    (404, "NoSuchBucket", "The bucket 'medtracker-inventory' does not exist."),
    (500, "InternalError", "The backup server had a problem (InternalError). Try again later."),
])
def test_server_errors_become_safe_messages(fake_s3, status, code, message):
    fake_s3.fail_with = (status, code)
    with pytest.raises(S3Error) as err:
        put_object(fake_s3.cfg, "x", b"")
    assert str(err.value) == message
    assert fake_s3.cfg.secret_key not in str(err.value)


def test_unreachable_server():
    with pytest.raises(S3Error, match="Cannot reach the backup server. Check the internet connection."):
        put_object(S3Config("http://127.0.0.1:9", "b", "k", "s"), "x", b"", timeout=2)


def test_http_refused_except_localhost():
    with pytest.raises(S3Error, match="must start with https://"):
        put_object(S3Config("http://s3.kalourmade.com", "b", "k", "s"), "x", b"")


def test_already_encoded_query_and_path_are_not_encoded_twice():
    # The URL is encoded once when it is built; signing must use it as is (MinIO rejected
    # a list request whose prefix had a space, '=' or '/' when it was encoded twice).
    from s3client import _canonical_path, _canonical_query
    assert _canonical_query("prefix=x%20y%3Dz%2F&list-type=2") == "list-type=2&prefix=x%20y%3Dz%2F"
    assert _canonical_path("/medtracker-inventory/a%20b/c.enc") == "/medtracker-inventory/a%20b/c.enc"
