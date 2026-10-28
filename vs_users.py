from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any
from urllib.parse import quote


APP_ROOT = Path(__file__).resolve().parent


def _load_app_environment() -> None:
    env_file = APP_ROOT / ".env"
    if not env_file.is_file():
        return
    for raw_line in env_file.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if re.fullmatch(r"[A-Z][A-Z0-9_]*", key):
            os.environ.setdefault(key, value)


_load_app_environment()
DB_PATH = Path(os.environ.get("VS_USER_DB", str(APP_ROOT / "logs" / "vs_users.sqlite3"))).resolve()
DEFAULT_PASSWORD = os.environ.get("VS_INITIAL_USER_PASSWORD", "")
PBKDF2_ROUNDS = 310_000
SESSION_TTL = 24 * 60 * 60
RESET_TTL = 30 * 60
_DB_LOCK = threading.Lock()
_SESSION_SECRET = ""


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(DB_PATH), timeout=20)
    db.row_factory = sqlite3.Row
    return db


def normalize_username(username: str) -> str:
    value = str(username or "").strip()
    return value.lower() if "@" in value else value.upper()


def _hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${digest.hex()}"


def _verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds_text, salt_hex, expected_hex = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(rounds_text))
        return hmac.compare_digest(actual.hex(), expected_hex)
    except (ValueError, TypeError):
        return False


def _validate_password(password: str) -> str:
    value = str(password or "")
    if len(value) < 8 or len(value) > 256:
        raise ValueError("Password must contain between 8 and 256 characters.")
    return value


def _email(value: str, required: bool = False) -> str:
    result = str(value or "").strip().lower()
    if not result and not required:
        return ""
    if len(result) > 254 or not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", result):
        raise ValueError("Enter a valid email address.")
    return result


def _row_user(row: sqlite3.Row | None, include_hash: bool = False) -> dict[str, Any] | None:
    if row is None:
        return None
    result: dict[str, Any] = {
        "username": row["username"], "role": row["role"], "active": bool(row["active"]),
        "created_at": row["created_at"], "session_version": int(row["session_version"]),
        "first_name": row["first_name"], "last_name": row["last_name"], "email": row["email"],
        "totp_enabled": bool(row["totp_enabled"]),
    }
    if include_hash:
        result["password_hash"] = row["password_hash"]
        result["totp_secret"] = row["totp_secret"]
        result["totp_pending"] = row["totp_pending"]
    return result


