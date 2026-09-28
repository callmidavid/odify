"""Bachs checkout + webhook verification. Docs: https://docs.bachs.io (sandbox first)."""
import hashlib
import hmac
import os
import time

import requests

BACHS_API_KEY = os.getenv("BACHS_API_KEY", "")

# Credit packs sold (NGN). 1 credit == 1 lead requested (Option A).
PACKS = {
    "trial_150": {"credits": 150, "amount": "1000.00", "currency": "NGN", "label": "150 credits"},
    "starter_250": {"credits": 250, "amount": "2000.00", "currency": "NGN", "label": "250 credits"},
    "growth_650": {"credits": 650, "amount": "5000.00", "currency": "NGN", "label": "650 credits"},
}


def _api_key() -> str:
    return os.getenv("BACHS_API_KEY", "") or BACHS_API_KEY


def bachs_base(key: str = "") -> str:
    key = key or _api_key()
    if key.startswith("sk_sandbox_"):
        return "https://sandbox-api.bachs.io"
    return "https://api.bachs.io"


def create_checkout(customer_email: str, customer_name: str, pack_id: str, payment_id: str,
                    success_url: str, cancel_url: str) -> dict:
    pack = PACKS.get(pack_id)
    if not pack:
        raise ValueError("unknown pack")
    key = _api_key()
    if not key:
        raise RuntimeError("BACHS_API_KEY not set")
    # Raw-amount checkout: no catalog product needed, dynamic NGN pricing.
    body = {
        "pricing": {"currency": pack["currency"], "amount": pack["amount"]},
        "customer": {"email": customer_email, "name": customer_name or customer_email},
        "success_url": success_url,
        "cancel_url": cancel_url,
        "reference": payment_id,
        "metadata": {"user_ref": payment_id, "pack_id": pack_id, "credits": str(pack["credits"])},
        "customer_creation": "always",
    }
    resp = requests.post(
        f"{bachs_base(key)}/v1/checkout-sessions",
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        json=body,
        timeout=20,
    )
    if not resp.ok:
        raise RuntimeError(f"Bachs {resp.status_code}: {resp.text[:300]}")
    return resp.json()


def verify_signature_v2(header: str, raw_body: bytes, secret: str, tolerance: int = 300) -> bool:
    """Prefer X-Bachs-Signature-V2: 't=...,v1=...' (may carry multiple v1 during rotation)."""
    try:
        parts = [p for p in header.split(",") if "=" in p]
        kv = {}
        sigs = []
        for p in parts:
            k, v = p.split("=", 1)
            if k == "v1":
                sigs.append(v)
            elif k == "t":
                kv["t"] = v
        timestamp = int(kv.get("t", "0"))
        if abs(time.time() - timestamp) > tolerance:
            return False
        expected = hmac.new(secret.encode(), f"{timestamp}.".encode() + raw_body, hashlib.sha256).hexdigest()
        return any(hmac.compare_digest(expected, s) for s in sigs)
    except Exception:
        return False


def verify_signature_legacy(raw_body: bytes, secret: str, timestamp_header: str, signature_header: str,
                            tolerance: int = 300) -> bool:
    try:
        ts = int(timestamp_header)
        if abs(time.time() - ts) > tolerance:
            return False
        msg = f"{ts}.{raw_body.decode('utf-8')}"
        expected = hmac.new(secret.encode(), msg.encode(), hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature_header)
    except Exception:
        return False
