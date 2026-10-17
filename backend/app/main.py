"""FamilyLog's FastAPI app: accounts, settings, help, and every section.

The shell is small on purpose: what a section does lives in its package
(app/sections/<id>/); this file wires them in from the registry and keeps
the rules that hold for all of them - the session check, the family
lockout, admin-only settings.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .core import auth, comfy, db, help as help_reg, jobqueue, logs, ollama, settings
from .meta import APP_DISPLAY_NAME, APP_ID, APP_VERSION
from .sections import SECTIONS

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"


@asynccontextmanager
async def lifespan(_app: FastAPI):
    logs.setup()
    ran = db.init_db()
    if ran:
        import logging
        logging.getLogger(APP_ID).info("migrations applied: %s", "; ".join(ran))
    settings.apply_timezone()
    yield


app = FastAPI(title=APP_DISPLAY_NAME, version=APP_VERSION, lifespan=lifespan)

# ---------- authentication ----------
# Everything under /api needs a session except these, plus what sections
# declare public (FamilyMap's page name for its login screen).
CORE_PUBLIC_PATHS = {"/api/auth/status", "/api/auth/setup", "/api/auth/login",
                     "/api/auth/logout", "/api/meta"}


def public_paths() -> set[str]:
    out = set(CORE_PUBLIC_PATHS)
    for s in SECTIONS:
        out.update(s.public_paths)
    return out


PUBLIC_PATHS = public_paths()


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if not path.startswith("/api") or path in PUBLIC_PATHS:
        return await call_next(request)
    me = auth.session_user(request.cookies.get(auth.SESSION_COOKIE))
    if not me:
        return JSONResponse({"detail": "Not signed in."}, status_code=401)
    # A family account reaches the family page's API and nothing else -
    # decided here, once, so no endpoint has to remember.
    if not auth.family_allows(me, path):
        return JSONResponse({"detail": "Kun familiesiden."}, status_code=403)
    request.state.user = me
    return await call_next(request)


def current_user(request: Request) -> dict:
    return request.state.user


def require_admin(request: Request) -> dict:
    me = request.state.user
    if me["role"] != "admin":
        raise HTTPException(403, "Administrator only.")
    return me


def _is_secure(request: Request) -> bool:
    """True when the browser reached us over HTTPS, directly or via the proxy."""
    proto = request.headers.get("x-forwarded-proto", "")
    return request.url.scheme == "https" or proto.split(",")[0].strip() == "https"


def set_session_cookie(response: Response, token: str, secure: bool) -> None:
    response.set_cookie(
        auth.SESSION_COOKIE, token,
        # The server's expires_at is the authority; the cookie just lasts as
        # long as the longest possible session.
        max_age=auth.SESSION_DAYS_ADMIN * 86400,
        httponly=True, samesite="lax", secure=secure, path="/")


class Credentials(BaseModel):
    username: str
    password: str


class PasswordBody(BaseModel):
    password: str


@app.get("/api/meta")
def meta():
    """The app's name and version, before anyone signs in (login screen)."""
    return {"name": APP_DISPLAY_NAME, "version": APP_VERSION}


@app.get("/api/auth/status")
def auth_status(request: Request):
    me = auth.session_user(request.cookies.get(auth.SESSION_COOKIE))
    return {"needsSetup": auth.user_count() == 0, "user": me}


@app.post("/api/auth/setup")
def auth_setup(body: Credentials, response: Response, request: Request):
    """First run: the first account is the admin."""
    if auth.user_count() > 0:
        raise HTTPException(400, "Already set up.")
    try:
        user = auth.create_user(body.username, body.password, "admin")
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    set_session_cookie(response, auth.create_session(user["id"]), _is_secure(request))
    return {"user": user}


@app.post("/api/auth/login")
def auth_login(body: Credentials, response: Response, request: Request):
    token, error = auth.login(body.username, body.password)
    if error:
        raise HTTPException(401, error)
    set_session_cookie(response, token, _is_secure(request))
    return {"user": auth.session_user(token)}


@app.post("/api/auth/logout")
def auth_logout(request: Request, response: Response):
    auth.revoke_session(request.cookies.get(auth.SESSION_COOKIE))
    response.delete_cookie(auth.SESSION_COOKIE, path="/")
    return {"ok": True}


# ---------- accounts (admin) ----------

@app.get("/api/users")
def list_users(request: Request):
    require_admin(request)
    online = {s["userId"] for s in auth.active_sessions()}
    users = auth.list_users()
    for u in users:
        u["online"] = u["id"] in online
    return users


class CreateUserBody(BaseModel):
    username: str
    password: str
    role: str = "user"


