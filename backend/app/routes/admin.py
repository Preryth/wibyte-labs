import asyncio
import os
import re
import shutil
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Literal
from uuid import UUID

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from pydantic import BaseModel

from backend.app.auth import CurrentUser
from backend.app.services.admin_store import activity, connection

router = APIRouter(prefix="/admin", tags=["Admin"])


def require_admin(user: CurrentUser):
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


AdminUser = Annotated[object, Depends(require_admin)]


def supabase(method, params=None, payload=None):
    url = os.getenv("SUPABASE_URL", "").rstrip("/")
    key = os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise HTTPException(status_code=503, detail="Admin Supabase access is not configured.")
    headers = {"apikey": key, "Prefer": "count=exact,return=representation"}
    if not key.startswith("sb_secret_"):
        headers["Authorization"] = "Bearer " + key
    try:
        result = requests.request(
            method, url + "/rest/v1/profiles", headers=headers,
            params=params, json=payload, timeout=12,
        )
        if not result.ok:
            raise HTTPException(status_code=503, detail="Supabase profiles are unavailable.")
        return result.json(), result.headers.get("Content-Range", "")
    except (requests.RequestException, ValueError):
        raise HTTPException(status_code=503, detail="Supabase profiles are unavailable.") from None


def profile_count(status=None):
    params = {"select": "id", "limit": "1"}
    if status:
        params["approval_status"] = "eq." + status
    rows, content_range = supabase("GET", params)
    total = content_range.rsplit("/", 1)[-1]
    if not total.isdigit():
        raise HTTPException(status_code=503, detail="Student totals are unavailable.")
    return int(total)


def machine_metrics():
    def cpu():
        values = [int(v) for v in Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
        return sum(values), values[3] + values[4]
    before, idle_before = cpu()
    time.sleep(0.15)
    after, idle_after = cpu()
    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0]) * 1024
    disk = shutil.disk_usage("/")
    return {
        "cpu_percent": round(100 * (1 - (idle_after - idle_before) / max(1, after - before)), 1),
        "cpu_cores": os.cpu_count(),
        "load_average": list(os.getloadavg()),
        "memory_used": memory["MemTotal"] - memory["MemAvailable"],
        "memory_total": memory["MemTotal"],
        "disk_used": disk.used, "disk_total": disk.total,
    }


@router.get("/me")
def me(user: AdminUser, response: Response):
    response.headers["Cache-Control"] = "no-store"
    return {"id": user.id, "email": user.email, "role": user.role}


@router.get("/overview")
def overview(user: AdminUser):
    with ThreadPoolExecutor(max_workers=4) as pool:
        counts = list(pool.map(profile_count, (None, "approved", "pending")))
    with connection() as db:
        labs = db.execute("SELECT COUNT(*) FROM labs").fetchone()[0]
        recovery = db.execute("""
            SELECT COUNT(*) FROM lab_timeout_events e
            JOIN labs l ON l.id = e.lab_id WHERE e.outcome = 'save_failed'
        """).fetchone()[0]
        suspended = db.execute(
            "SELECT COUNT(*) FROM admin_suspensions WHERE suspended = 1"
        ).fetchone()[0]
    return {
        "students": counts[0], "approved": counts[1], "pending": counts[2],
        "active_labs": labs, "recovery_labs": recovery, "suspended": suspended,
        "resources": machine_metrics(), "checked_at": datetime.now(timezone.utc).isoformat(),
    }


@router.get("/students")
def students(
    user: AdminUser, q: str = Query(default="", max_length=120),
    page: int = Query(default=1, ge=1),
    status: Literal["all", "approved", "pending", "rejected"] = "all",
):
    params = {
        "select": "id,email,role,approval_status,created_at",
        "order": "created_at.desc,id.asc", "limit": "50", "offset": str((page - 1) * 50),
    }
    if status != "all":
        params["approval_status"] = "eq." + status
    if q.strip():
        # Search email text without allowing PostgREST filter syntax.
        term = re.sub(r"[^a-zA-Z0-9@._+\-]", "", q.strip())
        if not term:
            return {"students": [], "total": 0, "page": page}
        params["email"] = "ilike.*" + term.replace("_", r"\_") + "*"
    rows, content_range = supabase("GET", params)
    with connection() as db:
        for row in rows:
            local = db.execute("""
                SELECT g.github_username,
                    COALESCE(s.suspended, 0) AS suspended,
                    (SELECT COUNT(*) FROM labs WHERE student_id = ?) AS active_labs
                FROM (SELECT ? AS id) u
                LEFT JOIN github_connections g ON g.student_id = u.id
                LEFT JOIN admin_suspensions s ON s.student_id = u.id
            """, (row["id"], row["id"])).fetchone()
            row.update(dict(local))
    total = content_range.rsplit("/", 1)[-1]
    return {"students": rows, "total": int(total) if total.isdigit() else None, "page": page}


