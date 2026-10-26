"""One shared login for demos. No accounts: the username and password come
from the environment.

    APP_USERNAME, APP_PASSWORD   the credentials (both unset = no login, for local use)
    APP_SECRET                   optional; signs the session cookie. Defaults to a
                                 value derived from the password, so changing the
                                 password logs everyone out.

The session is a signed cookie holding its expiry time; nothing is stored on
the server, so it works across Vercel instances.
"""

import asyncio
import hashlib
import hmac
import os
import time

COOKIE = "session"
SESSION_S = 12 * 3600


def enabled() -> bool:
    return bool(os.environ.get("APP_USERNAME") and os.environ.get("APP_PASSWORD"))


def _secret() -> bytes:
    explicit = os.environ.get("APP_SECRET")
    if explicit:
        return explicit.encode()
    material = f"{os.environ.get('APP_USERNAME', '')}:{os.environ.get('APP_PASSWORD', '')}:session"
    return hashlib.sha256(material.encode()).digest()


def _sign(value: str) -> str:
    return hmac.new(_secret(), value.encode(), hashlib.sha256).hexdigest()


def make_cookie() -> str:
    expires = str(int(time.time()) + SESSION_S)
    return f"{expires}.{_sign(expires)}"


def valid(cookie: str | None) -> bool:
    if not enabled():
        return True
    if not cookie or "." not in cookie:
        return False
    expires, sig = cookie.split(".", 1)
    if not hmac.compare_digest(sig, _sign(expires)):
        return False
    return expires.isdigit() and int(expires) > time.time()


async def check_credentials(username: str, password: str) -> bool:
    ok = hmac.compare_digest(username.encode(), os.environ.get("APP_USERNAME", "").encode())
    ok &= hmac.compare_digest(password.encode(), os.environ.get("APP_PASSWORD", "").encode())
    if not ok:
        await asyncio.sleep(1.0)  # slows down guessing
    return ok
