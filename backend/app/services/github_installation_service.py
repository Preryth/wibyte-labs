import requests
from fastapi import HTTPException
from backend.app.services.github_service import github_service

APP_SLUG = "wibyte-labs-development"


def installation_status(student_id):
    connection = github_service.get_connection(student_id)
    if connection is None:
        return {"connected": False, "installed": None, "suspended": False}

    try:
        connection = github_service._get_valid_connection(student_id)
        for page in range(1, 11):
            response = requests.get(
                "https://api.github.com/user/installations",
                headers=github_service._api_headers(connection.access_token),
                params={"per_page": 100, "page": page},
                timeout=10,
            )
            if response.status_code != 200:
                raise HTTPException(
                    status_code=503,
                    detail="Could not verify the GitHub App. Retry, or reconnect GitHub in Settings.",
                )
            items = response.json().get("installations")
            if not isinstance(items, list):
                raise ValueError("Unexpected installation response")

            for item in items:
                account = item.get("account") or {}
                if (
                    item.get("app_slug") == APP_SLUG
                    and str(account.get("id")) == str(connection.github_user_id)
                ):
                    suspended = bool(item.get("suspended_at"))
                    return {
                        "connected": True,
                        "installed": not suspended,
                        "suspended": suspended,
                        "github_username": connection.github_username,
                    }
            if len(items) < 100:
                return {
                    "connected": True, "installed": False, "suspended": False,
                    "github_username": connection.github_username,
                }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Could not verify the GitHub App. Retry, or reconnect GitHub in Settings.",
        ) from None
    raise HTTPException(status_code=503, detail="GitHub installation verification is incomplete. Please retry.")
