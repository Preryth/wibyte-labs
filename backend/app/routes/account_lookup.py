
import os
import re
import time
from collections import OrderedDict
from threading import Lock

import requests
from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/auth", tags=["Account"])
_attempts = OrderedDict()
_attempt_lock = Lock()


class AccountLookup(BaseModel):
    email: str = Field(min_length=3, max_length=254)


def check_rate(request):
    address = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _attempt_lock:
        started, count = _attempts.get(address, (now, 0))
        if now - started >= 60:
            started, count = now, 0
        if count >= 60:
            raise HTTPException(
                status_code=429,
                detail="Too many attempts. Please wait a minute.",
                headers={"Retry-After": "60"},
            )
        _attempts[address] = (started, count + 1)
        _attempts.move_to_end(address)
        while len(_attempts) > 10000:
            _attempts.popitem(last=False)


@router.post("/account-status")
def account_status(payload: AccountLookup, request: Request, response: Response):
    check_rate(request)
    response.headers["Cache-Control"] = "no-store"
    email = payload.email.strip().lower()
    if re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) is None:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SECRET_KEY", "")
    failure = "Unable to check your account right now. Please try again."
    if not url or not key:
        raise HTTPException(status_code=503, detail=failure)

    # Search on the server, then verify the exact email.
    # Paginate matches; never assume an incomplete search means a new account.
    for page in range(1, 11):
        try:
            result = requests.get(
                url + "/auth/v1/admin/users",
                headers={"apikey": key},
                params={"filter": email, "page": page, "per_page": 100},
                timeout=10,
            )
            if result.status_code != 200:
                raise HTTPException(status_code=503, detail=failure)
            users = result.json().get("users")
            if not isinstance(users, list):
                raise HTTPException(status_code=503, detail=failure)
            for user in users:
                if not isinstance(user, dict):
                    raise HTTPException(status_code=503, detail=failure)
                if (user.get("email") or "").strip().lower() == email:
                    return {
                        "status": "confirmed"
                        if user.get("email_confirmed_at")
                        else "unconfirmed"
                    }
            if len(users) < 100:
                return {"status": "new"}
        except (requests.RequestException, ValueError, AttributeError):
            raise HTTPException(status_code=503, detail=failure) from None

    raise HTTPException(status_code=503, detail=failure)


def verified_account(request):
    from backend.app.auth import verify_identity
    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=401, detail="Sign in to continue.")
    return verify_identity(token)


@router.get("/access")
def account_access(request: Request, response: Response):
    from backend.app.services.account_lifecycle_service import profile_request
    from backend.app.services.admin_store import is_suspended

    user = verified_account(request)
    rows = profile_request("GET", user["id"])
    if len(rows) != 1:
        raise HTTPException(status_code=404, detail="Your account is unavailable. Please sign out.")
    profile = rows[0]
    if profile.get("approval_status") not in ("pending", "approved", "rejected", "declined"):
        raise HTTPException(status_code=503, detail="Account approval status is unavailable.")
    response.headers["Cache-Control"] = "no-store"
    return {
        "approval_status": profile["approval_status"],
        "role": profile["role"],
        "suspended": is_suspended(user["id"]),
    }


@router.post("/request-approval")
def request_approval(request: Request, response: Response):
    from types import SimpleNamespace
    from backend.app.services.account_lifecycle_service import profile_request
    from backend.app.services.admin_store import activity, is_suspended
    from backend.app.services.single_lab_service import student_lab_lock

    check_rate(request)
    user = verified_account(request)
    target = user["id"]
    response.headers["Cache-Control"] = "no-store"
    with student_lab_lock(target):
        if is_suspended(target):
            raise HTTPException(status_code=403, detail="Your account is suspended. Contact WiByte.")
        rows = profile_request("GET", target)
        if len(rows) != 1:
            raise HTTPException(status_code=404, detail="Account not found. Please sign up again.")
        status = rows[0]["approval_status"]
        if status in ("pending", "approved"):
            return {"approval_status": status}
        if status not in ("rejected", "declined"):
            raise HTTPException(status_code=409, detail="Account status changed. Refresh and retry.")
        updated = profile_request(
            "PATCH", target, {"approval_status": "pending"},
            {"approval_status": "eq." + status},
        )
        if len(updated) != 1:
            raise HTTPException(status_code=409, detail="Account status changed. Refresh and retry.")
        activity(
            "user.request_approval",
            SimpleNamespace(id=target, email=user.get("email")),
            target,
        )
    return {"approval_status": "pending"}
