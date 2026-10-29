import math
import time
from collections import defaultdict

from backend.app.services.usage_service import connection


def window(period, start=None, end=None):
    now = time.time()
    if period == "custom":
        if start is None or end is None or not math.isfinite(start) or not math.isfinite(end):
            raise ValueError("Choose a valid start and end time.")
        if end <= start or start > now:
            raise ValueError("The end time must follow the start time.")
        return start, min(end, now)
    end = now
    if period == "all":
        with connection() as db:
            first = db.execute("SELECT MIN(started_at) FROM usage_sessions").fetchone()[0]
            tracking = db.execute(
                "SELECT value FROM usage_meta WHERE key = 'tracking_started_at'"
            ).fetchone()
        return min(first if first is not None else now,
                   float(tracking[0]) if tracking else now) - 1, end
    return end - {"24h": 86400, "week": 604800, "month": 2592000}[period], end


def merged(intervals):
    output = []
    for start, end in sorted(intervals):
        if output and start <= output[-1][1]:
            output[-1] = (output[-1][0], max(output[-1][1], end))
        else:
            output.append((start, end))
    return output


def peaks(intervals, start, end, bins):
    """Exact interval peaks inside each bucket; intervals are half-open."""
    changes = defaultdict(int)
    for left, right in intervals:
        if right > left:
            changes[left] += 1
            changes[right] -= 1
    events = sorted(changes.items())
    index, current = 0, 0
    values = []
    step = (end - start) / bins
    for bucket in range(bins):
        left, right = start + bucket * step, start + (bucket + 1) * step
        while index < len(events) and events[index][0] <= left:
            current += events[index][1]
            index += 1
        peak = current
        while index < len(events) and events[index][0] < right:
            current += events[index][1]
            peak = max(peak, current)
            index += 1
        values.append(peak)
    return values


def selection(start, end, q, gui):
    conditions = [
        "h.started_at < ?", "COALESCE(h.ended_at, ?) > ?",
        "COALESCE(h.close_reason, '') != 'creation_failed'",
    ]
    args = [end, end, start]
    if q.strip():
        conditions.append(
            "(instr(lower(COALESCE(h.email, '')), lower(?)) > 0 "
            "OR instr(lower(COALESCE(h.name, '')), lower(?)) > 0 "
            "OR instr(lower(h.student_id), lower(?)) > 0)"
        )
        args.extend([q.strip()] * 3)
    if gui == "yes":
        conditions.append("h.gui_started = 1")
    elif gui == "no":
        conditions.append("h.gui_started = 0")
    elif gui == "unknown":
        conditions.append("h.gui_started IS NULL")
    return " AND ".join(conditions), args


def resource_series(db, start, end, bins, where, args, lab_id=None):
    step = (end - start) / bins
    host = db.execute("""
        SELECT CAST((sampled_at - ?) / ? AS INTEGER) AS bucket,
               AVG(cpu_percent) AS cpu_percent,
               MAX(cpu_percent) AS cpu_peak,
               AVG(memory_used) AS memory_used,
               MAX(memory_total) AS memory_total,
               MAX(disk_used) AS disk_used,
               MAX(disk_total) AS disk_total, COUNT(*) AS samples
        FROM usage_host_samples
        WHERE sampled_at >= ? AND sampled_at < ?
        GROUP BY bucket
    """, (start, step, start, end)).fetchall()
    extra, lab_args = (" AND s.lab_id = ?", [lab_id]) if lab_id else ("", [])
    labs = db.execute(f"""
        SELECT CAST((s.sampled_at - ?) / ? AS INTEGER) AS bucket,
               AVG(s.cpu_percent) AS cpu_percent,
               MAX(s.cpu_percent) AS cpu_peak,
               AVG(s.memory_used) AS memory_used,
               MAX(s.memory_used) AS memory_peak,
               MAX(s.memory_limit) AS memory_limit,
               MAX(s.processes) AS processes, COUNT(*) AS samples
        FROM usage_lab_samples s
        JOIN usage_sessions h ON h.lab_id = s.lab_id
        WHERE s.sampled_at >= ? AND s.sampled_at < ?
          AND {where}{extra}
        GROUP BY bucket
    """, (start, step, start, end, *args, *lab_args)).fetchall()
    return {
        "host": {row["bucket"]: dict(row) for row in host},
        "labs": {row["bucket"]: dict(row) for row in labs},
    }