@app.post("/api/users")
def create_user(body: CreateUserBody, request: Request):
    """A `user` (counts towards the limit) or a `family` account (does not;
    FamilyMap's admin page makes those too)."""
    require_admin(request)
    if body.role not in ("user", auth.FAMILY_ROLE):
        raise HTTPException(400, "Role must be user or family.")
    if body.role == "user" and auth.account_count() >= auth.MAX_USERS:
        raise HTTPException(400, f"Limit is {auth.MAX_USERS} accounts (family accounts not counted).")
    try:
        return auth.create_user(body.username, body.password, body.role)
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.patch("/api/users/{uid}/password")
def change_password(uid: int, body: PasswordBody, request: Request):
    me = current_user(request)
    if me["role"] != "admin" and me["id"] != uid:
        raise HTTPException(403, "You can only change your own password.")
    if auth.get_user(uid) is None:
        raise HTTPException(404, "No such account.")
    try:
        auth.set_password(uid, body.password)
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    if me["id"] != uid:
        auth.revoke_user_sessions(uid)          # a re-login with the new password
    return {"ok": True}


@app.delete("/api/users/{uid}")
def remove_user(uid: int, request: Request):
    me = require_admin(request)
    if uid == me["id"]:
        raise HTTPException(400, "You cannot delete your own account.")
    auth.delete_user(uid)
    return {"ok": True}


@app.post("/api/users/{uid}/sign-out")
def force_sign_out(uid: int, request: Request):
    require_admin(request)
    auth.revoke_user_sessions(uid)
    return {"ok": True}


# ---------- settings (admin) ----------

@app.get("/api/settings")
def get_settings(request: Request):
    require_admin(request)
    return settings.public()


@app.put("/api/settings")
def put_settings(body: dict, request: Request):
    require_admin(request)
    try:
        return settings.save(body)
    except settings.Invalid as exc:
        raise HTTPException(400, str(exc))


class UrlBody(BaseModel):
    url: str | None = None


@app.post("/api/settings/test-ollama")
async def test_ollama(body: UrlBody, request: Request):
    """The Test button: list the models at this address (the unsaved one in
    the form, or the saved one). The answer says why when it fails."""
    require_admin(request)
    url = (body.url or "").strip() or settings.load()["ollamaUrl"]
    if url and not url.startswith(("http://", "https://")):
        return {"ok": False, "url": url, "models": [],
                "error": "The address must start with http:// or https://."}
    try:
        models = await ollama.tags(url)
    except ollama.OllamaError as exc:
        return {"ok": False, "url": url, "models": [], "error": str(exc)}
    return {"ok": True, "url": url, "models": models, "error": None}


@app.post("/api/settings/test-comfy")
async def test_comfy(body: UrlBody, request: Request):
    require_admin(request)
    url = (body.url or "").strip() or settings.load()["comfyUrl"]
    ok, message = await comfy.ping(url)
    return {"ok": ok, "url": url, "message": message}


@app.get("/api/ollama/models")
async def list_models(request: Request):
    """Installed model names for the sections' model pickers (any signed-in
    non-family user). Empty when Ollama is unreachable."""
    return await ollama.list_models()


@app.get("/api/roles")
def roles(request: Request):
    """The model chosen per role, for the sections' "empty = Settings" hints."""
    return {r: settings.role_model(r) for r in settings.ROLES}


# ---------- help and diagnostics ----------

@app.get("/api/help")
def help_registry(request: Request):
    """docs/HELP.md, read on each call (small; an edit shows without a restart)."""
    return {"version": APP_VERSION, "name": APP_DISPLAY_NAME, "entries": help_reg.entries()}


@app.get("/api/diagnostics")
def diagnostics(request: Request):
    require_admin(request)
    return {"version": APP_VERSION, "queue": jobqueue.snapshot(),
            "recent": logs.recent(50), "logTail": logs.tail(200)}


@app.delete("/api/diagnostics/recent")
def clear_recent(request: Request):
    require_admin(request)
    logs.clear()
    return {"ok": True}


# ---------- the sections ----------

for _section in SECTIONS:
    app.include_router(_section.router)


@app.get("/api/sections")
def sections(request: Request):
    return [{"id": s.id, "title": s.title} for s in SECTIONS]


# ---------- the frontend ----------
if STATIC_DIR.is_dir():
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
else:
    @app.get("/", include_in_schema=False)
    def _no_frontend():
        return PlainTextResponse(
            f"{APP_DISPLAY_NAME} {APP_VERSION}: the frontend is not built "
            f"(no {STATIC_DIR}). Run `npm run build` in frontend/ and copy dist/ there, "
            "or use the container image.", status_code=503)
