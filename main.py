import os
import logging
from contextlib import asynccontextmanager
from datetime import datetime

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import database
import claude_conversation
import reminder_scheduler

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    database.init_db()
    reminder_scheduler.start()
    logger.info("WebinarFunnel AI ready.")
    yield
    reminder_scheduler.stop()


app = FastAPI(
    title="WebinarFunnel AI",
    description="WhatsApp webinar automation powered by Claude",
    version="1.0.0",
    lifespan=lifespan,
)

app.mount("/static", StaticFiles(directory="static"), name="static")


# ---------------------------------------------------------------------------
# Request models
# ---------------------------------------------------------------------------

class RegistrationRequest(BaseModel):
    name: str
    email: str
    phone: str
    webinar_date: str  # ISO format: 2026-06-15T14:00:00


class InboundMessageRequest(BaseModel):
    phone: str
    message: str
    registrant_id: str | None = None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.get("/")
async def serve_frontend():
    return FileResponse("static/index.html")


@app.post("/webhook/registration")
async def register(body: RegistrationRequest):
    try:
        webinar_dt = datetime.fromisoformat(body.webinar_date)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid webinar_date format. Use ISO: 2026-06-15T14:00:00")

    rid = database.create_registrant(body.name, body.email, body.phone, body.webinar_date)
    scheduled = reminder_scheduler.schedule_reminders(rid, webinar_dt)

    return JSONResponse({
        "registrant_id": rid,
        "name": body.name,
        "scheduled_reminders": scheduled,
        "status": "registered",
    })


@app.post("/webhook/inbound-message")
async def inbound_message(body: InboundMessageRequest):
    registrant = None

    if body.registrant_id:
        registrant = database.get_registrant(body.registrant_id)
    if not registrant and body.phone:
        registrant = database.get_registrant_by_phone(body.phone)
    if not registrant:
        raise HTTPException(status_code=404, detail="Registrant not found. Register first via /webhook/registration")

    rid = registrant["id"]
    database.save_message(rid, "inbound", body.message)

    history_rows = database.get_conversation(rid)
    claude_history = [
        {"role": "user" if r["role"] == "inbound" else "assistant", "content": r["message"]}
        for r in history_rows
        if r["role"] in ("inbound", "outbound") and r.get("intent") != "reminder_confirmation"
        and r.get("intent") != "reminder_day_before"
        and r.get("intent") != "reminder_hour_before"
        and r.get("intent") != "reminder_post_webinar"
    ]

    result = claude_conversation.process_message(registrant["name"], claude_history, body.message)

    database.save_message(rid, "outbound", result["reply"], intent=result["intent_detected"])

    if result["booking_triggered"]:
        database.mark_booking(rid)

    return JSONResponse({
        "registrant_id": rid,
        "reply": result["reply"],
        "intent_detected": result["intent_detected"],
        "booking_triggered": result["booking_triggered"],
    })


@app.post("/send-reminder/{registrant_id}/{reminder_type}")
async def send_reminder(registrant_id: str, reminder_type: str):
    valid_types = {"confirmation", "day_before", "hour_before", "post_webinar"}
    if reminder_type not in valid_types:
        raise HTTPException(status_code=400, detail=f"Invalid type. Use: {valid_types}")

    registrant = database.get_registrant(registrant_id)
    if not registrant:
        raise HTTPException(status_code=404, detail="Registrant not found")

    message = reminder_scheduler.get_reminder_message(registrant["name"], reminder_type)
    database.save_message(registrant_id, "outbound", message, intent=f"reminder_{reminder_type}")
    database.mark_reminder_sent(registrant_id, reminder_type)

    return JSONResponse({
        "registrant_id": registrant_id,
        "reminder_type": reminder_type,
        "message_sent": message,
        "status": "sent",
    })


@app.get("/conversation/{registrant_id}")
async def get_conversation(registrant_id: str):
    if not database.get_registrant(registrant_id):
        raise HTTPException(status_code=404, detail="Registrant not found")
    turns = database.get_conversation(registrant_id)
    return JSONResponse({"registrant_id": registrant_id, "turns": turns, "total": len(turns)})


@app.get("/registrants")
async def list_registrants():
    registrants = database.get_all_registrants()
    return JSONResponse({"total": len(registrants), "registrants": registrants})


@app.get("/health")
async def health():
    return JSONResponse({
        "status": "ok",
        "service": "WebinarFunnel AI",
        "anthropic_key_set": bool(os.getenv("ANTHROPIC_API_KEY")),
        "scheduler_running": reminder_scheduler.get_scheduler().running,
    })


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", 8000)), reload=False)
