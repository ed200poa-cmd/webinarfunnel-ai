import sqlite3
import uuid
import json
from datetime import datetime
from pathlib import Path

DB_PATH = Path("webinarfunnel.db")


def init_db() -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS registrants (
                id            TEXT PRIMARY KEY,
                name          TEXT NOT NULL,
                email         TEXT NOT NULL,
                phone         TEXT NOT NULL,
                webinar_date  TEXT NOT NULL,
                registered_at TEXT NOT NULL,
                reminder_sent TEXT DEFAULT '{}',
                booking_triggered INTEGER DEFAULT 0
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS conversations (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                registrant_id TEXT NOT NULL,
                role          TEXT NOT NULL,
                message       TEXT NOT NULL,
                intent        TEXT,
                timestamp     TEXT NOT NULL,
                FOREIGN KEY (registrant_id) REFERENCES registrants(id)
            )
        """)
        conn.commit()


def create_registrant(name: str, email: str, phone: str, webinar_date: str) -> str:
    rid = str(uuid.uuid4())[:8]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO registrants (id, name, email, phone, webinar_date, registered_at) VALUES (?, ?, ?, ?, ?, ?)",
            (rid, name, email, phone, webinar_date, datetime.utcnow().isoformat()),
        )
        conn.commit()
    return rid


def get_registrant(registrant_id: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM registrants WHERE id = ?", (registrant_id,)).fetchone()
        return dict(row) if row else None


def get_registrant_by_phone(phone: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute("SELECT * FROM registrants WHERE phone = ?", (phone,)).fetchone()
        return dict(row) if row else None


def get_all_registrants() -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM registrants ORDER BY registered_at DESC").fetchall()
        return [dict(r) for r in rows]


def save_message(registrant_id: str, role: str, message: str, intent: str | None = None) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO conversations (registrant_id, role, message, intent, timestamp) VALUES (?, ?, ?, ?, ?)",
            (registrant_id, role, message, intent, datetime.utcnow().isoformat()),
        )
        conn.commit()


def get_conversation(registrant_id: str) -> list[dict]:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT role, message, intent, timestamp FROM conversations WHERE registrant_id = ? ORDER BY id",
            (registrant_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def mark_reminder_sent(registrant_id: str, reminder_type: str) -> None:
    registrant = get_registrant(registrant_id)
    if not registrant:
        return
    sent = json.loads(registrant.get("reminder_sent") or "{}")
    sent[reminder_type] = datetime.utcnow().isoformat()
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "UPDATE registrants SET reminder_sent = ? WHERE id = ?",
            (json.dumps(sent), registrant_id),
        )
        conn.commit()


def mark_booking(registrant_id: str) -> None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("UPDATE registrants SET booking_triggered = 1 WHERE id = ?", (registrant_id,))
        conn.commit()
