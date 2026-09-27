import os

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI, Form, Header, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse
from pydantic import BaseModel

from src.modules.ody.services import (
    run_search,
    run_search_places,
    generate_csv,
    generate_vcard_for_result,
    generate_all_vcards,
    get_results,
)
from src.modules.billing import db as billing_db
from src.modules.billing import auth as billing_auth
from src.modules.billing import bachs as bachs_lib

billing_db.init_db()

buildApp = FastAPI(title="Odify API")

buildApp.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

FRONTEND_URL = os.getenv("FRONTEND_URL", "https://odify.vercel.app").rstrip("/")
BACHS_WEBHOOK_SECRET = os.getenv("BACHS_WEBHOOK_SECRET", "")


def _current_user(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        return {}
    try:
        return billing_auth.decode_token(authorization.split(" ", 1)[1])
    except Exception:
        return {}


def _me(authorization: str | None = Header(default=None, alias="Authorization")) -> dict:
    claims = _current_user(authorization)
    if not claims.get("sub"):
        return {}
    return claims


class SignupBody(BaseModel):
    email: str
    password: str
    name: str = ""


class LoginBody(BaseModel):
    email: str
    password: str


class GoogleBody(BaseModel):
    id_token: str


class CheckoutBody(BaseModel):
    pack_id: str


@buildApp.get("/")
def health():
    return {"ok": True, "app": "Odify API"}


@buildApp.get("/billing/packs")
def packs():
    return {"packs": bachs_lib.PACKS}


# ---- Auth ----

@buildApp.post("/auth/signup")
def signup(body: SignupBody):
    email = body.email.strip().lower()
    if "@" not in email or len(body.password) < 6:
        return JSONResponse({"detail": "Invalid email or password (min 6 chars)"}, status_code=400)
    conn = billing_db._connect()
    try:
        exists = conn.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
        if exists:
            return JSONResponse({"detail": "Email already registered — log in"}, status_code=400)
    finally:
        conn.close()
    user = billing_auth.get_or_create_user(email, body.name, billing_auth.hash_password(body.password))
    token = billing_auth.create_token(user["id"], user["email"])
    return {"access_token": token, "user": {"id": user["id"], "email": user["email"], "name": user.get("name", "")},
            "credits": billing_db.get_balance(user["id"])}


@buildApp.post("/auth/login")
def login(body: LoginBody):
    email = body.email.strip().lower()
    conn = billing_db._connect()
    try:
        row = conn.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        if not row or not row["password_hash"] or not billing_auth.verify_password(body.password, row["password_hash"]):
            return JSONResponse({"detail": "Invalid email or password"}, status_code=401)
        user = dict(row)
    finally:
        conn.close()
    token = billing_auth.create_token(user["id"], user["email"])
    return {"access_token": token, "user": {"id": user["id"], "email": user["email"], "name": user.get("name", "")},
            "credits": billing_db.get_balance(user["id"])}


@buildApp.post("/auth/google")
def google_login(body: GoogleBody):
    try:
        info = billing_auth.verify_google_id_token(body.id_token)
    except Exception as e:
        return JSONResponse({"detail": f"Google verification failed: {e}"}, status_code=401)
    user = billing_auth.get_or_create_user(info["email"], info.get("name", ""), google_sub=info["sub"])
    token = billing_auth.create_token(user["id"], user["email"])
    return {"access_token": token, "user": {"id": user["id"], "email": user["email"], "name": user.get("name", "")},
            "credits": billing_db.get_balance(user["id"])}


@buildApp.get("/me/credits")
def my_credits(authorization: str | None = Header(default=None, alias="Authorization")):
    claims = _current_user(authorization)
    if not claims.get("sub"):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    return {"credits": billing_db.get_balance(claims["sub"]), "email": claims.get("email")}


@buildApp.get("/me/history")
def my_history(authorization: str | None = Header(default=None, alias="Authorization")):
    claims = _current_user(authorization)
    if not claims.get("sub"):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    conn = billing_db._connect()
    try:
        rows = conn.execute(
            "SELECT delta, reason, ref, balance_after, created_at FROM ledger WHERE user_id=? ORDER BY id DESC LIMIT 50",
            (claims["sub"],),
        ).fetchall()
        return {"history": [dict(r) for r in rows]}
    finally:
        conn.close()


# ---- Billing (Bachs) ----

@buildApp.post("/billing/checkout")
def billing_checkout(body: CheckoutBody, authorization: str | None = Header(default=None, alias="Authorization")):
    claims = _current_user(authorization)
    if not claims.get("sub"):
        return JSONResponse({"detail": "Unauthorized"}, status_code=401)
    pack = bachs_lib.PACKS.get(body.pack_id)
    if not pack:
        return JSONResponse({"detail": "Unknown pack"}, status_code=400)
    payment_id = billing_db.new_id("pay_")
    conn = billing_db._connect()
    try:
        conn.execute(
            "INSERT INTO payments (id, user_id, amount, currency, credits, status, created_at) VALUES (?,?,?,?,?,?,?)",
            (payment_id, claims["sub"], pack["amount"], pack["currency"], pack["credits"], "pending", billing_db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    try:
        session = bachs_lib.create_checkout(
            customer_email=claims.get("email", ""),
            customer_name="",
            pack_id=body.pack_id,
            payment_id=payment_id,
            success_url=f"{FRONTEND_URL}/success",
            cancel_url=f"{FRONTEND_URL}/pricing?cancelled=1",
        )
    except Exception as e:
        return JSONResponse({"detail": f"Checkout failed: {e}"}, status_code=502)
    conn = billing_db._connect()
    try:
        conn.execute("UPDATE payments SET checkout_id=? WHERE id=?", (session.get("checkout_id", ""), payment_id))
        conn.commit()
    finally:
        conn.close()
    return {"checkout_url": session.get("checkout_url"), "checkout_id": session.get("checkout_id"),
            "payment_id": payment_id}


@buildApp.post("/billing/webhook")
async def billing_webhook(request: Request):
    raw = await request.body()
    secret = os.getenv("BACHS_WEBHOOK_SECRET", "") or BACHS_WEBHOOK_SECRET
    v2 = request.headers.get("X-Bachs-Signature-V2", "")
    ok = bachs_lib.verify_signature_v2(v2, raw, secret) if (v2 and secret) else False
    if not ok and secret:
        legacy_ok = bachs_lib.verify_signature_legacy(
            raw, secret,
            request.headers.get("X-Bachs-Timestamp", ""),
            request.headers.get("X-Bachs-Signature", ""),
        )
        ok = legacy_ok
    if secret and not ok:
        return JSONResponse({"detail": "Bad signature"}, status_code=401)
    try:
        event = await request.json()
    except Exception:
        return JSONResponse({"detail": "Bad JSON"}, status_code=400)
    etype = event.get("type", "")
    eid = event.get("id", "")
    data = event.get("data", {}) or {}
    if eid:
        conn = billing_db._connect()
        try:
            exists = conn.execute("SELECT event_id FROM webhook_events WHERE event_id=?", (eid,)).fetchone()
            if exists:
                return {"ok": True, "deduped": True}
            conn.execute("INSERT INTO webhook_events (event_id, type, created_at) VALUES (?,?,?)",
                         (eid, etype, billing_db.now_iso()))
            conn.commit()
        finally:
            conn.close()
    if etype == "collection.succeeded":
        checkout_id = data.get("checkout_id", "")
        conn = billing_db._connect()
        try:
            pay = None
            if checkout_id:
                pay = conn.execute("SELECT * FROM payments WHERE checkout_id=?", (checkout_id,)).fetchone()
            if not pay:
                # fallback: match by reference == payment id if Bachs echoes it
                ref = data.get("reference", "")
                if ref:
                    pay = conn.execute("SELECT * FROM payments WHERE id=?", (ref,)).fetchone()
            if pay and pay["status"] != "paid":
                conn.execute("UPDATE payments SET status='paid' WHERE id=?", (pay["id"],))
                conn.commit()
                try:
                    billing_db.add_credits(pay["user_id"], int(pay["credits"]), "topup_bachs", pay["id"])
                except Exception:
                    pass
        finally:
            conn.close()
    return {"ok": True}


# ---- Search (Option A: charge requested upfront, refund shortfall) ----

@buildApp.post("/search")
def search(
    niche: str = Form(...),
    country: str = Form(...),
    max_results: int = Form(10),
):
    query = f"{niche} in {country}"
    session_id, data = run_search(query, max_results)
    return {
        "session_id": session_id,
        "results": [
            {
                "url": r["url"],
                "emails": r["emails"],
                "phones": r["phones"],
                "emails_str": ", ".join(r["emails"]),
                "phones_str": ", ".join(r["phones"]),
            }
            for r in data
        ],
    }


@buildApp.post("/search-places")
def search_places(
    niche: str = Form(...),
    location: str = Form(...),
    max_results: int = Form(30),
    authorization: str | None = Header(default=None, alias="Authorization"),
):
    claims = _current_user(authorization)
    if not claims.get("sub"):
        return JSONResponse({"detail": "Unauthorized — log in to search"}, status_code=401)
    try:
        requested = int(max_results)
    except Exception:
        return JSONResponse({"detail": "max_results must be a number"}, status_code=400)
    requested = max(1, min(50, requested))
    user_id = claims["sub"]
    try:
        balance_after_charge = billing_db.charge_upfront(user_id, requested, ref=f"{niche}|{location}")
    except ValueError:
        bal = billing_db.get_balance(user_id)
        return JSONResponse(
            {"detail": f"Insufficient credits — this search needs {requested} credits, you have {bal}",
             "need_topup": True, "required": requested, "balance": bal},
            status_code=402,
        )
    try:
        session_id, data = run_search_places(niche, location, requested)
    except Exception as e:
        # Full refund on scraper failure — user pays only for delivered leads
        billing_db.refund_shortfall(user_id, requested, ref="search_failed_refund")
        return JSONResponse({"detail": f"Search failed: {e}"}, status_code=500)
    returned = len(data)
    refunded = max(0, requested - returned)
    if refunded:
        billing_db.refund_shortfall(user_id, refunded, ref=session_id)
    balance = billing_db.get_balance(user_id)
    conn = billing_db._connect()
    try:
        conn.execute(
            "INSERT INTO searches (user_id, niche, location, requested, returned, charged, refunded, created_at)"
            " VALUES (?,?,?,?,?,?,?,?)",
            (user_id, niche, location, requested, returned, requested, refunded, billing_db.now_iso()),
        )
        conn.commit()
    finally:
        conn.close()
    return {
        "session_id": session_id,
        "results": data,
        "credits_charged": requested,
        "credits_refunded": refunded,
        "credits_balance": balance,
    }


@buildApp.get("/download/csv/{session_id}")
def download_csv(session_id: str):
    csv_data = generate_csv(session_id)
    return PlainTextResponse(
        csv_data,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=leads.csv"},
    )


@buildApp.get("/download/vcard/{session_id}/{idx}")
def download_vcard(session_id: str, idx: int):
    results = get_results(session_id)
    if idx < 0 or idx >= len(results):
        return PlainTextResponse("Not found", status_code=404)
    vcard = generate_vcard_for_result(results[idx])
    return PlainTextResponse(
        vcard,
        media_type="text/vcard",
        headers={"Content-Disposition": f"attachment; filename=lead_{idx}.vcf"},
    )


@buildApp.get("/download/all-vcards/{session_id}")
def download_all_vcards(session_id: str):
    vcards = generate_all_vcards(session_id)
    return PlainTextResponse(
        vcards,
        media_type="text/vcard",
        headers={"Content-Disposition": "attachment; filename=all_leads.vcf"},
    )
