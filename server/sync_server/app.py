"""
app.py - The sync server's web API (FastAPI). Run with `python -m sync_server.app`.

    POST /v1/join       {code, computer}  -> {device, token, empty}
    POST /v1/changes    {changes}         -> {seq, rejected}
    GET  /v1/changes    ?after=N&limit=M  -> {changes, more}
    GET  /v1/snapshot                     -> {rows, seq}
    GET  /v1/health                       -> {ok}

Every request but health sends X-MedTracker-Format; all but join and health send
`Authorization: Bearer <token>`. Errors are {"message": ...}, safe to show to the user.
"""

import logging
import os
from datetime import datetime

from fastapi import Body, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from sync_schema import FORMAT, TOO_OLD
from sync_server.core import Core, SyncError

MAX_BODY = 20 * 1024 * 1024
log = logging.getLogger("sync_server")


def create_app(core: Core) -> FastAPI:
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

    def device(authorization: str | None, data_format: str | None) -> str:
        check_format(data_format)
        scheme, _, token = (authorization or "").partition(" ")
        if scheme.lower() != "bearer" or not token:
            raise SyncError(401, "This computer is not joined to sync.")
        return core.device_for(token.strip(), datetime.now())

    @app.get("/v1/health")
    def health():
        return {"ok": True}

    @app.post("/v1/join")
    def join(code: str = Body(...), computer: str = Body(...),
             x_medtracker_format: str | None = Header(None)):
        check_format(x_medtracker_format)
        return core.join(code, computer, datetime.now())

    @app.post("/v1/changes")
    def push(changes: list = Body(..., embed=True), authorization: str | None = Header(None),
             x_medtracker_format: str | None = Header(None)):
        return core.push(device(authorization, x_medtracker_format), changes)

    @app.get("/v1/changes")
    def pull(after: int = Query(0, ge=0), limit: int = Query(1000, ge=1, le=1000),
             authorization: str | None = Header(None), x_medtracker_format: str | None = Header(None)):
        device(authorization, x_medtracker_format)
        return core.pull(after, limit)

    @app.get("/v1/snapshot")
    def snapshot(authorization: str | None = Header(None),
                 x_medtracker_format: str | None = Header(None)):
        device(authorization, x_medtracker_format)
        return core.snapshot()

    return app


def main() -> None:
    import uvicorn
    from sync_server.store_pg import PostgresStore
    logging.basicConfig(level=logging.INFO)
    app = create_app(Core(PostgresStore(os.environ["DATABASE_URL"])))
    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", "8000")),
                proxy_headers=True, forwarded_allow_ips="*")


if __name__ == "__main__":
    main()
