import logging
from datetime import datetime, timedelta

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore

import database

logger = logging.getLogger(__name__)

REMINDER_TEMPLATES = {
    "confirmation": (
        "Hi {name}! 🎉 You're registered for the AI Business Automation webinar at 2 PM EST. "
        "We'll show you how to save 10+ hours/week. Reply with any questions!"
    ),
    "day_before": (
        "Hi {name}! ⏰ Your webinar is TOMORROW at 2 PM EST. "
        "Add it to your calendar now so you don't miss it. See you there!"
    ),
    "hour_before": (
        "Hi {name}! 🚀 We start in 1 HOUR! "
        "Join here: [webinar_link] — See you soon!"
    ),
    "post_webinar": (
        "Hi {name}! 👋 Thanks for attending today's webinar! "
        "Did you have any questions about what we covered? "
        "Reply here and I'll help you figure out your next steps!"
    ),
}

_scheduler: BackgroundScheduler | None = None


def get_scheduler() -> BackgroundScheduler:
    global _scheduler
    if _scheduler is None:
        jobstores = {"default": SQLAlchemyJobStore(url="sqlite:///scheduler_jobs.db")}
        _scheduler = BackgroundScheduler(jobstores=jobstores, timezone="UTC")
    return _scheduler


def get_reminder_message(name: str, reminder_type: str) -> str:
    template = REMINDER_TEMPLATES.get(reminder_type, "Hi {name}! Reminder about your upcoming webinar.")
    return template.format(name=name)


def _fire_reminder(registrant_id: str, reminder_type: str) -> None:
    registrant = database.get_registrant(registrant_id)
    if not registrant:
        return
    message = get_reminder_message(registrant["name"], reminder_type)
    database.save_message(registrant_id, "outbound", message, intent=f"reminder_{reminder_type}")
    database.mark_reminder_sent(registrant_id, reminder_type)
    logger.info("Reminder fired: %s → registrant %s", reminder_type, registrant_id)


def schedule_reminders(registrant_id: str, webinar_dt: datetime) -> list[dict]:
    sched = get_scheduler()
    now = datetime.utcnow()

    schedule_map = {
        "confirmation": now + timedelta(seconds=3),
        "day_before": webinar_dt - timedelta(hours=24),
        "hour_before": webinar_dt - timedelta(hours=1),
        "post_webinar": webinar_dt + timedelta(hours=2),
    }

    results = []
    for reminder_type, run_at in schedule_map.items():
        if run_at <= now and reminder_type != "confirmation":
            results.append({"type": reminder_type, "status": "skipped_past", "scheduled_at": run_at.isoformat()})
            continue
        job_id = f"{registrant_id}_{reminder_type}"
        sched.add_job(
            _fire_reminder,
            trigger="date",
            run_date=max(run_at, now + timedelta(seconds=1)),
            args=[registrant_id, reminder_type],
            id=job_id,
            replace_existing=True,
        )
        results.append({"type": reminder_type, "status": "scheduled", "scheduled_at": run_at.isoformat()})

    return results


def start() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("APScheduler started.")


def stop() -> None:
    sched = get_scheduler()
    if sched.running:
        sched.shutdown(wait=False)
