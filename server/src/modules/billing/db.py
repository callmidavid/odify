"""SQLite persistence for auth, credits, payments. Stdlib only."""
import os
import sqlite3
import time
import uuid

DB_PATH = os.getenv("ODIFY_DB_PATH", os.path.join(os.path.dirname(__file__), "..", "..", "..", "odify.db"))
DB_PATH = os.path.abspath(DB_PATH)

SIGNUP_BONUS = int(os.getenv("SIGNUP_BONUS_CREDITS", "10"))


def _connect():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _connect()
    cur = conn.cursor()
    cur.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id TEXT PRIMARY KEY,
        email TEXT UNIQUE NOT NULL,
        name TEXT DEFAULT '',
        password_hash TEXT DEFAULT '',
        google_sub TEXT UNIQUE,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS wallets (
        user_id TEXT PRIMARY KEY REFERENCES users(id),
        balance INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS ledger (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id),
        delta INTEGER NOT NULL,
        reason TEXT NOT NULL,
        ref TEXT DEFAULT '',
        balance_after INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS payments (
        id TEXT PRIMARY KEY,
        user_id TEXT NOT NULL REFERENCES users(id),
        checkout_id TEXT DEFAULT '',
        amount TEXT NOT NULL,
        currency TEXT NOT NULL,
        credits INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'pending',
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS webhook_events (
        event_id TEXT PRIMARY KEY,
        type TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS searches (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL REFERENCES users(id),
        niche TEXT NOT NULL,
        location TEXT NOT NULL,
        requested INTEGER NOT NULL,
        returned INTEGER NOT NULL,
        charged INTEGER NOT NULL,
        refunded INTEGER NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    conn.commit()
    conn.close()


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def new_id(prefix=""):
    return f"{prefix}{uuid.uuid4().hex[:16]}"


def get_balance(user_id: str) -> int:
    conn = _connect()
    try:
        row = conn.execute("SELECT balance FROM wallets WHERE user_id=?", (user_id,)).fetchone()
        return int(row["balance"]) if row else 0
    finally:
        conn.close()


def _set_balance_ledger(conn, user_id: str, delta: int, reason: str, ref: str = "") -> int:
    row = conn.execute("SELECT balance FROM wallets WHERE user_id=?", (user_id,)).fetchone()
    bal = int(row["balance"]) if row else 0
    new_bal = bal + delta
    if new_bal < 0:
        raise ValueError("insufficient_credits")
    if row:
        conn.execute("UPDATE wallets SET balance=? WHERE user_id=?", (new_bal, user_id))
    else:
        conn.execute("INSERT INTO wallets (user_id, balance) VALUES (?, ?)", (user_id, new_bal))
    conn.execute(
        "INSERT INTO ledger (user_id, delta, reason, ref, balance_after, created_at) VALUES (?,?,?,?,?,?)",
        (user_id, delta, reason, ref, new_bal, now_iso()),
    )
    return new_bal


def add_credits(user_id: str, amount: int, reason: str, ref: str = "") -> int:
    if amount <= 0:
        raise ValueError("amount must be positive")
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        bal = _set_balance_ledger(conn, user_id, amount, reason, ref)
        conn.commit()
        return bal
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def charge_upfront(user_id: str, requested: int, ref: str = "") -> int:
    """Deduct `requested` credits atomically. Returns new balance. Raises ValueError on insufficient."""
    if requested <= 0:
        raise ValueError("requested must be positive")
    conn = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        bal = _set_balance_ledger(conn, user_id, -requested, "search_charge", ref)
        conn.commit()
        return bal
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def refund_shortfall(user_id: str, refund: int, ref: str = "") -> int | None:
    if refund <= 0:
        return None
    return add_credits(user_id, refund, "search_refund_shortfall", ref)
