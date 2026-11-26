"""
app.py - The sync server's web API (FastAPI). Run with `python -m sync_server.app`.

    GET  /v1/health                               -> {ok}
    POST /v1/join       {code, computer}          -> {device, token, empty, app, company}
    POST /v1/<app>/<company>/changes  {changes}   -> {seq, rejected}
    GET  /v1/<app>/<company>/changes  ?after=N    -> {changes, more}
    GET  /v1/<app>/<company>/snapshot             -> {rows, seq}
    PUT  /v1/admin/<app>/<company>                -> {created, code}   (creates the company's database)
    POST /v1/admin/<app>/<company>/codes          -> {code}
    GET  /v1/admin/<app>/<company>/computers      -> {computers}
    POST /v1/admin/<app>/<company>/revoke  {computer}
    GET  /status                                  -> HTML page for people (HTTP Basic, STATUS_PASSWORD)

Computers send X-MedTracker-Format, and (except to join) `Authorization: Bearer <their key>`; the
key only opens its own company. Admin addresses need `Authorization: Bearer <ADMIN_KEY>` and do
not exist without one. Errors are {"message": ...}, safe to show to the user.
"""

import base64
import logging
import os
import secrets
from datetime import datetime

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, Response

from sync_schema import FORMAT, TOO_OLD
from sync_server import status_page
from sync_server.apps import NOT_FOUND
from sync_server.control import Control
from sync_server.core import SyncError

MAX_BODY = 20 * 1024 * 1024
log = logging.getLogger("sync_server")


def create_app(control: Control, status_password: str | None = None,
               admin_key: str | None = None) -> FastAPI:
    """`status_password` turns on GET /status, `admin_key` the admin addresses; without them
    those addresses do not exist."""
    app = FastAPI(title="MedTracker sync", docs_url=None, redoc_url=None, openapi_url=None)

    @app.exception_handler(SyncError)
    def sync_error(_request, exc: SyncError):
        return JSONResponse({"message": exc.message}, status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    def bad_request(_request, _exc):
        return JSONResponse({"message": "The request was not understood."}, status_code=400)

    @app.middleware("http")
    async def limit_size(request: Request, call_next):
        if int(request.headers.get("content-length") or 0) > MAX_BODY:
            return JSONResponse({"message": "Too much data in one request."}, status_code=413)
        return await call_next(request)

    def check_format(value: str | None) -> None:
        try:
            number = int(value or 0)
        except ValueError:
            number = 0
        if number < FORMAT:
            raise SyncError(426, TOO_OLD)

    def bearer(authorization: str | None) -> str:
        scheme, _, token = (authorization or "").partition(" ")
        return token.strip() if scheme.lower() == "bearer" else ""

    def connected(app_name: str, company: str, authorization: str | None, data_format: str | None):
        """(the company's Core, the computer's id) for a computer's key."""
        check_format(data_format)
        token = bearer(authorization)
        if not token:
            raise SyncError(401, "This computer is not joined to sync.")
        return control.connect(token, app_name, company, datetime.now())

    def admin(authorization: str | None) -> None:
        if not admin_key:
            raise SyncError(404, NOT_FOUND)
        if not secrets.compare_digest(bearer(authorization).encode(), admin_key.encode()):
            raise SyncError(401, "The admin key is missing or wrong.")

    @app.get("/v1/health")
    def health():
        return {"ok": True}

    # --- status page -------------------------------------------------------------

    def status_allowed(authorization: str | None) -> bool:
        scheme, _, encoded = (authorization or "").partition(" ")
        if scheme.lower() != "basic":
            return False
        try:
            _, _, password = base64.b64decode(encoded).decode().partition(":")
        except ValueError:
            return False
        return secrets.compare_digest(password.encode(), status_password.encode())

    @app.get("/status", response_class=HTMLResponse)
    def status(authorization: str | None = Header(None)):
        if not status_password:
            return JSONResponse({"message": NOT_FOUND}, status_code=404)
        if not status_allowed(authorization):
            return Response("Password needed.", status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="MedTracker sync status"'})
        try:
            found = control.status(datetime.now())
        except Exception as exc:                       # the database is down: say so, don't crash
            log.exception("status page")
            return HTMLResponse(status_page.render(None, f"{type(exc).__name__}: {exc}"), status_code=503)
        return HTMLResponse(status_page.render(found))

    # --- computers ---------------------------------------------------------------

    @app.post("/v1/join")
    def join(code: str = Body(...), computer: str = Body(...),
             x_medtracker_format: str | None = Header(None)):
        check_format(x_medtracker_format)
        return control.join(code, computer, datetime.now())

    @app.post("/v1/{app_name}/{company}/changes")
    def push(app_name: str, company: str, changes: list = Body(..., embed=True),
             authorization: str | None = Header(None), x_medtracker_format: str | None = Header(None)):
        core, device = connected(app_name, company, authorization, x_medtracker_format)
        return core.push(device, changes)

    @app.get("/v1/{app_name}/{company}/changes")
    def pull(app_name: str, company: str, after: int = Query(0, ge=0),
             limit: int = Query(1000, ge=1, le=1000), authorization: str | None = Header(None),
             x_medtracker_format: str | None = Header(None)):
        return connected(app_name, company, authorization, x_medtracker_format)[0].pull(after, limit)

    @app.get("/v1/{app_name}/{company}/snapshot")
    def snapshot(app_name: str, company: str, authorization: str | None = Header(None),
                 x_medtracker_format: str | None = Header(None)):
        return connected(app_name, company, authorization, x_medtracker_format)[0].snapshot()

    # --- admin -------------------------------------------------------------------

    @app.put("/v1/admin/{app_name}/{company}")
    def create_company(app_name: str, company: str, authorization: str | None = Header(None)):
        admin(authorization)
        return control.create_company(app_name, company, datetime.now())

    @app.post("/v1/admin/{app_name}/{company}/codes")
    def make_code(app_name: str, company: str, authorization: str | None = Header(None)):
        admin(authorization)
        return {"code": control.make_code(app_name, company, datetime.now())}

    @app.get("/v1/admin/{app_name}/{company}/computers")
    def computers(app_name: str, company: str, authorization: str | None = Header(None)):
        admin(authorization)
        return {"computers": [{k: d[k] for k in ("name", "joined", "last_seen", "revoked")}
                              for d in control.computers(app_name, company)]}

    @app.post("/v1/admin/{app_name}/{company}/revoke")
    def revoke(app_name: str, company: str, computer: str = Body(..., embed=True),
               authorization: str | None = Header(None)):
        admin(authorization)
        control.revoke(app_name, company, computer)
        return {"ok": True}

    return app


def main() -> None:
    import uvicorn
    from sync_server.postgres import postgres_control
    logging.basicConfig(level=logging.INFO)
    app = create_app(postgres_control(os.environ["DATABASE_URL"]),
                     status_password=os.environ.get("STATUS_PASSWORD") or None,
                     admin_key=os.environ.get("ADMIN_KEY") or None)
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
