"""Postgres (Neon) persistence for auth, credits, payments. No SQLite fallback."""
import os
import time
import uuid

import psycopg
from psycopg.rows import dict_row

SIGNUP_BONUS = int(os.getenv("SIGNUP_BONUS_CREDITS", "10"))


def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "")
    if not url:
        raise RuntimeError("DATABASE_URL not set — run `neon deploy` or export it (see .env.local)")
    return url


def _connect():
    return psycopg.connect(_database_url(), row_factory=dict_row)


def init_db():
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                email TEXT UNIQUE NOT NULL,
                name TEXT DEFAULT '',
                password_hash TEXT DEFAULT '',
                google_sub TEXT UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS wallets (
                user_id TEXT PRIMARY KEY REFERENCES users(id),
                balance INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS ledger (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                delta INTEGER NOT NULL,
                reason TEXT NOT NULL,
                ref TEXT DEFAULT '',
                balance_after INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS payments (
                id TEXT PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                checkout_id TEXT DEFAULT '',
                amount TEXT NOT NULL,
                currency TEXT NOT NULL,
                credits INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS webhook_events (
                event_id TEXT PRIMARY KEY,
                type TEXT NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            CREATE TABLE IF NOT EXISTS searches (
                id SERIAL PRIMARY KEY,
                user_id TEXT NOT NULL REFERENCES users(id),
                niche TEXT NOT NULL,
                location TEXT NOT NULL,
                requested INTEGER NOT NULL,
                returned INTEGER NOT NULL,
                charged INTEGER NOT NULL,
                refunded INTEGER NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            );
            """)
        conn.commit()


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix=""):
    return f"{prefix}{uuid.uuid4().hex[:16]}"


# ---- users ----

def find_user_by_email(email: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE email=%s", (email.strip().lower(),))
            return cur.fetchone()


def find_user_by_id(uid: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE id=%s", (uid,))
            return cur.fetchone()


def find_user_by_google_sub(sub: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM users WHERE google_sub=%s", (sub,))
            return cur.fetchone()


def create_user(email: str, name: str, password_hash: str, google_sub: str | None) -> dict:
    email = email.strip().lower()
    uid = new_id("u_")
    with _connect() as conn:
        with conn.cursor() as cur:
            try:
                cur.execute(
                    "INSERT INTO users (id, email, name, password_hash, google_sub)"
                    " VALUES (%s,%s,%s,%s,%s)"
                    " ON CONFLICT (email) DO UPDATE SET"
                    " name = CASE WHEN users.name = '' THEN EXCLUDED.name ELSE users.name END,"
                    " google_sub = COALESCE(users.google_sub, EXCLUDED.google_sub)"
                    " RETURNING *",
                    (uid, email, name, password_hash, google_sub),
                )
                user = cur.fetchone()
                cur.execute("INSERT INTO wallets (user_id, balance) VALUES (%s, 0) ON CONFLICT DO NOTHING",
                            (user["id"],))
            except psycopg.errors.UniqueViolation:
                # Lost a concurrent insert race (or google_sub clash) — use the winner.
                conn.rollback()
                with conn.cursor() as cur2:
                    cur2.execute("SELECT * FROM users WHERE email=%s", (email,))
                    user = cur2.fetchone()
                    if user and google_sub and not user["google_sub"]:
                        try:
                            cur2.execute("UPDATE users SET google_sub=%s WHERE id=%s",
                                         (google_sub, user["id"]))
                            user = dict(user)
                            user["google_sub"] = google_sub
                        except psycopg.errors.UniqueViolation:
                            pass  # sub linked elsewhere; email identity wins
                    cur2.execute("INSERT INTO wallets (user_id, balance) VALUES (%s, 0) ON CONFLICT DO NOTHING",
                                 (user["id"],))
        conn.commit()
    award_signup_bonus(user["id"])
    return dict(user)


def award_signup_bonus(user_id: str):
    """Atomic + idempotent: advisory lock serializes concurrent awards per user."""
    if SIGNUP_BONUS <= 0:
        return
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (f"bonus:{user_id}",))
                cur.execute("SELECT 1 FROM ledger WHERE user_id=%s AND reason='signup_bonus'", (user_id,))
                if cur.fetchone():
                    return
                _apply_delta(cur, user_id, SIGNUP_BONUS, "signup_bonus")
            conn.commit()
    except Exception:
        pass


def link_google_sub(uid: str, sub: str):
    try:
        with _connect() as conn:
            with conn.cursor() as cur:
                cur.execute("UPDATE users SET google_sub=%s WHERE id=%s AND google_sub IS NULL", (sub, uid))
            conn.commit()
    except psycopg.errors.UniqueViolation:
        pass  # sub already linked to another row; email identity wins


# ---- credits (atomic, row-locked) ----

def get_balance(user_id: str) -> int:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT balance FROM wallets WHERE user_id=%s", (user_id,))
            row = cur.fetchone()
            return int(row["balance"]) if row else 0


def _apply_delta(cur, user_id: str, delta: int, reason: str, ref: str = "") -> int:
    cur.execute("SELECT balance FROM wallets WHERE user_id=%s FOR UPDATE", (user_id,))
    row = cur.fetchone()
    bal = int(row["balance"]) if row else 0
    new_bal = bal + delta
    if new_bal < 0:
        raise ValueError("insufficient_credits")
    if row:
        cur.execute("UPDATE wallets SET balance=%s WHERE user_id=%s", (new_bal, user_id))
    else:
        cur.execute("INSERT INTO wallets (user_id, balance) VALUES (%s, %s)", (user_id, new_bal))
    cur.execute(
        "INSERT INTO ledger (user_id, delta, reason, ref, balance_after) VALUES (%s,%s,%s,%s,%s)",
        (user_id, delta, reason, ref, new_bal),
    )
    return new_bal


def add_credits(user_id: str, amount: int, reason: str, ref: str = "") -> int:
    if amount <= 0:
        raise ValueError("amount must be positive")
    with _connect() as conn:
        with conn.cursor() as cur:
            bal = _apply_delta(cur, user_id, amount, reason, ref)
        conn.commit()
        return bal


def charge_upfront(user_id: str, requested: int, ref: str = "") -> int:
    """Deduct `requested` credits atomically. Returns new balance. Raises ValueError on insufficient."""
    if requested <= 0:
        raise ValueError("requested must be positive")
    with _connect() as conn:
        try:
            with conn.cursor() as cur:
                bal = _apply_delta(cur, user_id, -requested, "search_charge", ref)
            conn.commit()
            return bal
        except Exception:
            conn.rollback()
            raise


def refund_shortfall(user_id: str, refund: int, ref: str = "") -> int | None:
    if refund <= 0:
        return None
    return add_credits(user_id, refund, "search_refund_shortfall", ref)


def list_ledger(user_id: str, limit: int = 50) -> list[dict]:
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT delta, reason, ref, balance_after, created_at FROM ledger"
                " WHERE user_id=%s ORDER BY id DESC LIMIT %s",
                (user_id, limit),
            )
            return [dict(r) for r in cur.fetchall()]


# ---- payments / webhooks / searches ----

def insert_payment(pid: str, user_id: str, amount: str, currency: str, credits: int):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO payments (id, user_id, amount, currency, credits, status)"
                " VALUES (%s,%s,%s,%s,%s,'pending')",
                (pid, user_id, amount, currency, credits),
            )
        conn.commit()


def set_payment_checkout(pid: str, checkout_id: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE payments SET checkout_id=%s WHERE id=%s", (checkout_id, pid))
        conn.commit()


def find_payment_by_checkout(checkout_id: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM payments WHERE checkout_id=%s", (checkout_id,))
            return cur.fetchone()


def find_payment(pid: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM payments WHERE id=%s", (pid,))
            return cur.fetchone()


def mark_payment_paid(pid: str):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute("UPDATE payments SET status='paid' WHERE id=%s", (pid,))
        conn.commit()


def insert_webhook_event(event_id: str, etype: str) -> bool:
    """Returns False if already seen (deduped)."""
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO webhook_events (event_id, type) VALUES (%s,%s) ON CONFLICT DO NOTHING"
                " RETURNING event_id",
                (event_id, etype),
            )
            seen = cur.fetchone() is None
        conn.commit()
        return not seen


def record_search(user_id: str, niche: str, location: str, requested: int, returned: int,
                  charged: int, refunded: int):
    with _connect() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO searches (user_id, niche, location, requested, returned, charged, refunded)"
                " VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (user_id, niche, location, requested, returned, charged, refunded),
            )
        conn.commit()