def _add_column(db: sqlite3.Connection, table: str, name: str, definition: str) -> None:
    columns = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
    if name not in columns:
        db.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def initialize() -> None:
    global _SESSION_SECRET
    with _DB_LOCK, _connect() as db:
        db.execute("PRAGMA journal_mode=WAL")
        db.execute("""CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY, password_hash TEXT NOT NULL,
            role TEXT NOT NULL CHECK(role IN ('admin','user')), active INTEGER NOT NULL DEFAULT 1,
            session_version INTEGER NOT NULL DEFAULT 1, created_at TEXT NOT NULL
        )""")
        for name, definition in (
            ("first_name", "TEXT NOT NULL DEFAULT ''"), ("last_name", "TEXT NOT NULL DEFAULT ''"),
            ("email", "TEXT NOT NULL DEFAULT ''"), ("totp_secret", "TEXT NOT NULL DEFAULT ''"),
            ("totp_pending", "TEXT NOT NULL DEFAULT ''"), ("totp_enabled", "INTEGER NOT NULL DEFAULT 0"),
        ):
            _add_column(db, "users", name, definition)
        db.execute("""CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)""")
        db.execute("""CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT, happened_at TEXT NOT NULL, actor TEXT NOT NULL,
            action TEXT NOT NULL, target TEXT NOT NULL DEFAULT '', detail TEXT NOT NULL DEFAULT '{}'
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS activity_happened_idx ON activity(id DESC)")
        db.execute("""CREATE TABLE IF NOT EXISTS folder_owners (
            folder TEXT PRIMARY KEY, created_by TEXT NOT NULL, created_at TEXT NOT NULL,
            last_by TEXT NOT NULL, last_at TEXT NOT NULL
        )""")
        db.execute("""CREATE TABLE IF NOT EXISTS password_resets (
            token_hash TEXT PRIMARY KEY, username TEXT NOT NULL, expires_at INTEGER NOT NULL, created_at INTEGER NOT NULL
        )""")
        db.execute("CREATE INDEX IF NOT EXISTS password_resets_user_idx ON password_resets(username)")
        secret_row = db.execute("SELECT value FROM settings WHERE key='session_secret'").fetchone()
        if secret_row:
            _SESSION_SECRET = secret_row["value"]
        else:
            _SESSION_SECRET = os.environ.get("VS_DASHBOARD_SESSION_SECRET") or secrets.token_urlsafe(48)
            db.execute("INSERT INTO settings(key,value) VALUES('session_secret',?)", (_SESSION_SECRET,))
        now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
        seed = [("info@primexeu.com", "admin"), ("FG", "admin"), ("ESH", "user"), ("DM", "user"), ("EP", "user"), ("AT", "user")]
        user_count = db.execute("SELECT COUNT(*) AS n FROM users").fetchone()["n"]
        if user_count == 0:
            if not DEFAULT_PASSWORD:
                raise RuntimeError("Set VS_INITIAL_USER_PASSWORD in the server .env file before initializing a new user database.")
            for username, role in seed:
                normalized = normalize_username(username)
                email = normalized if "@" in normalized else ""
                db.execute(
                    "INSERT INTO users(username,password_hash,role,created_at,email) VALUES(?,?,?,?,?)",
                    (normalized, _hash_password(DEFAULT_PASSWORD), role, now, email),
                )


def _session_signature(value: str) -> str:
    secret = _SESSION_SECRET or os.environ.get("VS_DASHBOARD_SESSION_SECRET", "")
    return hmac.new(secret.encode("utf-8"), value.encode("utf-8"), hashlib.sha256).hexdigest()


def issue_session(username: str) -> str:
    user = get_user(username)
    if not user or not user["active"]:
        raise ValueError("User is not active.")
    value = f"{user['username']}|{user['session_version']}|{int(time.time())}|{secrets.token_urlsafe(18)}"
    return f"{value}|{_session_signature(value)}"


def get_user(username: str) -> dict[str, Any] | None:
    normalized = normalize_username(username)
    with _connect() as db:
        row = db.execute("SELECT * FROM users WHERE username=?", (normalized,)).fetchone()
    return _row_user(row, include_hash=True)


def authenticate(username: str, password: str, code: str = "") -> dict[str, Any] | None:
    user = get_user(username)
    if not user or not user["active"] or not _verify_password(str(password or ""), user["password_hash"]):
        return None
    if user["totp_enabled"] and not _verify_totp(str(user["totp_secret"]), code):
        return None
    return {key: value for key, value in user.items() if key not in {"password_hash", "totp_secret", "totp_pending"}}


def authenticate_password(username: str, password: str) -> dict[str, Any] | None:
    user = get_user(username)
    if not user or not user["active"] or not _verify_password(str(password or ""), user["password_hash"]):
        return None
    return {key: value for key, value in user.items() if key not in {"password_hash", "totp_secret", "totp_pending"}}


def create_login_challenge(username: str) -> str:
    user = get_user(username)
    if not user or not user["active"] or not user["totp_enabled"]:
        raise ValueError("A two-factor login challenge is not available.")
    payload = f"{user['username']}|{user['session_version']}|{int(time.time())}|{secrets.token_urlsafe(18)}"
    return f"{payload}|{_session_signature('login:' + payload)}"


def complete_login_challenge(challenge: str, code: str) -> dict[str, Any] | None:
    parts = str(challenge or "").split("|")
    if len(parts) != 5:
        return None
    username, version_text, timestamp_text, nonce, signature = parts
    payload = "|".join(parts[:4])
    if not nonce or not hmac.compare_digest(signature, _session_signature("login:" + payload)):
        return None
    try:
        version, timestamp = int(version_text), int(timestamp_text)
    except ValueError:
        return None
    now = int(time.time())
    if timestamp > now + 30 or now - timestamp > 300:
        return None
    user = get_user(username)
    if not user or not user["active"] or user["session_version"] != version or not user["totp_enabled"]:
        return None
    if not _verify_totp(str(user["totp_secret"]), code):
        return None
    return {key: value for key, value in user.items() if key not in {"password_hash", "totp_secret", "totp_pending"}}


def session_user(cookie_value: str) -> dict[str, Any] | None:
    parts = str(cookie_value or "").split("|")
    if len(parts) != 5:
        return None
    username, version_text, timestamp_text, nonce, signature = parts
    if not nonce or not hmac.compare_digest(signature, _session_signature("|".join(parts[:4]))):
        return None
    try:
        timestamp, version = int(timestamp_text), int(version_text)
    except ValueError:
        return None
    now = int(time.time())
    if timestamp > now + 60 or now - timestamp > SESSION_TTL:
        return None
    user = get_user(username)
    if not user or not user["active"] or user["session_version"] != version:
        return None
    return {key: value for key, value in user.items() if key not in {"password_hash", "totp_secret", "totp_pending"}}


def list_users() -> list[dict[str, Any]]:
    with _connect() as db:
        rows = db.execute("SELECT username,role,active,created_at,first_name,last_name,email,totp_enabled FROM users ORDER BY role DESC, username COLLATE NOCASE").fetchall()
    return [{**dict(row), "active": bool(row["active"]), "totp_enabled": bool(row["totp_enabled"])} for row in rows]


def _record(db: sqlite3.Connection, actor: str, action: str, target: str = "", detail: dict[str, Any] | None = None) -> None:
    db.execute(
        "INSERT INTO activity(happened_at,actor,action,target,detail) VALUES(?,?,?,?,?)",
        (time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime()), actor, action, target, json.dumps(detail or {}, ensure_ascii=False)),
    )


def record_activity(actor: str, action: str, target: str = "", detail: dict[str, Any] | None = None) -> None:
    with _DB_LOCK, _connect() as db:
        _record(db, normalize_username(actor), action, target, detail)


def record_photo_activity(actor: str, action: str, relative_path: str, detail: dict[str, Any] | None = None) -> None:
    normalized_actor = normalize_username(actor)
    target = str(relative_path).replace("\\", "/").strip("/")
    now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    folder = str(Path(target).parent).replace("\\", "/")
    if folder == ".":
        folder = ""
    with _DB_LOCK, _connect() as db:
        _record(db, normalized_actor, action, target, detail)
        if folder:
            db.execute(
                """INSERT INTO folder_owners(folder,created_by,created_at,last_by,last_at) VALUES(?,?,?,?,?)
                   ON CONFLICT(folder) DO UPDATE SET last_by=excluded.last_by,last_at=excluded.last_at""",
                (folder, normalized_actor, now, normalized_actor, now),
            )


def folder_owner_map(top_folder: str) -> dict[str, dict[str, str]]:
    prefix = normalize_path(top_folder) + "/%"
    with _connect() as db:
        rows = db.execute(
            """SELECT f.folder,f.created_by,f.created_at,f.last_by,f.last_at,
                      c.first_name AS created_first,c.last_name AS created_last,
                      l.first_name AS last_first,l.last_name AS last_last
               FROM folder_owners f LEFT JOIN users c ON c.username=f.created_by
               LEFT JOIN users l ON l.username=f.last_by WHERE f.folder LIKE ?""",
            (prefix,),
        ).fetchall()
    return {
        row["folder"].split("/", 1)[1]: {
            "createdBy": row["created_by"], "createdByName": " ".join(part for part in (row["created_first"], row["created_last"]) if part),
            "createdAt": row["created_at"], "lastBy": row["last_by"],
            "lastByName": " ".join(part for part in (row["last_first"], row["last_last"]) if part), "lastAt": row["last_at"],
        }
        for row in rows
    }


def normalize_path(value: str) -> str:
    return str(value or "").replace("\\", "/").strip("/")


def list_activity(limit: int = 500) -> list[dict[str, Any]]:
    capped = max(1, min(int(limit), 1000))
    with _connect() as db:
        rows = db.execute(
            """SELECT a.happened_at,a.actor,a.action,a.target,a.detail,u.first_name,u.last_name
               FROM activity a LEFT JOIN users u ON u.username=a.actor ORDER BY a.id DESC LIMIT ?""",
            (capped,),
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["actor_name"] = " ".join(part for part in (item.pop("first_name", ""), item.pop("last_name", "")) if part)
        try:
            item["detail"] = json.loads(item["detail"])
        except (TypeError, json.JSONDecodeError):
            item["detail"] = {}
        result.append(item)
    return result


def update_profile(username: str, first_name: str, last_name: str, email: str) -> None:
    normalized = normalize_username(username)
    first_name, last_name = str(first_name or "").strip(), str(last_name or "").strip()
    if len(first_name) > 80 or len(last_name) > 80:
        raise ValueError("First and last name must be 80 characters or fewer.")
    email_value = _email(email)
    with _DB_LOCK, _connect() as db:
        duplicate = db.execute("SELECT username FROM users WHERE email=? AND username<>? COLLATE NOCASE", (email_value, normalized)).fetchone() if email_value else None
        if duplicate:
            raise ValueError("That email address is already assigned to another account.")
        db.execute("UPDATE users SET first_name=?,last_name=?,email=? WHERE username=? AND active=1", (first_name, last_name, email_value, normalized))
        _record(db, normalized, "profile_updated", normalized, {"email_changed": bool(email_value)})


def _totp_code(secret: str, timestamp: int | None = None) -> str:
    key = base64.b32decode(secret + "=" * ((8 - len(secret) % 8) % 8), casefold=True)
    counter = int((timestamp if timestamp is not None else time.time()) // 30)
    digest = hmac.new(key, counter.to_bytes(8, "big"), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = (int.from_bytes(digest[offset:offset + 4], "big") & 0x7FFFFFFF) % 1_000_000
    return f"{value:06d}"


def _verify_totp(secret: str, code: str) -> bool:
    value = re.sub(r"\s+", "", str(code or ""))
    if not secret or not re.fullmatch(r"\d{6}", value):
        return False
    now = int(time.time())
    return any(hmac.compare_digest(_totp_code(secret, now + shift * 30), value) for shift in (-1, 0, 1))


def begin_totp_setup(username: str) -> dict[str, str]:
    normalized = normalize_username(username)
    secret = base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")
    with _DB_LOCK, _connect() as db:
        db.execute("UPDATE users SET totp_pending=? WHERE username=? AND active=1", (secret, normalized))
    user = get_user(normalized) or {}
    label = quote(user.get("email") or normalized, safe="")
    issuer = quote("Primex VS Tools", safe="")
    uri = f"otpauth://totp/{issuer}:{label}?secret={secret}&issuer={issuer}&algorithm=SHA1&digits=6&period=30"
    return {"secret": secret, "uri": uri}


def enable_totp(username: str, password: str, code: str) -> str:
    normalized = normalize_username(username)
    with _DB_LOCK, _connect() as db:
        row = db.execute("SELECT password_hash,totp_pending,totp_enabled FROM users WHERE username=? AND active=1", (normalized,)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            raise ValueError("Current password is incorrect.")
        if row["totp_enabled"]:
            raise ValueError("Two-factor authentication is already enabled.")
        if not row["totp_pending"] or not _verify_totp(row["totp_pending"], code):
            raise ValueError("The verification code is not valid. Check the authenticator app and try again.")
        db.execute("UPDATE users SET totp_secret=totp_pending,totp_pending='',totp_enabled=1,session_version=session_version+1 WHERE username=?", (normalized,))
        _record(db, normalized, "two_factor_enabled", normalized)
    return issue_session(normalized)


def disable_totp(username: str, password: str, code: str) -> str:
    normalized = normalize_username(username)
    with _DB_LOCK, _connect() as db:
        row = db.execute("SELECT password_hash,totp_secret,totp_enabled FROM users WHERE username=? AND active=1", (normalized,)).fetchone()
        if not row or not _verify_password(password, row["password_hash"]):
            raise ValueError("Current password is incorrect.")
        if not row["totp_enabled"] or not _verify_totp(row["totp_secret"], code):
            raise ValueError("The verification code is not valid.")
        db.execute("UPDATE users SET totp_secret='',totp_pending='',totp_enabled=0,session_version=session_version+1 WHERE username=?", (normalized,))
        _record(db, normalized, "two_factor_disabled", normalized)
    return issue_session(normalized)


def change_password(username: str, old_password: str, new_password: str) -> str:
    normalized = normalize_username(username)
    new_hash = _hash_password(_validate_password(new_password))
    with _DB_LOCK, _connect() as db:
        row = db.execute("SELECT password_hash FROM users WHERE username=? AND active=1", (normalized,)).fetchone()
        if row is None or not _verify_password(old_password, row["password_hash"]):
            raise ValueError("Current password is incorrect.")
        db.execute("UPDATE users SET password_hash=?,session_version=session_version+1 WHERE username=?", (new_hash, normalized))
        _record(db, normalized, "password_changed", normalized)
    return issue_session(normalized)


def admin_create_user(actor: str, username: str, password: str, role: str = "user", first_name: str = "", last_name: str = "", email: str = "") -> None:
    normalized = normalize_username(username)
    if not re.fullmatch(r"[A-Z0-9._@-]{1,64}", normalized, re.IGNORECASE):
        raise ValueError("Username may contain letters, numbers, dot, underscore, @ and hyphen.")
    if role not in {"admin", "user"}:
        raise ValueError("Choose admin or user role.")
    first_name, last_name = str(first_name or "").strip(), str(last_name or "").strip()
    if len(first_name) > 80 or len(last_name) > 80:
        raise ValueError("First and last name must be 80 characters or fewer.")
    email_value = _email(email or (normalized if "@" in normalized else ""))
    password_hash = _hash_password(_validate_password(password))
    now = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    with _DB_LOCK, _connect() as db:
        if db.execute("SELECT 1 FROM users WHERE username=?", (normalized,)).fetchone():
            raise ValueError("That username already exists.")
        if email_value and db.execute("SELECT 1 FROM users WHERE email=? COLLATE NOCASE", (email_value,)).fetchone():
            raise ValueError("That email address is already assigned to another account.")
        db.execute("INSERT INTO users(username,password_hash,role,created_at,first_name,last_name,email) VALUES(?,?,?,?,?,?,?)", (normalized, password_hash, role, now, first_name, last_name, email_value))
        _record(db, normalize_username(actor), "user_created", normalized, {"role": role})


def admin_update_profile(actor: str, username: str, first_name: str, last_name: str, email: str) -> None:
    target = normalize_username(username)
    with _DB_LOCK, _connect() as db:
        row = db.execute("SELECT username FROM users WHERE username=? AND active=1", (target,)).fetchone()
    if not row:
        raise ValueError("Active user not found.")
    update_profile(target, first_name, last_name, email)
    record_activity(actor, "user_profile_updated", target)


def admin_reset_password(actor: str, username: str, password: str) -> None:
    normalized = normalize_username(username)
    password_hash = _hash_password(_validate_password(password))
    with _DB_LOCK, _connect() as db:
        row = db.execute("SELECT 1 FROM users WHERE username=? AND active=1", (normalized,)).fetchone()
        if not row:
            raise ValueError("Active user not found.")
        db.execute("UPDATE users SET password_hash=?,session_version=session_version+1 WHERE username=?", (password_hash, normalized))
        _record(db, normalize_username(actor), "password_reset", normalized)


def admin_reset_totp(actor: str, username: str) -> None:
    normalized_actor, normalized = normalize_username(actor), normalize_username(username)
    if normalized == normalized_actor:
        raise ValueError("Ask the other administrator to reset your 2FA.")
    with _DB_LOCK, _connect() as db:
        row = db.execute("SELECT totp_enabled FROM users WHERE username=? AND active=1", (normalized,)).fetchone()
        if not row:
            raise ValueError("Active user not found.")
        db.execute("UPDATE users SET totp_secret='',totp_pending='',totp_enabled=0,session_version=session_version+1 WHERE username=?", (normalized,))
        _record(db, normalized_actor, "two_factor_reset_by_admin", normalized)


def admin_set_role(actor: str, username: str, role: str) -> None:
    normalized = normalize_username(username)
    if role not in {"admin", "user"}:
        raise ValueError("Choose admin or user role.")
    with _DB_LOCK, _connect() as db:
        row = db.execute("SELECT role FROM users WHERE username=? AND active=1", (normalized,)).fetchone()
        if not row:
            raise ValueError("Active user not found.")
        if row["role"] == "admin" and role == "user":
            admins = db.execute("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=1").fetchone()["n"]
            if admins <= 2:
                raise ValueError("Keep at least two active administrators. Add another administrator before changing this role.")
        db.execute("UPDATE users SET role=?,session_version=session_version+1 WHERE username=?", (role, normalized))
        _record(db, normalize_username(actor), "role_changed", normalized, {"role": role})


def admin_delete_user(actor: str, username: str) -> None:
    normalized_actor, normalized = normalize_username(actor), normalize_username(username)
    if normalized == normalized_actor:
        raise ValueError("You cannot remove your own account while signed in.")
    with _DB_LOCK, _connect() as db:
        row = db.execute("SELECT role FROM users WHERE username=? AND active=1", (normalized,)).fetchone()
        if not row:
            raise ValueError("Active user not found.")
        if row["role"] == "admin":
            admins = db.execute("SELECT COUNT(*) AS n FROM users WHERE role='admin' AND active=1").fetchone()["n"]
            if admins <= 2:
                raise ValueError("Keep at least two active administrators. Add another administrator before removing this account.")
        _record(db, normalized_actor, "user_removed", normalized, {"role": row["role"]})
        db.execute("DELETE FROM users WHERE username=?", (normalized,))
        db.execute("DELETE FROM password_resets WHERE username=?", (normalized,))


def create_password_reset(email: str) -> tuple[str, str] | None:
    email_value = _email(email, required=True)
    token = secrets.token_urlsafe(32)
    now = int(time.time())
    with _DB_LOCK, _connect() as db:
        row = db.execute("SELECT username,email FROM users WHERE email=? COLLATE NOCASE AND active=1", (email_value,)).fetchone()
        if not row:
            return None
        recent = db.execute("SELECT 1 FROM password_resets WHERE username=? AND created_at>? LIMIT 1", (row["username"], now - 60)).fetchone()
        if recent:
            return None
        db.execute("DELETE FROM password_resets WHERE username=?", (row["username"],))
        token_hash = hashlib.sha256(token.encode("ascii")).hexdigest()
        db.execute("INSERT INTO password_resets(token_hash,username,expires_at,created_at) VALUES(?,?,?,?)", (token_hash, row["username"], now + RESET_TTL, now))
    return str(row["email"]), token


def clear_password_reset(token: str) -> None:
    token_hash = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
    with _DB_LOCK, _connect() as db:
        db.execute("DELETE FROM password_resets WHERE token_hash=?", (token_hash,))


def reset_password(token: str, new_password: str) -> None:
    token_hash = hashlib.sha256(str(token or "").encode("utf-8")).hexdigest()
    password_hash = _hash_password(_validate_password(new_password))
    now = int(time.time())
    with _DB_LOCK, _connect() as db:
        row = db.execute("SELECT username FROM password_resets WHERE token_hash=? AND expires_at>?", (token_hash, now)).fetchone()
        if not row:
            raise ValueError("This reset link is invalid or has expired. Request a new one.")
        username = row["username"]
        db.execute("UPDATE users SET password_hash=?,session_version=session_version+1 WHERE username=? AND active=1", (password_hash, username))
        db.execute("DELETE FROM password_resets WHERE username=?", (username,))
        db.execute("DELETE FROM password_resets WHERE token_hash=?", (token_hash,))
        _record(db, username, "password_reset_by_email", username)