def report(period="24h", q="", gui="all", page=1, start=None, end=None, lab_id=None):
    start, end = window(period, start, end)
    bins = 96 if period == "24h" else 168
    where, args = selection(start, end, q, gui)
    if lab_id:
        where += " AND h.lab_id = ?"
        args.append(lab_id)
    with connection() as db:
        rows = [dict(row) for row in db.execute(
            f"SELECT h.* FROM usage_sessions h WHERE {where} ORDER BY h.started_at DESC, h.lab_id",
            args,
        )]
        resources = resource_series(db, start, end, bins, where, args, lab_id)
        meta = dict(db.execute("SELECT key, value FROM usage_meta").fetchall())

    by_user = {}
    intervals = []
    hours = [0.0] * bins
    step = (end - start) / bins
    for row in rows:
        left = max(start, row["started_at"])
        right = min(end, row["ended_at"] if row["ended_at"] is not None else end)
        duration = max(0, right - left)
        row["range_seconds"] = duration
        row["total_seconds"] = max(
            0, (row["ended_at"] if row["ended_at"] is not None else end) - row["started_at"]
        )
        intervals.append((left, right))
        user = by_user.setdefault(row["student_id"], {
            "student_id": row["student_id"], "email": row["email"],
            "name": row["name"], "seconds": 0, "sessions": 0,
            "gui_sessions": 0, "gui_unknown": 0, "intervals": [],
        })
        user["seconds"] += duration
        user["sessions"] += 1
        user["gui_sessions"] += int(row["gui_started"] == 1)
        user["gui_unknown"] += int(row["gui_started"] is None)
        user["intervals"].append((left, right))
        first = max(0, int((left - start) / step))
        last = min(bins - 1, math.ceil((right - start) / step) - 1)
        for bucket in range(first, last + 1):
            hours[bucket] += max(
                0, min(right, start + (bucket + 1) * step) -
                max(left, start + bucket * step)
            ) / 3600

    user_intervals = [
        interval for user in by_user.values()
        for interval in merged(user["intervals"])
    ]
    lab_peaks = peaks(intervals, start, end, bins)
    user_peaks = peaks(user_intervals, start, end, bins)
    series = [{
        "at": start + bucket * step,
        "until": start + (bucket + 1) * step,
        "lab_hours": hours[bucket],
        "concurrent_labs": lab_peaks[bucket],
        "concurrent_users": user_peaks[bucket],
        "host": resources["host"].get(bucket),
        "labs": resources["labs"].get(bucket),
    } for bucket in range(bins)]

    users = sorted(by_user.values(), key=lambda user: (-user["seconds"], user["student_id"]))
    for user in users:
        user.pop("intervals")
    total_seconds = sum(row["range_seconds"] for row in rows)
    return {
        "start": start, "end": end,
        "tracking_started_at": float(meta.get("tracking_started_at", end)),
        "last_sample_at": float(meta["last_sample_at"]) if meta.get("last_sample_at") else None,
        "summary": {
            "seconds": total_seconds, "sessions": len(rows),
            "users": len(users),
            "average_seconds": total_seconds / len(rows) if rows else 0,
            "peak_users": max(user_peaks, default=0),
            "peak_labs": max(lab_peaks, default=0),
            "gui_sessions": sum(row["gui_started"] == 1 for row in rows),
            "gui_unknown": sum(row["gui_started"] is None for row in rows),
        },
        "series": series, "users": users,
        "sessions": rows[(page - 1) * 50:page * 50],
        "total": len(rows), "page": page,
    }
