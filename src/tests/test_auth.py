import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from pipeline.build import SessionOptions
from web import auth
from web.server import create_app

SHIPPED = Path(__file__).parents[1] / "state_engine" / "tuning" / "tuning.json"


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "demo")
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    monkeypatch.setattr(auth.asyncio, "sleep", _no_sleep)
    shutil.copy(SHIPPED, tmp_path / "tuning.json")
    return create_app(str(tmp_path), "tuning", SessionOptions(tts=False), read_only=True)


async def _no_sleep(_s):
    return None


def test_everything_needs_login(app):
    c = TestClient(app)
    assert c.get("/", follow_redirects=False).headers["location"] == "/login"
    assert c.get("/static/app.js", follow_redirects=False).status_code == 303
    assert c.get("/api/characters").status_code == 401
    assert c.get("/config").status_code == 401
    assert "Sign in" in c.get("/login").text


def test_wrong_password_rejected(app):
    c = TestClient(app)
    r = c.post("/login", data={"username": "demo", "password": "nope"}, follow_redirects=False)
    assert r.status_code == 401 and "Wrong username or password" in r.text
    assert auth.COOKIE not in c.cookies


def test_login_logout(app):
    c = TestClient(app)
    r = c.post("/login", data={"username": "demo", "password": "s3cret"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"
    assert c.get("/api/characters").status_code == 200
    assert c.get("/config").json()["login"] is True
    c.get("/logout")
    c.cookies.clear()
    assert c.get("/api/characters").status_code == 401


def test_ws_rejected_without_login(app):
    from starlette.websockets import WebSocketDisconnect

    c = TestClient(app)
    with pytest.raises(WebSocketDisconnect) as e:
        with c.websocket_connect("/ws") as ws:
            ws.receive_json()
    assert e.value.code == 1008


def test_tampered_or_expired_cookie_rejected(monkeypatch):
    monkeypatch.setenv("APP_USERNAME", "demo")
    monkeypatch.setenv("APP_PASSWORD", "s3cret")
    good = auth.make_cookie()
    assert auth.valid(good)
    expires, sig = good.split(".")
    assert not auth.valid(f"{int(expires) + 999}.{sig}")
    assert not auth.valid("1.abc")
    monkeypatch.setenv("APP_PASSWORD", "changed")
    assert not auth.valid(good)  # changing the password logs everyone out


def test_read_only_blocks_saving(app):
    c = TestClient(app)
    c.post("/login", data={"username": "demo", "password": "s3cret"})
    data = json.loads(SHIPPED.read_text())
    r = c.put("/api/characters/tuning", json=data)
    assert r.status_code == 403 and "read-only" in r.json()["error"]
    assert c.post("/api/characters", json=data).status_code == 403
    assert c.delete("/api/characters/tuning").status_code == 403
    assert c.get("/config").json()["read_only"] is True


def test_no_login_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("APP_USERNAME", raising=False)
    monkeypatch.delenv("APP_PASSWORD", raising=False)
    shutil.copy(SHIPPED, tmp_path / "tuning.json")
    c = TestClient(create_app(str(tmp_path), "tuning", SessionOptions(tts=False)))
    assert c.get("/api/characters").status_code == 200
    assert c.get("/login", follow_redirects=False).headers["location"] == "/"


def test_asgi_entrypoint_imports(monkeypatch):
    import importlib

    monkeypatch.setenv("VERCEL", "1")
    import asgi
    importlib.reload(asgi)
    assert asgi.read_only is True and asgi.app is not None
