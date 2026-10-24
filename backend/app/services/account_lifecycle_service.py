import os
import requests
from fastapi import HTTPException


def admin_headers():
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise HTTPException(status_code=503, detail="Account management is unavailable.")
    headers = {"apikey": key, "Prefer": "return=representation"}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    return url, headers


def profile_request(method, user_id, payload=None, conditions=None):
    url, headers = admin_headers()
    params = {
        "id": "eq." + user_id,
        "select": "id,email,role,approval_status",
        **(conditions or {}),
    }
    try:
        response = requests.request(
            method, url + "/rest/v1/profiles",
            headers=headers, params=params, json=payload, timeout=12,
        )
        if not response.ok:
            raise HTTPException(status_code=503, detail="Account status is temporarily unavailable.")
        rows = response.json()
        if not isinstance(rows, list):
            raise ValueError("Unexpected profile response")
        return rows
    except (requests.RequestException, ValueError):
        raise HTTPException(status_code=503, detail="Account status is temporarily unavailable.") from None


def delete_auth_user(user_id):
    url, headers = admin_headers()
    try:
        response = requests.delete(
            url + "/auth/v1/admin/users/" + user_id,
            headers=headers,
            json={"should_soft_delete": False},
            timeout=12,
        )
    except requests.RequestException:
        raise HTTPException(
            status_code=503,
            detail="Account deletion could not be confirmed. Refresh before retrying.",
        ) from None
    if response.status_code not in (200, 204, 404):
        raise HTTPException(
            status_code=502,
            detail="Supabase could not delete this account. No local records were removed.",
        )
