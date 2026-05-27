import os
import logging

import anthropic

logger = logging.getLogger(__name__)
MODEL = "claude-haiku-20240307"

SYSTEM_PROMPT = """You are an AI assistant for a business automation webinar host. Your goal is to answer questions about the webinar content, handle objections, and guide interested attendees toward booking a free strategy call.

Be conversational, helpful, and encouraging. Keep responses under 60 words — this is WhatsApp. Never make false promises.

WEBINAR CONTEXT:
- Topic: AI Business Automation — How to save 10+ hours/week using AI tools
- Tools covered: Make.com, Claude AI, WhatsApp automation, n8n
- Bonus: Free automation audit for all attendees
- Booking link: cal.com/webinar (free 30-min strategy call)

When someone is ready to book, share the link: cal.com/webinar

DETECT INTENT (include in your reasoning but not in response):
booking_interest | question | objection | general | not_interested"""

BOOKING_TRIGGERS = ["book", "schedule", "call", "sign up", "yes please", "how do i", "cal.com", "interested", "next step", "want to"]
OBJECTION_TRIGGERS = ["expensive", "too much", "don't have time", "not sure", "maybe later", "busy", "not ready"]


def detect_intent(message: str) -> str:
    lower = message.lower()
    if any(k in lower for k in BOOKING_TRIGGERS):
        return "booking_interest"
    if any(k in lower for k in OBJECTION_TRIGGERS):
        return "objection"
    if "?" in message:
        return "question"
    return "general"


def process_message(registrant_name: str, history: list[dict], message: str) -> dict:
    intent = detect_intent(message)
    booking_triggered = intent == "booking_interest"

    messages = history + [{"role": "user", "content": message}]

    api_key = os.getenv("ANTHROPIC_API_KEY", "")
    if not api_key:
        reply = _fallback_reply(intent, registrant_name)
        return {"reply": reply, "intent_detected": intent, "booking_triggered": booking_triggered}

    try:
        client = anthropic.Anthropic(api_key=api_key)
        resp = client.messages.create(
            model=MODEL,
            max_tokens=200,
            system=SYSTEM_PROMPT,
            messages=messages,
        )
        reply = resp.content[0].text.strip()
        if "cal.com" in reply.lower() or "book" in reply.lower():
            booking_triggered = True
    except Exception as exc:
        logger.error("Claude error: %s", exc)
        reply = _fallback_reply(intent, registrant_name)

    return {"reply": reply, "intent_detected": intent, "booking_triggered": booking_triggered}


def _fallback_reply(intent: str, name: str) -> str:
    if intent == "booking_interest":
        return f"Great, {name}! Book your free 30-min strategy call here: cal.com/webinar — can't wait to map out your automation plan!"
    if intent == "objection":
        return "Totally understand! The call is completely free, no pressure. Most people find 1 idea that saves them 5+ hours/week. Worth 30 minutes?"
    if intent == "question":
        return "Great question! We covered Make.com + Claude AI for automating lead follow-up, scheduling, and WhatsApp funnels. What part interests you most?"
    return f"Hey {name}! Did the webinar spark any ideas? Happy to answer questions or help you figure out next steps!"
