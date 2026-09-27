"""Auth: email/password (pbkdf2, stdlib) + Google ID token + JWT sessions."""
import hashlib
import hmac
import os
import secrets
import time

import jwt
import requests

from . import db

JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-change-me")
JWT_TTL_SECONDS = int(os.getenv("JWT_TTL_SECONDS", "604800"))  # 7 days
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID", "")


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 200_000)
    return f"pbkdf2$200000${salt}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        _, iters, salt, hexdk = stored.split("$")
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iters))
        return hmac.compare_digest(dk.hex(), hexdk)
    except Exception:
        return False


def create_token(user_id: str, email: str) -> str:
    now = int(time.time())
    payload = {"sub": user_id, "email": email, "iat": now, "exp": now + JWT_TTL_SECONDS}
    return jwt.encode(payload, JWT_SECRET, algorithm="HS256")


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=["HS256"])


def verify_google_id_token(id_token: str) -> dict:
    """Verify via Google tokeninfo. Returns {sub, email, name}."""
    resp = requests.get("https://oauth2.googleapis.com/tokeninfo", params={"id_token": id_token}, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    if GOOGLE_CLIENT_ID and data.get("aud") != GOOGLE_CLIENT_ID:
        raise ValueError("Google token audience mismatch")
    if not data.get("sub") or not data.get("email"):
        raise ValueError("Invalid Google token")
    return {"sub": data["sub"], "email": data["email"], "name": data.get("name", "")}


def get_or_create_user(email: str, name: str = "", password_hash: str = "", google_sub: str | None = None) -> dict:
    conn = db._connect()
    try:
        email = email.strip().lower()
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if row:
            if google_sub and not row["google_sub"]:
                conn.execute("UPDATE users SET google_sub=? WHERE id=?", (google_sub, row["id"]))
                conn.commit()
                row = conn.execute("SELECT * FROM users WHERE id=?", (row["id"],)).fetchone()
            return dict(row)
        if google_sub:
            grow = conn.execute("SELECT * FROM users WHERE google_sub=?", (google_sub,)).fetchone()
            if grow:
                return dict(grow)
        uid = db.new_id("u_")
        conn.execute(
            "INSERT INTO users (id, email, name, password_hash, google_sub, created_at) VALUES (?,?,?,?,?,?)",
            (uid, email, name, password_hash, google_sub, db.now_iso()),
        )
        conn.execute("INSERT OR IGNORE INTO wallets (user_id, balance) VALUES (?, 0)", (uid,))
        conn.commit()
        if db.SIGNUP_BONUS > 0:
            try:
                db.add_credits(uid, db.SIGNUP_BONUS, "signup_bonus")
            except Exception:
                pass
        return dict(conn.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone())
    finally:
        conn.close()