class AdminPromotion(BaseModel):
    email: str


@router.post("/administrators")
def promote_admin(payload: AdminPromotion, user: AdminUser):
    from backend.app.services.admin_store import is_suspended

    email = payload.email.strip().lower()
    if len(email) > 254 or re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email) is None:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")

    profiles, _ = supabase(
        "GET",
        {"email": "eq." + email, "select": "id,email,role,approval_status", "limit": "2"},
    )
    if len(profiles) != 1:
        raise HTTPException(status_code=404, detail="No unique existing profile found for this email.")
    profile = profiles[0]
    target = profile["id"]
    if profile.get("approval_status") != "approved":
        raise HTTPException(status_code=400, detail="Approve this account before granting admin access.")
    if is_suspended(target):
        raise HTTPException(status_code=400, detail="Restore this account before granting admin access.")
    if profile.get("role") == "admin":
        return {"email": profile["email"], "status": "already_admin"}
    if profile.get("role") != "student":
        raise HTTPException(status_code=400, detail="This account cannot be promoted here.")

    activity("admin.promote", user, target, "requested", {"email": email})
    updated, _ = supabase(
        "PATCH",
        {"id": "eq." + target, "role": "eq.student", "approval_status": "eq.approved"},
        {"role": "admin"},
    )
    if len(updated) != 1 or updated[0].get("role") != "admin":
        raise HTTPException(status_code=409, detail="Account changed; refresh and retry.")
    activity("admin.promote", user, target, details={"email": email})
    return {"email": email, "status": "promoted"}


class StudentAction(BaseModel):
    action: Literal["approve", "reject", "suspend", "restore"]


@router.post("/students/{student_id}/access")
def change_access(student_id: UUID, payload: StudentAction, user: AdminUser):
    target = str(student_id)
    if target == user.id:
        raise HTTPException(status_code=400, detail="You cannot change your own access here.")
    profiles, _ = supabase("GET", {"id": "eq." + target, "select": "id,email,role,approval_status"})
    if not profiles:
        raise HTTPException(status_code=404, detail="Student not found.")
    profile = profiles[0]
    if profile.get("role") != "student":
        raise HTTPException(status_code=400, detail="This page only changes student access.")
    action = payload.action
    activity("student." + action, user, target, "requested")
    if action in ("approve", "reject"):
        value = "approved" if action == "approve" else "rejected"
        updated, _ = supabase(
            "PATCH", {"id": "eq." + target, "role": "eq.student"},
            {"approval_status": value},
        )
        if len(updated) != 1:
            raise HTTPException(status_code=409, detail="Student changed; refresh and retry.")
    else:
        with connection() as db:
            db.execute("""
                INSERT INTO admin_suspensions(student_id, suspended, updated_at, updated_by)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(student_id) DO UPDATE SET
                    suspended = excluded.suspended, updated_at = excluded.updated_at,
                    updated_by = excluded.updated_by
            """, (target, int(action == "suspend"), datetime.now(timezone.utc).isoformat(), user.id))
    activity("student." + action, user, target, details={"email": profile.get("email")})
    return {"status": "updated"}


