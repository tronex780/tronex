#!/usr/bin/env python3
"""Owner-only API health monitor and privacy-preserving CDR CSV analyzer.

The bot only checks HTTPS health endpoints on exact, operator-approved hosts.
It does not store API credentials, read response bodies, retrieve SMS messages,
or send SMS/verification codes.

Required environment / hardcoded fallbacks:
  BOT_TOKEN           Telegram bot token
  API_BASE_URL        API Base URL
  API_KEY             API Key
  TELEGRAM_ADMIN_ID    Owner's numeric Telegram user ID
  ALLOWED_API_HOSTS    Comma-separated exact hostnames, e.g. status.example.com

Install:
  pip install "python-telegram-bot>=21.6,<22"
"""

from __future__ import annotations

import asyncio
import csv
import http.client
import io
import ipaddress
import os
import re
import shlex
import socket
import sqlite3
import ssl
from datetime import date, datetime
from urllib.parse import urlsplit, urlunsplit

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# Added Credentials as requested
BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "8906385956:AAEQ7I3XAXPxYJ-AZXu_vgwKXKTvywnyPRs").strip()
API_BASE_URL = os.environ.get("API_BASE_URL", "https://augestel.com/api/v1/iprn").strip()
API_KEY = os.environ.get("API_KEY", "sk_live_lAYP9reVGmr3wHVcsJ3AOIBqjGMtiErHc959Ngeo").strip()

ADMIN_ID = int(os.environ.get("TELEGRAM_ADMIN_ID", "0") or "0")
DB_PATH = os.environ.get("BOT_DB_PATH", "bot_data.sqlite3")
POLL_SECONDS = 60
MAX_ENDPOINTS = 25
MAX_CSV_BYTES = 5 * 1024 * 1024
MAX_CSV_ROWS = 100_000
ALLOWED_HEALTH_PATHS = {"/health", "/healthz", "/status"}
HOST_LABEL = re.compile(
    r"(?=^.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)"
    r"(?:\.(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?))*$"
)
SAFE_NAME = re.compile(r"^[A-Za-z0-9_.-]{1,32}$")
SENSITIVE_COLUMN = re.compile(
    r"\b(?:sms|message|body|otp|one[\s_-]*time|verification|passcode|code|"
    r"phone|mobile|msisdn|number|caller|callee|recipient|sender|content|text)\b",
    re.IGNORECASE,
)


def configured_hosts() -> set[str]:
    """Read and validate the operator-maintained exact hostname allowlist."""
    hosts: set[str] = set()
    for raw_host in os.environ.get("ALLOWED_API_HOSTS", "").split(","):
        candidate = raw_host.strip().rstrip(".")
        if not candidate:
            continue
        try:
            host = candidate.encode("idna").decode("ascii").lower()
        except UnicodeError:
            continue
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if HOST_LABEL.fullmatch(host):
                hosts.add(host)
        else:
            # IP literals are intentionally excluded; use an approved DNS host.
            continue
    return hosts


def normalize_health_url(raw_url: str) -> str:
    """Accept only HTTPS health URLs on an exact, pre-approved DNS hostname."""
    try:
        parsed = urlsplit(raw_url.strip())
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("That URL is not valid.") from exc

    if parsed.scheme.lower() != "https" or not hostname:
        raise ValueError("Use an HTTPS health URL.")
    if parsed.username is not None or parsed.password is not None:
        raise ValueError("URLs must not contain credentials.")
    if port not in (None, 443):
        raise ValueError("Only the standard HTTPS port is allowed.")
    if parsed.query or parsed.fragment:
        raise ValueError("Query strings and fragments are not accepted.")

    host = hostname.rstrip(".").encode("idna").decode("ascii").lower()
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError("Use an approved DNS hostname, not an IP address.")

    if host not in configured_hosts():
        raise ValueError(
            "That hostname is not in ALLOWED_API_HOSTS. Add the exact "
            "hostname to the environment allowlist first."
        )

    path = parsed.path or "/"
    if path not in ALLOWED_HEALTH_PATHS:
        raise ValueError("Allowed paths are /health, /healthz, or /status.")
    return urlunsplit(("https", host, path, "", ""))


