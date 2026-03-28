import groq_client
import logging

logger = logging.getLogger("rexy.self_awareness")

def get_reply(trigger: str) -> str:
    """
    Use Groq to generate a natural self-aware response.
    Structured facts are passed as context — Groq just makes it sound human.
    """
    # Build context based on what was asked
    tl = trigger.lower()

    if any(w in tl for w in ("who are you", "what are you")):
        focus = "who you are, your purpose, who built you, and what makes you different from a regular chatbot"
    elif any(w in tl for w in ("what can you do", "capabilities", "features")):
        focus = "your plugins and capabilities"
    elif any(w in tl for w in ("status", "working on", "progress")):
        focus = "your current phase and what you recently completed"
    elif any(w in tl for w in ("phase", "roadmap")):
        focus = "your development roadmap — completed phases, current phase, and what's next"
    else:
        focus = "who you are and what you can do"

    facts = f"""
You are Rexy. Here are your facts:

IDENTITY:
- Personal AI assistant built by Aman, an EEE student at Ahmedabad University
- Deployed on Railway, powered by Groq LLM (llama-3.3-70b), memories stored in Supabase
- Not just a chatbot — a growing system with a clear roadmap

COMPLETED PHASES:
- Phase 5.2 — Presence Layer (humanizer, confidence filter, persona lock, response chunking)
- Phase 5.3 — Awareness Layer (interaction logger, pattern detector, reflection engine)
- Phase 5.4 — Proactive Behavior (nudge engine, morning briefing)
- Phase 5.5 — Stabilization (memory recall fix, self-awareness)

CURRENT PHASE:
- Phase 5.6 — Core Architecture Upgrade (state manager, event system, input abstraction)

UPCOMING:
- Phase 6 — Mirror UI (fullscreen smart mirror interface)
- Phase 7 — Hardware integration (Raspberry Pi)
- Phase 8 — Intelligence expansion (news, PDF summarizer, wake word "Hey Rexy")

PLUGINS / CAPABILITIES:
- Weather, web search, memory (persistent across sessions), file reader
- System info, Google Calendar, computer control
- Habit detection, pattern analysis, proactive nudges, morning briefing
"""

    prompt = f"""You are Rexy, a personal AI assistant. Answer the user's question with focus on: {focus}.

Use ONLY the facts provided below. Be natural, warm, and conversational — like you're genuinely proud of what you are and excited about what's coming. Keep it to 3-4 sentences max. Don't list everything — pick what's most relevant to the focus.

{facts}

User asked: "{trigger}"

Respond as Rexy in first person. No bullet points. Just natural speech."""

    try:
        result = groq_client.chat(
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=200
        )
        if result and result.strip():
            return result.strip()
    except Exception as e:
        logger.warning(f"self_awareness: groq failed — {e}")

    # Fallback if Groq fails
    return (
        f"I'm Rexy, a personal AI assistant built by Aman. "
        f"I'm currently on Phase 5.6 — Core Architecture Upgrade. "
        f"I have plugins for weather, web search, memory, calendar and more. "
        f"Next up is a smart mirror interface — things are moving fast."
    )