@router.get("/labs")
def labs(user: AdminUser, page: int = Query(default=1, ge=1)):
    with connection() as db:
        total = db.execute("SELECT COUNT(*) FROM labs").fetchone()[0]
        rows = db.execute("""
            SELECT l.id, l.status, l.created_at, l.last_activity_at, s.email,
                   r.full_name AS repository,
                   e.outcome AS timeout_outcome, e.message AS timeout_message
            FROM labs l
            LEFT JOIN students s ON s.id = l.student_id
            LEFT JOIN github_repositories r ON r.id = l.github_repository_id
            LEFT JOIN lab_timeout_events e ON e.lab_id = l.id
            ORDER BY l.created_at DESC LIMIT 50 OFFSET ?
        """, ((page - 1) * 50,)).fetchall()
    return {"labs": [dict(row) for row in rows], "total": total, "page": page}


@router.get("/labs/{lab_id}/resources")
def lab_resources(lab_id: UUID, user: AdminUser, request: Request):
    with connection() as db:
        row = db.execute(
            "SELECT container_id FROM labs WHERE id = ?", (str(lab_id),)
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Lab not found.")
    try:
        container = request.app.state.docker_client.containers.get(row["container_id"])
        stats = container.stats(stream=False)
        current = stats.get("cpu_stats", {})
        previous = stats.get("precpu_stats", {})
        used = current.get("cpu_usage", {}).get("total_usage", 0)
        old_used = previous.get("cpu_usage", {}).get("total_usage", 0)
        system_delta = current.get("system_cpu_usage", 0) - previous.get("system_cpu_usage", 0)
        cores = current.get("online_cpus") or len(
            current.get("cpu_usage", {}).get("percpu_usage", [])
        ) or 1
        cpu = max(0, used - old_used) / system_delta * cores * 100 if system_delta > 0 else 0
        memory = stats.get("memory_stats", {})
        cache = memory.get("stats", {}).get("inactive_file", memory.get("stats", {}).get("cache", 0))
        return {
            "cpu_percent": round(cpu, 1),
            "memory_used": max(0, memory.get("usage", 0) - cache),
            "memory_limit": memory.get("limit", 0),
            "processes": stats.get("pids_stats", {}).get("current", 0),
        }
    except Exception:
        raise HTTPException(status_code=503, detail="Lab resource usage is unavailable.") from None


class LabTermination(BaseModel):
    mode: Literal["save", "discard"]


@router.post("/labs/{lab_id}/terminate")
def terminate_lab(lab_id: UUID, payload: LabTermination, user: AdminUser, request: Request):
    import docker
    from backend.app.services.single_lab_service import student_lab_lock

    target = str(lab_id)
    with connection() as db:
        row = db.execute(
            "SELECT student_id, container_id, status, github_repository_id "
            "FROM labs WHERE id = ?", (target,),
        ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Lab already closed.")
    if row["status"] != "running":
        raise HTTPException(status_code=409, detail="This lab is busy saving or closing. Refresh shortly.")

    owner, container_id = row["student_id"], row["container_id"]
    action = "lab.save_terminate" if payload.mode == "save" else "lab.discard_terminate"

    if payload.mode == "save":
        if not row["github_repository_id"]:
            raise HTTPException(
                status_code=400,
                detail="No GitHub repository is connected. The lab has been kept.",
            )
        activity(action, user, target, "requested")
        worker = request.app.state.inactivity_service
        completed = worker.cleanup_lab(target, container_id, force=True)
        state = worker.session_status(target, owner)
        if not completed or not state or state.get("timeout_outcome") != "saved":
            activity(action, user, target, "failed")
            raise HTTPException(
                status_code=502,
                detail="Saving and pushing could not be verified. The lab was not terminated by this action.",
            )
        message = state["message"]
    else:
        activity(action, user, target, "requested")
        with student_lab_lock(owner):
            try:
                with connection() as db:
                    db.execute("BEGIN IMMEDIATE")
                    current = db.execute(
                        "SELECT status, container_id FROM labs WHERE id = ?", (target,),
                    ).fetchone()
                    if current is None:
                        raise HTTPException(status_code=404, detail="Lab already closed.")
                    if current["status"] != "running" or current["container_id"] != container_id:
                        raise HTTPException(status_code=409, detail="Lab changed or is busy. Refresh and retry.")
                    try:
                        request.app.state.docker_client.containers.get(container_id).remove(force=True)
                    except docker.errors.NotFound:
                        pass
                    message = (
                        "Your lab was terminated by an administrator without saving "
                        "or pushing its remaining changes."
                    )
                    db.execute("""
                        INSERT INTO lab_timeout_events
                        (lab_id, student_id, outcome, message)
                        VALUES (?, ?, 'terminated_unsaved', ?)
                        ON CONFLICT(lab_id) DO UPDATE SET
                            outcome = excluded.outcome, message = excluded.message
                    """, (target, owner, message))
                    db.execute("DELETE FROM labs WHERE id = ?", (target,))
            except HTTPException:
                raise
            except Exception:
                activity(action, user, target, "failed")
                raise HTTPException(
                    status_code=502,
                    detail="Termination could not be completed. Refresh to check the lab.",
                ) from None

    activity(action, user, target)
    return {"status": "terminated", "message": message}


@router.get("/activity")
def history(user: AdminUser, page: int = Query(default=1, ge=1)):
    with connection() as db:
        total = db.execute("SELECT COUNT(*) FROM admin_activity").fetchone()[0]
        rows = db.execute("""
            SELECT id, occurred_at, actor_email, action, target_id, outcome
            FROM admin_activity ORDER BY id DESC LIMIT 50 OFFSET ?
        """, ((page - 1) * 50,)).fetchall()
    return {"events": [dict(row) for row in rows], "total": total, "page": page}


@router.get("/health")
def health(user: AdminUser, request: Request):
    def check(name, operation):
        started = time.monotonic()
        try:
            detail = operation()
            return {"name": name, "status": "healthy", "detail": detail,
                    "latency_ms": round((time.monotonic() - started) * 1000)}
        except Exception:
            return {"name": name, "status": "unavailable",
                    "detail": "Check service configuration and logs.", "latency_ms": None}

    def web(url, headers=None):
        r = requests.get(url, headers=headers, timeout=5)
        if not r.ok:
            raise RuntimeError("Service unavailable")
        return "Reachable"

    def database():
        profile_count()
        return "Profile queries working"

    def local_database():
        with connection() as db:
            db.execute("SELECT 1").fetchone()
        return "Connected"

    def gui():
        image = request.app.state.docker_client.images.get("wpl-student:dev")
        if not image.id:
            raise RuntimeError("Student image missing")
        return "Student image available; GUI starts on demand"

    checks = [
        ("Backend", lambda: "Responding"),
        ("Local database", local_database),
        ("Docker", lambda: "Responding" if request.app.state.docker_client.ping() else
         (_ for _ in ()).throw(RuntimeError())),
        ("Supabase Auth", lambda: web(
            os.getenv("SUPABASE_URL", "").rstrip("/") + "/auth/v1/health",
            {"apikey": os.getenv("SUPABASE_PUBLISHABLE_KEY", "")},
        )),
        ("Supabase database API", database),
        ("GitHub API", lambda: web("https://api.github.com", {"User-Agent": "WiByte-Admin"})),
        ("GUI environment", gui),
    ]
    with ThreadPoolExecutor(max_workers=7) as pool:
        results = list(pool.map(lambda item: check(*item), checks))
    return {"services": results, "checked_at": datetime.now(timezone.utc).isoformat()}


def install_activity_tracking(app):
    @app.middleware("http")
    async def track(request, call_next):
        response = await call_next(request)
        path = request.url.path
        action = None
        target = None
        if request.method == "POST" and path == "/labs":
            action = "lab.create"
        elif request.method == "DELETE" and re.fullmatch(r"/labs/[a-f0-9-]+", path):
            action, target = "lab.close", path.rsplit("/", 1)[-1]
        else:
            match = re.fullmatch(r"/github/labs/([a-f0-9-]+)/git/(commit|push|pull)", path)
            if request.method == "POST" and match:
                target, operation = match.groups()
                action = "git." + operation
        if action:
            try:
                await asyncio.to_thread(
                    activity, action, getattr(request.state, "current_user", None),
                    target, "success" if response.status_code < 400 else "failed",
                    {"http_status": response.status_code},
                )
            except Exception:
                import logging
                logging.getLogger(__name__).exception("Could not record activity")
        if path.startswith("/admin/"):
            response.headers["Cache-Control"] = "no-store"
        return response
