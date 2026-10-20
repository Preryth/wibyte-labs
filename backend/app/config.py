"""Deployment settings shared by the backend."""
import os
from pathlib import Path
from urllib.parse import urlsplit

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Always load the same file, regardless of the startup directory.
# Explicit process environment variables take precedence.
load_dotenv(PROJECT_ROOT / "backend" / ".env", override=False)


def read_url(name, default=None):
    value = os.getenv(name, default)
    if not value:
        raise RuntimeError(f"{name} must be configured.")
    value = value.strip().rstrip("/")
    try:
        parts = urlsplit(value)
        port = parts.port
    except ValueError:
        raise RuntimeError(f"{name} has an invalid host or port.") from None
    if (
        parts.scheme not in ("http", "https")
        or not parts.hostname
        or parts.username
        or parts.password
        or parts.query
        or parts.fragment
        or any(c.isspace() for c in value)
        or (port is not None and not 1 <= port <= 65535)
    ):
        raise RuntimeError(f"{name} must be an HTTP(S) URL without credentials, query or fragment.")
    return value


PUBLIC_URL = read_url("WPL_PUBLIC_URL")
if urlsplit(PUBLIC_URL).path:
    raise RuntimeError("WPL_PUBLIC_URL must not include a path.")

API_BASE_URL = read_url("WPL_API_BASE_URL", PUBLIC_URL + "/api")
GUI_BASE_URL = read_url("WPL_GUI_BASE_URL", PUBLIC_URL)

GITHUB_CALLBACK_URL = API_BASE_URL + "/github/callback"
GITHUB_FRONTEND_URL = PUBLIC_URL

# The browser frontend is served at PUBLIC_URL.
CORS_ORIGINS = [PUBLIC_URL]

# This implementation uses SQLite, including the inactivity service.
# Relative paths resolve from the repository root.
_database_path = Path(os.getenv("WPL_DATABASE_PATH", "wpl.db")).expanduser()
DATABASE_PATH = (
    _database_path if _database_path.is_absolute()
    else PROJECT_ROOT / _database_path
).resolve()

from sqlalchemy.engine import URL
DATABASE_URL = URL.create("sqlite", database=str(DATABASE_PATH))

if urlsplit(GUI_BASE_URL).path:
    raise RuntimeError("WPL_GUI_BASE_URL must not include a path.")
GUI_HTTPS = urlsplit(GUI_BASE_URL).scheme == "https"

from decimal import Decimal, InvalidOperation
import re


def positive_integer(name, default):
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        raise RuntimeError(f"{name} must be a positive integer.") from None
    if value <= 0:
        raise RuntimeError(f"{name} must be a positive integer.")
    return value


LAB_IMAGE = os.getenv("WPL_LAB_IMAGE", "wpl-student:dev").strip()
if not LAB_IMAGE:
    raise RuntimeError("WPL_LAB_IMAGE must not be empty.")

LAB_MEMORY = os.getenv("WPL_LAB_MEMORY", "1g").strip()
if not re.fullmatch(r"[1-9][0-9]*(?:[bkmgBKMG])?", LAB_MEMORY):
    raise RuntimeError("WPL_LAB_MEMORY must be positive bytes or a value such as 512m or 1g.")

try:
    _cpu = Decimal(os.getenv("WPL_LAB_CPUS", "0.25"))
except InvalidOperation:
    raise RuntimeError("WPL_LAB_CPUS must be a positive number.") from None
if not _cpu.is_finite() or _cpu <= 0:
    raise RuntimeError("WPL_LAB_CPUS must be a positive finite number.")
_cpu_units = _cpu * 1_000_000_000
if _cpu_units != _cpu_units.to_integral_value():
    raise RuntimeError("WPL_LAB_CPUS supports at most nine decimal places.")
LAB_NANO_CPUS = int(_cpu_units)

LAB_PIDS_LIMIT = positive_integer("WPL_LAB_PIDS_LIMIT", 256)
IDLE_MINUTES = positive_integer("WPL_IDLE_MINUTES", 30)
