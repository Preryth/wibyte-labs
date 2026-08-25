import os
from dataclasses import dataclass
from typing import Annotated

import requests
from fastapi import Depends, HTTPException, Request, status

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_PUBLISHABLE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")

@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None
    name: str | None
    approval_status: str


def _configuration_error():
    if not SUPABASE_URL or not SUPABASE_PUBLISHABLE_KEY:
        raise HTTPException(status_code=500, detail="Supabase backend authentication is not configured.")


def authenticate_token(token: str) -> AuthenticatedUser:
    _configuration_error()
    headers = {"apikey": SUPABASE_PUBLISHABLE_KEY, "Authorization": f"Bearer {token}"}
    try:
        user_response = requests.get(f"{SUPABASE_URL}/auth/v1/user", headers=headers, timeout=10)
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Unable to verify authentication token.") from exc
    if user_response.status_code != 200:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired authentication token.")
    user = user_response.json()
    user_id = user.get("id")
    if not user_id:
        raise HTTPException(status_code=401, detail="Authenticated user is missing an ID.")

    try:
        profile_response = requests.get(
            f"{SUPABASE_URL}/rest/v1/profiles",
            params={"id": f"eq.{user_id}", "select": "approval_status"},
            headers=headers,
            timeout=10,
        )
    except requests.RequestException as exc:
        raise HTTPException(status_code=503, detail="Unable to verify account access.") from exc
    if profile_response.status_code != 200:
        raise HTTPException(status_code=503, detail="Unable to verify account approval status.")
    profiles = profile_response.json()
    approval_status = profiles[0].get("approval_status", "pending") if profiles else "pending"
    if approval_status != "approved":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your WiByte Labs account is not approved.")
    metadata = user.get("user_metadata") or {}
    return AuthenticatedUser(
        id=user_id,
        email=user.get("email"),
        name=metadata.get("full_name") or metadata.get("name"),
        approval_status=approval_status,
    )


def get_current_user(request: Request) -> AuthenticatedUser:
    authorization = request.headers.get("Authorization", "")
    scheme, _, token = authorization.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Authentication is required.")
    user = authenticate_token(token)
    request.state.current_user = user
    return user

CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
