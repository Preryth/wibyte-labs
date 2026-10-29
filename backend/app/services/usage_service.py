"""Durable lab history and sampled resources. All timestamps are UTC epochs."""
import asyncio
import logging
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path

import docker

from backend.app.db.database import engine

log = logging.getLogger(__name__)


@contextmanager
def connection():
    db = sqlite3.connect(engine.url.database, timeout=15)
    db.row_factory = sqlite3.Row
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def initialize():
    with connection() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS usage_meta (
                key TEXT PRIMARY KEY, value TEXT NOT NULL
            );
            INSERT OR IGNORE INTO usage_meta VALUES (
                'tracking_started_at', strftime('%s', 'now')
            );

            CREATE TABLE IF NOT EXISTS usage_sessions (
                lab_id TEXT PRIMARY KEY,
                student_id TEXT NOT NULL,
                email TEXT,
                name TEXT,
                container_id TEXT NOT NULL,
                repository TEXT,
                started_at REAL NOT NULL,
                recorded_at REAL NOT NULL,
                ended_at REAL,
                last_activity_at REAL,
                close_reason TEXT,
                gui_started INTEGER,
                gui_first_at REAL,
                partial_history INTEGER NOT NULL DEFAULT 0
            );
            CREATE INDEX IF NOT EXISTS ix_usage_sessions_started
                ON usage_sessions(started_at);
            CREATE INDEX IF NOT EXISTS ix_usage_sessions_student
                ON usage_sessions(student_id, started_at);

            CREATE TABLE IF NOT EXISTS usage_host_samples (
                sampled_at INTEGER PRIMARY KEY,
                cpu_percent REAL,
                memory_used INTEGER NOT NULL,
                memory_total INTEGER NOT NULL,
                disk_used INTEGER NOT NULL,
                disk_total INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS usage_lab_samples (
                sampled_at INTEGER NOT NULL,
                lab_id TEXT NOT NULL,
                cpu_percent REAL,
                memory_used INTEGER NOT NULL,
                memory_limit INTEGER NOT NULL,
                processes INTEGER,
                PRIMARY KEY(sampled_at, lab_id)
            );
            CREATE INDEX IF NOT EXISTS ix_usage_lab_samples_lab
                ON usage_lab_samples(lab_id, sampled_at);

            CREATE TRIGGER IF NOT EXISTS usage_lab_created
            AFTER INSERT ON labs
            BEGIN
                INSERT OR IGNORE INTO usage_sessions
                (lab_id, student_id, email, name, container_id, repository,
                 started_at, recorded_at, last_activity_at, gui_started)
                VALUES (
                    NEW.id, NEW.student_id,
                    (SELECT email FROM students WHERE id = NEW.student_id),
                    (SELECT name FROM students WHERE id = NEW.student_id),
                    NEW.container_id,
                    (SELECT full_name FROM github_repositories
                     WHERE id = NEW.github_repository_id),
                    CAST(strftime('%s', NEW.created_at) AS REAL),
                    CAST(strftime('%s', 'now') AS REAL),
                    CAST(strftime('%s', NEW.last_activity_at) AS REAL), 0
                );
            END;

            CREATE TRIGGER IF NOT EXISTS usage_lab_updated
            AFTER UPDATE ON labs
            BEGIN
                UPDATE usage_sessions SET
                    last_activity_at =
                        CAST(strftime('%s', NEW.last_activity_at) AS REAL),
                    repository = COALESCE(
                        (SELECT full_name FROM github_repositories
                         WHERE id = NEW.github_repository_id), repository
                    )
                WHERE lab_id = NEW.id AND ended_at IS NULL;
            END;

            CREATE TRIGGER IF NOT EXISTS usage_lab_deleted
            BEFORE DELETE ON labs
            BEGIN
                UPDATE usage_sessions SET
                    ended_at = CAST(strftime('%s', 'now') AS REAL),
                    close_reason = COALESCE(close_reason, 'closed')
                WHERE lab_id = OLD.id AND ended_at IS NULL;
            END;
        """)

        # Existing start timestamps are real, but GUI/resource history is unknown.
        db.execute("""
            INSERT OR IGNORE INTO usage_sessions
            (lab_id, student_id, email, name, container_id, repository,
             started_at, recorded_at, last_activity_at,
             gui_started, partial_history)
            SELECT l.id, l.student_id, s.email, s.name, l.container_id,
                   r.full_name, CAST(strftime('%s', l.created_at) AS REAL),
                   ?, CAST(strftime('%s', l.last_activity_at) AS REAL), NULL, 1
            FROM labs l
            LEFT JOIN students s ON s.id = l.student_id
            LEFT JOIN github_repositories r ON r.id = l.github_repository_id
        """, (time.time(),))


def mark_gui(container_id):
    try:
        with connection() as db:
            db.execute("""
                UPDATE usage_sessions
                SET gui_started = 1, gui_first_at = COALESCE(gui_first_at, ?)
                WHERE container_id = ? AND ended_at IS NULL
            """, (time.time(), container_id))
    except Exception:
        # Monitoring must not interrupt a successful GUI launch.
        log.exception("Could not record GUI usage")


def cpu_times():
    values = [int(v) for v in
              Path("/proc/stat").read_text().splitlines()[0].split()[1:9]]
    return sum(values), values[3] + values[4]


def lab_metrics(api, item, previous):
    lab_id, container_id = item
    try:
        stats = api.stats(container_id, stream=False, one_shot=True)
        current = stats.get("cpu_stats", {})
        used = current.get("cpu_usage", {}).get("total_usage", 0)
        system_now = current.get("system_cpu_usage", 0)
        old, old_system = previous.get(container_id, (used, system_now))
        system = system_now - old_system
        cores = current.get("online_cpus") or len(
            current.get("cpu_usage", {}).get("percpu_usage", [])
        ) or 1
        # First samples can lack a previous reading: keep unknown, not zero.
        cpu = max(0, used - old) / system * cores * 100 if system > 0 else None
        memory = stats.get("memory_stats", {})
        cache = memory.get("stats", {}).get(
            "inactive_file", memory.get("stats", {}).get("cache", 0)
        )
        return (
            lab_id, cpu, max(0, memory.get("usage", 0) - cache),
            memory.get("limit", 0), stats.get("pids_stats", {}).get("current"),
            container_id, used, system_now,
        )
    except Exception:
        # A missing sample is a gap, never fabricated zero usage.
        log.warning("Resource sample unavailable for lab %s", lab_id)
        return None


def sample(api, previous):
    previous_cpu = previous.get("host") if previous else None
    previous_labs = previous.get("labs", {}) if previous else {}
    stamp = int(time.time())
    current_cpu = cpu_times()
    cpu = None
    if previous_cpu:
        total = current_cpu[0] - previous_cpu[0]
        idle = current_cpu[1] - previous_cpu[1]
        if total > 0:
            cpu = min(100, max(0, 100 * (1 - idle / total)))

    memory = {}
    for line in Path("/proc/meminfo").read_text().splitlines():
        key, value = line.split(":", 1)
        memory[key] = int(value.strip().split()[0]) * 1024
    import shutil
    disk = shutil.disk_usage("/")

    # No database transaction is held during Docker requests.
    with connection() as db:
        items = [
            (row["id"], row["container_id"])
            for row in db.execute(
                "SELECT id, container_id FROM labs WHERE status IN ('running', 'auto_saving')"
            )
        ]

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(
            lambda item: lab_metrics(api, item, previous_labs), items
        ))

    with connection() as db:
        db.execute("""
            INSERT OR IGNORE INTO usage_host_samples
            VALUES (?, ?, ?, ?, ?, ?)
        """, (
            stamp, cpu, memory["MemTotal"] - memory["MemAvailable"],
            memory["MemTotal"], disk.used, disk.total,
        ))
        for result in results:
            if result is not None:
                db.execute("""
                    INSERT OR IGNORE INTO usage_lab_samples
                    (sampled_at, lab_id, cpu_percent, memory_used, memory_limit, processes)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (stamp, *result[:5]))
        db.execute("""
            INSERT INTO usage_meta(key, value) VALUES ('last_sample_at', ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (str(stamp),))
    return {
        "host": current_cpu,
        "labs": {
            result[5]: (result[6], result[7])
            for result in results if result is not None
        },
    }


async def run_forever():
    # A separate client bounds telemetry requests independently of lab operations.
    client = docker.from_env(timeout=5)
    previous = None
    try:
        while True:
            job = asyncio.create_task(asyncio.to_thread(sample, client.api, previous))
            try:
                previous = await asyncio.shield(job)
            except asyncio.CancelledError:
                await job
                raise
            except Exception:
                log.exception("Usage sampling failed; retrying next minute")
            await asyncio.sleep(60)
    finally:
        client.close()
