import os
import re
from urllib.parse import urlsplit

import docker
from fastapi import APIRouter, HTTPException, Request, Response
from itsdangerous import BadSignature, URLSafeTimedSerializer

from backend.app.services.lab_service import lab_service

router = APIRouter()
MAX_AGE = 12 * 60 * 60


def signer():
    secret = os.environ.get("WPL_SECRET_KEY")
    if not secret:
        raise RuntimeError("WPL_SECRET_KEY is required")
    return URLSafeTimedSerializer(secret, salt="wpl-gui-session-v1")


def issue_gui_url(response, lab_id, student_id):
    token = signer().dumps({"lab": lab_id, "student": student_id})
    response.set_cookie(
        key=f"wpl_gui_{lab_id}",
        value=token,
        max_age=MAX_AGE,
        path=f"/gui/{lab_id}/",
        secure=True,
        httponly=True,
        samesite="strict",
    )
    response.headers["Cache-Control"] = "no-store"
    return (
        f"https://labs.wibyte.in/gui/{lab_id}/vnc.html"
        f"?autoconnect=true&resize=scale&encrypt=true"
        f"&path=gui/{lab_id}/websockify"
    )


@router.get("/gui/proxy-auth")
def authorize_gui(request: Request):
    original = request.headers.get("X-Original-URI", "")
    match = re.fullmatch(
        r"/gui/([a-f0-9-]{36})/.*",
        urlsplit(original).path,
    )
    if not match:
        raise HTTPException(403, "Invalid GUI path")

    lab_id = match.group(1)
    token = request.cookies.get(f"wpl_gui_{lab_id}", "")
    try:
        payload = signer().loads(token, max_age=MAX_AGE)
    except BadSignature:
        raise HTTPException(403, "Open GUI from your lab again")

    if not isinstance(payload, dict) or payload.get("lab") != lab_id:
        raise HTTPException(403, "Invalid GUI session")

    student_id = payload.get("student")
    if not isinstance(student_id, str):
        raise HTTPException(403, "Invalid GUI session")

    session = lab_service.get_for_student(lab_id, student_id)
    if session is None:
        raise HTTPException(403, "Lab no longer exists")

    try:
        container = request.app.state.docker_client.containers.get(
            session.container_id
        )
        if container.status != "running":
            raise HTTPException(403, "Lab is not running")
        bindings = container.attrs["NetworkSettings"]["Ports"].get("6080/tcp")
        if not bindings:
            raise HTTPException(403, "GUI port unavailable")
        port = int(bindings[0]["HostPort"])
        if not 1 <= port <= 65535:
            raise HTTPException(403, "Invalid GUI port")
    except docker.errors.NotFound:
        raise HTTPException(403, "Lab no longer exists")

    return Response(
        status_code=204,
        headers={"X-Gui-Port": str(port), "Cache-Control": "no-store"},
    )