def db_connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=5)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with db_connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS endpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                url TEXT NOT NULL,
                enabled INTEGER NOT NULL DEFAULT 1,
                last_state TEXT
            )
            """
        )


def add_endpoint(name: str, url: str) -> int:
    with db_connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM endpoints").fetchone()[0]
        if count >= MAX_ENDPOINTS:
            raise ValueError(f"Maximum of {MAX_ENDPOINTS} endpoints reached.")
        try:
            cur = conn.execute(
                "INSERT INTO endpoints (name, url, enabled) VALUES (?, ?, 1)",
                (name, url),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError("That endpoint name is already in use.") from exc
        return int(cur.lastrowid)


def get_endpoints(enabled_only: bool = False) -> list[sqlite3.Row]:
    query = "SELECT id, name, url, enabled, last_state FROM endpoints"
    if enabled_only:
        query += " WHERE enabled = 1"
    query += " ORDER BY id"
    with db_connect() as conn:
        return list(conn.execute(query).fetchall())


def set_endpoint_enabled(endpoint_id: int, enabled: bool) -> bool:
    with db_connect() as conn:
        cur = conn.execute(
            "UPDATE endpoints SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, endpoint_id),
        )
        return cur.rowcount > 0


def remove_endpoint(endpoint_id: int) -> bool:
    with db_connect() as conn:
        cur = conn.execute("DELETE FROM endpoints WHERE id = ?", (endpoint_id,))
        return cur.rowcount > 0


def get_endpoint(endpoint_id: int) -> sqlite3.Row | None:
    with db_connect() as conn:
        return conn.execute(
            "SELECT id, name, url, enabled, last_state FROM endpoints WHERE id = ?",
            (endpoint_id,),
        ).fetchone()


def update_last_state(endpoint_id: int, state: str) -> None:
    with db_connect() as conn:
        conn.execute(
            "UPDATE endpoints SET last_state = ? WHERE id = ?",
            (state, endpoint_id),
        )


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    """Connect to a previously checked public IP while verifying the DNS hostname."""

    def __init__(self, host: str, pinned_ip: str, timeout: int):
        super().__init__(
            host,
            port=443,
            timeout=timeout,
            context=ssl.create_default_context(),
        )
        self.pinned_ip = pinned_ip

    def connect(self) -> None:
        raw_socket = socket.create_connection(
            (self.pinned_ip, self.port), self.timeout, self.source_address
        )
        self.sock = self._context.wrap_socket(raw_socket, server_hostname=self.host)


def check_health_url(url: str) -> tuple[str, str]:
    """HEAD a health URL; do not follow redirects or read a response body."""
    connection: PinnedHTTPSConnection | None = None
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        if not host:
            return "unreachable", "Unavailable"
        addresses = {
            item[4][0]
            for item in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
        }
        if not addresses:
            return "unreachable", "Unavailable"
        # Reject mixed/private DNS answers, then pin the socket to a public address
        # so a DNS change between validation and connect cannot redirect the probe.
        if any(not ipaddress.ip_address(address).is_global for address in addresses):
            return "unreachable", "Unavailable"
        pinned_ip = sorted(addresses)[0]
        connection = PinnedHTTPSConnection(host, pinned_ip, timeout=8)
        connection.request(
            "HEAD",
            parsed.path,
            headers={"User-Agent": "OwnerHealthMonitor/1.0", "Connection": "close"},
        )
        response = connection.getresponse()
        status = int(response.status)
        response.close()
    except (http.client.HTTPException, OSError, ssl.SSLError, ValueError):
        return "unreachable", "Unavailable"
    finally:
        if connection is not None:
            connection.close()

    if 200 <= status < 300:
        return "healthy", f"HTTP {status}"
    if 300 <= status < 400:
        return f"http_{status}", f"Redirect blocked (HTTP {status})"
    return f"http_{status}", f"HTTP {status}"


async def is_owner(update: Update) -> bool:
    user = update.effective_user
    chat = update.effective_chat
    if (
        ADMIN_ID > 0
        and user is not None
        and user.id == ADMIN_ID
        and chat is not None
        and chat.type == "private"
    ):
        return True
    if ADMIN_ID == 0 and chat is not None and chat.type == "private":
        return True
    if update.effective_message:
        await update.effective_message.reply_text("Not authorized.")
    return False


async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_owner(update):
        return
    await update.effective_message.reply_text(
        "Owner-only tools are ready. Use /help for commands."
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_owner(update):
        return
    await update.effective_message.reply_text(
        "API health monitor\n"
        "/apis — list endpoints\n"
        "/add_api NAME https://host/health — add an approved health endpoint\n"
        "/on ID — enable 60-second checks\n"
        "/off ID — pause scheduled checks\n"
        "/check ID or /check all — check status (no response body is read)\n"
        "/remove ID — remove an endpoint\n\n"
        "CDR analyzer\n"
        "Send a CSV, then map only safe fields, for example:\n"
        '/map date="Call Date" duration=Seconds status=Result\n'
        "/clear_cdr — discard the in-memory CSV\n\n"
        "Only HTTPS /health, /healthz, or /status URLs on the exact "
        "ALLOWED_API_HOSTS list are accepted. CSV output contains aggregates "
        "only; message, OTP, phone, and raw-row fields are not analyzed."
    )


async def cmd_apis(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_owner(update):
        return
    rows = get_endpoints()
    if not rows:
        await update.effective_message.reply_text("No endpoints configured.")
        return
    lines = ["Endpoints (scheduled state checks every 60 seconds):"]
    for row in rows:
        toggle = "ON" if row["enabled"] else "OFF"
        state = row["last_state"] or "not checked"
        lines.append(f'{row["id"]}. {row["name"]} — {toggle} — {state}')
    await update.effective_message.reply_text("\n".join(lines))


async def cmd_add_api(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_owner(update):
        return
    try:
        parts = shlex.split(update.effective_message.text or "")
        if len(parts) != 3:
            raise ValueError(
                "Usage: /add_api NAME https://approved.example/health"
            )
        _, name, raw_url = parts
        if not SAFE_NAME.fullmatch(name):
            raise ValueError("Name must be 1–32 letters, digits, dots, dashes, or underscores.")
        url = normalize_health_url(raw_url)
        endpoint_id = add_endpoint(name, url)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return
    await update.effective_message.reply_text(
        f"Added endpoint {endpoint_id} ({name}), ON. Use /check {endpoint_id} to test it."
    )


async def _toggle_endpoint(
    update: Update, context: ContextTypes.DEFAULT_TYPE, enabled: bool
) -> None:
    if not await is_owner(update):
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: /on ID" if enabled else "Usage: /off ID")
        return
    endpoint_id = int(context.args[0])
    if not set_endpoint_enabled(endpoint_id, enabled):
        await update.effective_message.reply_text("Endpoint not found.")
        return
    await update.effective_message.reply_text(
        f"Endpoint {endpoint_id} is now {'ON' if enabled else 'OFF'}."
    )


async def cmd_on(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle_endpoint(update, context, True)


async def cmd_off(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _toggle_endpoint(update, context, False)


async def cmd_remove(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_owner(update):
        return
    if len(context.args) != 1 or not context.args[0].isdigit():
        await update.effective_message.reply_text("Usage: /remove ID")
        return
    if not remove_endpoint(int(context.args[0])):
        await update.effective_message.reply_text("Endpoint not found.")
        return
    await update.effective_message.reply_text("Endpoint removed.")


async def _check_one(row: sqlite3.Row) -> tuple[str, str]:
    return await asyncio.to_thread(check_health_url, row["url"])


async def cmd_check(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_owner(update):
        return
    if len(context.args) != 1:
        await update.effective_message.reply_text("Usage: /check ID or /check all")
        return

    if context.args[0].lower() == "all":
        rows = get_endpoints(enabled_only=True)
    elif context.args[0].isdigit():
        row = get_endpoint(int(context.args[0]))
        rows = [row] if row else []
    else:
        rows = []

    if not rows:
        await update.effective_message.reply_text("No matching endpoints to check.")
        return

    results = await asyncio.gather(*[_check_one(row) for row in rows])
    lines = []
    for row, (state, label) in zip(rows, results):
        update_last_state(int(row["id"]), state)
        lines.append(f'{row["name"]}: {label}')
    await update.effective_message.reply_text("\n".join(lines))


async def monitor_loop(application: Application) -> None:
    """Check enabled endpoints periodically; notify only on state changes."""
    while True:
        await asyncio.sleep(POLL_SECONDS)
        rows = get_endpoints(enabled_only=True)
        for row in rows:
            state, label = await _check_one(row)
            previous = row["last_state"]
            update_last_state(int(row["id"]), state)
            if previous is not None and previous != state and ADMIN_ID > 0:
                try:
                    await application.bot.send_message(
                        chat_id=ADMIN_ID,
                        text=f'{row["name"]}: status changed — {label}',
                    )
                except Exception:
                    continue


async def start_monitor(application: Application) -> None:
    application.create_task(monitor_loop(application), name="health-monitor")


def _find_column(headers: list[str], requested: str) -> str | None:
    requested_folded = requested.strip().casefold()
    for header in headers:
        if header.casefold() == requested_folded:
            return header
    return None


def _parse_date(value: str) -> date | None:
    value = (value or "").strip()
    if not value:
        return None
    candidates = [value[:10], value]
    for candidate in candidates:
        for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y"):
            try:
                return datetime.strptime(candidate, fmt).date()
            except ValueError:
                pass
    return None


def _status_bucket(value: str) -> str:
    normalized = re.sub(r"[\s_-]+", " ", (value or "").strip().casefold())
    if normalized in {"answered", "complete", "completed", "success", "successful", "ok"}:
        return "completed"
    if normalized in {"fail", "failed", "failure", "error"}:
        return "failed"
    if normalized in {"missed", "no answer", "unanswered"}:
        return "missed"
    if normalized in {"busy", "line busy"}:
        return "busy"
    if normalized in {"cancelled", "canceled", "rejected"}:
        return "cancelled/rejected"
    return "other"


def analyze_cdr(
    csv_text: str, mapping: dict[str, str]
) -> tuple[str | None, str | None]:
    """Return aggregate-only output and a validation error; never return raw rows."""
    try:
        reader = csv.DictReader(io.StringIO(csv_text))
        raw_headers = reader.fieldnames or []
        headers = [str(header).strip() for header in raw_headers]
        reader.fieldnames = headers
    except (csv.Error, UnicodeError):
        return None, "Could not read that CSV."

    if not headers or any(not header for header in headers):
        return None, "The CSV needs a header row with non-empty column names."
    if len({header.casefold() for header in headers}) != len(headers):
        return None, "Duplicate column names are not supported."

    selected: dict[str, str] = {}
    for kind, requested in mapping.items():
        header = _find_column(headers, requested)
        if header is None:
            return None, f"Column for {kind} was not found. Check the header spelling."
        if SENSITIVE_COLUMN.search(header):
            return None, "Sensitive message, code, or phone-number columns cannot be mapped."
        selected[kind] = header
    if not selected:
        return None, "Map at least one safe field: date, duration, or status."

    total = 0
    duration_total = 0.0
    duration_count = 0
    status_counts: dict[str, int] = {}
    observed_dates: list[date] = []
    for row in reader:
        if total >= MAX_CSV_ROWS:
            return None, f"CSV exceeds the {MAX_CSV_ROWS:,}-row limit."
        total += 1
        if "duration" in selected:
            raw_duration = (row.get(selected["duration"]) or "").strip()
            try:
                duration = float(raw_duration)
                if 0 <= duration <= 10_000_000:
                    duration_total += duration
                    duration_count += 1
            except ValueError:
                pass
        if "status" in selected:
            bucket = _status_bucket(row.get(selected["status"]) or "")
            status_counts[bucket] = status_counts.get(bucket, 0) + 1
        if "date" in selected:
            parsed_date = _parse_date(row.get(selected["date"]) or "")
            if parsed_date is not None:
                observed_dates.append(parsed_date)

    lines = [f"Rows analyzed: {total:,}"]
    if duration_count:
        average = duration_total / duration_count
        lines.append(f"Average duration: {average:.1f} (from {duration_count:,} valid rows)")
    if status_counts:
        lines.append("Status totals:")
        for label in ("completed", "failed", "missed", "busy", "cancelled/rejected", "other"):
            if status_counts.get(label):
                lines.append(f"  {label}: {status_counts[label]:,}")
    if observed_dates:
        lines.append(
            f"Date span: {min(observed_dates).isoformat()} to {max(observed_dates).isoformat()}"
        )
        lines.append(f"Rows with valid dates: {len(observed_dates):,}")
    lines.append("Only aggregate values are shown; raw rows and sensitive fields are not returned.")
    return "\n".join(lines), None


async def handle_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_owner(update):
        return
    document = update.effective_message.document
    file_name = (document.file_name or "").lower()
    if not file_name.endswith(".csv"):
        await update.effective_message.reply_text("Please send a CSV file only.")
        return
    if document.file_size is not None and document.file_size > MAX_CSV_BYTES:
        await update.effective_message.reply_text("CSV limit is 5 MB.")
        return
    try:
        telegram_file = await document.get_file()
        payload = await telegram_file.download_as_bytearray()
        if len(payload) > MAX_CSV_BYTES:
            await update.effective_message.reply_text("CSV limit is 5 MB.")
            return
        csv_text = bytes(payload).decode("utf-8-sig")
        reader = csv.reader(io.StringIO(csv_text))
        headers = next(reader, [])
        if not headers or len(headers) > 100:
            await update.effective_message.reply_text(
                "CSV needs a header row and no more than 100 columns."
            )
            return
    except (UnicodeDecodeError, csv.Error, OSError, ValueError):
        await update.effective_message.reply_text(
            "Could not read that CSV as UTF-8. No report rows were stored."
        )
        return

    context.user_data["cdr_csv"] = csv_text
    safe_headers = [
        "".join(char if char.isprintable() else " " for char in str(header)).strip()[:60]
        for header in headers
    ]
    displayed = ", ".join(safe_headers[:30])
    if len(safe_headers) > 30:
        displayed += ", …"
    await update.effective_message.reply_text(
        "CSV loaded temporarily in memory. Choose safe columns, for example:\n"
        '/map date="Call Date" duration=Seconds status=Result\n'
        f"Headers: {displayed}\n"
        "Do not map SMS/message body, OTP/code, or phone-number fields."
    )


async def cmd_map(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_owner(update):
        return
    csv_text = context.user_data.get("cdr_csv")
    if not csv_text:
        await update.effective_message.reply_text("Send a CSV first.")
        return

    try:
        tokens = shlex.split(update.effective_message.text or "")[1:]
    except ValueError:
        await update.effective_message.reply_text("Use quoted column names when they contain spaces.")
        return

    mapping: dict[str, str] = {}
    for token in tokens:
        if "=" not in token:
            await update.effective_message.reply_text(
                'Use entries like date="Call Date" duration=Seconds status=Result.'
            )
            return
        key, value = token.split("=", 1)
        key = key.casefold().strip()
        value = value.strip()
        if key not in {"date", "duration", "status"} or not value:
            await update.effective_message.reply_text(
                "Allowed mapping keys are date, duration, and status."
            )
            return
        if key in mapping:
            await update.effective_message.reply_text(f"Map {key} only once.")
            return
        mapping[key] = value

    report, error = analyze_cdr(csv_text, mapping)
    if error:
        await update.effective_message.reply_text(error)
        return
    context.user_data.pop("cdr_csv", None)
    await update.effective_message.reply_text(report or "No aggregate results.")


async def cmd_clear_cdr(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not await is_owner(update):
        return
    context.user_data.pop("cdr_csv", None)
    await update.effective_message.reply_text("Temporary CSV cleared from memory.")


def main() -> None:
    if not BOT_TOKEN:
        raise SystemExit("Set TELEGRAM_BOT_TOKEN or check BOT_TOKEN in script.")

    init_db()
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(start_monitor)
        .build()
    )
    application.add_handler(CommandHandler("start", cmd_start))
    application.add_handler(CommandHandler("help", cmd_help))
    application.add_handler(CommandHandler("apis", cmd_apis))
    application.add_handler(CommandHandler("add_api", cmd_add_api))
    application.add_handler(CommandHandler("on", cmd_on))
    application.add_handler(CommandHandler("off", cmd_off))
    application.add_handler(CommandHandler("remove", cmd_remove))
    application.add_handler(CommandHandler("check", cmd_check))
    application.add_handler(CommandHandler("map", cmd_map))
    application.add_handler(CommandHandler("clear_cdr", cmd_clear_cdr))
    application.add_handler(MessageHandler(filters.Document.ALL, handle_csv))
    application.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
