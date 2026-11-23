"""Shared pytest fixtures: every test gets its own fresh, empty database file."""

from datetime import date

import pytest

import db
import logic

# A fixed "today" so tests never depend on the real calendar.
TODAY = date(2026, 6, 15)


@pytest.fixture
def conn(tmp_path):
    connection = db.connect(tmp_path / "test.db")
    yield connection
    connection.close()


@pytest.fixture
def add(conn):
    """Helper: add stock with sensible defaults."""
    def _add(name="Paracetamol", qty=100, batch="B001", expiry="2027-01-31",
             on="2026-06-01", unit="tablets", reorder=20):
        return logic.add_stock(conn, on, name, qty, batch, expiry,
                               unit=unit, reorder_level=reorder, today=TODAY)
    return _add


@pytest.fixture
def give(conn):
    """Helper: dispense with sensible defaults."""
    def _give(name="Paracetamol", qty=10, batch=None, on="2026-06-10",
              patient="P1", prescriber="Dr A"):
        return logic.dispense(conn, on, name, qty, batch_no=batch, patient_id=patient,
                              prescriber=prescriber, today=TODAY)
    return _give


class FakeS3:
    """A tiny S3 stand-in for tests: stores PUT bodies, serves GET and ListObjectsV2."""

    def __init__(self):
        self.store: dict[str, bytes] = {}
        self.fail_with = None        # (status, code) to answer every request with an error
        self.cfg = None
        self.requests = []           # (method, path) of every request


@pytest.fixture
def fake_s3():
    import http.server
    import threading
    from urllib.parse import parse_qs, unquote, urlparse
    from xml.sax.saxutils import escape

    from s3client import S3Config

    fake = FakeS3()

    class Handler(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def _fail(self):
            if not fake.fail_with:
                return False
            status, code = fake.fail_with
            body = f"<Error><Code>{code}</Code><Message>x</Message></Error>".encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return True

        def _key(self):
            path = unquote(urlparse(self.path).path)
            return path.split("/", 2)[2] if path.count("/") >= 2 else ""

        def _send(self, body: bytes, status=200):
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_PUT(self):
            fake.requests.append(("PUT", self.path))
            data = self.rfile.read(int(self.headers.get("Content-Length", 0)))
            if self._fail():
                return
            fake.store[self._key()] = data
            self._send(b"")

        def do_GET(self):
            fake.requests.append(("GET", self.path))
            if self._fail():
                return
            query = parse_qs(urlparse(self.path).query)
            if "list-type" in query:
                prefix = query.get("prefix", [""])[0]
                keys = sorted(k for k in fake.store if k.startswith(prefix))
                start = int(query.get("continuation-token", ["0"])[0])
                page = keys[start:start + 1000]
                more = start + 1000 < len(keys)
                items = "".join(
                    f"<Contents><Key>{escape(k)}</Key><Size>{len(fake.store[k])}</Size>"
                    f"<LastModified>2026-11-23T09:00:00.000Z</LastModified></Contents>" for k in page)
                token = f"<NextContinuationToken>{start + 1000}</NextContinuationToken>" if more else ""
                body = ('<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
                        f"<IsTruncated>{'true' if more else 'false'}</IsTruncated>{token}{items}"
                        "</ListBucketResult>")
                return self._send(body.encode())
            key = self._key()
            if key not in fake.store:
                return self._send(b"<Error><Code>NoSuchKey</Code></Error>", 404)
            self._send(fake.store[key])

    httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    fake.cfg = S3Config(f"http://127.0.0.1:{httpd.server_port}", "medtracker-inventory",
                        "test-access", "test-secret-value")
    yield fake
    httpd.shutdown()
