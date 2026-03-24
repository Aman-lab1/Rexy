# Rexy - Ambient AI Companion

> Most AI tools wait to be opened.
> Rexy is designed to already be there.

---

## The Idea

Every AI assistant today follows the same pattern - you open an app, type a question, get an answer, close it.

Rexy is built around a different assumption:

**What if your AI didn't need to be opened?**

Rexy is not a chatbot. She's a persistent, environment-aware companion - deployed in the cloud, living on your desk, learning your patterns, and responding when it matters. Not just when you ask.

She's less of a tool. More of a presence.

---

## What Makes Rexy Different

### She doesn't blindly use AI

Most assistants send every single message to an LLM. Rexy doesn't.

A custom-built **SmartGate** - a two-layer intent router - intercepts messages before they reach the AI. Simple commands are handled instantly. Only complex, ambiguous, or conversational requests ever touch the model.

The result: **~75% fewer LLM calls**, faster responses, and lower cost - without sacrificing intelligence.

> Rexy decides *when* to use AI. Not the other way around.

---

### She remembers you

Most assistants forget you the moment you close the tab.

Rexy maintains **per-user persistent memory** powered by Supabase. Context carries across sessions. She knows who you are, what you've asked before, and what matters to you.

Every user gets isolated, private storage. No shared context, no data bleed.

---

### She does real things

Rexy isn't limited to conversation. Through a modular plugin system, she can:

- 🌤 Fetch real-time weather (Open-Meteo)
- 🔍 Search the web live
- 📅 Read and write Google Calendar events
- 🧠 Save and recall memory
- 📁 Read uploaded files
- 🖥 Report system information
- 💻 Control your local machine via a WebSocket agent

Plugins are modular, isolated, and independently extendable. Adding new capabilities doesn't touch the core.

---

### She has a face

**Desk Buddy** is a tablet-based PWA that gives Rexy physical presence.

Not a chat UI. A companion interface - a living, animated face on your desk that listens, reacts, and stays present even when you're not actively talking to her.

- 🎤 Tap-to-speak voice interaction
- 😊 Full emotion engine - idle, listening, thinking, speaking, happy, sad, surprised
- 🌙 Passive presence mode - settles into a dozing state when you're away, wakes up when you return
- 🔔 Notification island - iOS-inspired animated alerts synced to responses
- 🔐 Firebase persistent login - stays signed in across sessions
- 📱 Installable PWA - lives on your homescreen, runs fullscreen

> This is where Rexy stops being software and starts feeling like a companion.

---

## Architecture

Rexy is built as a distributed system - not a monolith.

```
User (Voice / Text)
        ↓
  Desk Buddy PWA  ←→  Railway Backend (FastAPI + WebSockets)
                              ↓
                        SmartGate Router
                         ↙          ↘
                   Plugin System    Groq LLM
                         ↓
                    Supabase (Memory)
                    Firebase (Auth)
```

| Layer | Technology |
|---|---|
| Backend | FastAPI + WebSockets |
| LLM | Groq API (llama-3.3-70b-versatile) |
| Auth | Firebase Authentication |
| Memory | Supabase (per-user) |
| Frontend | HTML/CSS/JS PWA |
| Hosting | Railway |
| Local Agent | Python WebSocket bridge |

---

## Security

Rexy is multi-user from the ground up:

- Authenticated WebSocket connections (Firebase token verification)
- Per-user isolated memory - no cross-user data access
- Rate limiting on all endpoints
- TLS enforced
- Path traversal protections
- Credential-free local agent design

---

## Current Status

**Phase 5 - Presence**

Rexy is live and in active development. Current focus:

- Natural voice interaction
- Emotional interface refinement  
- Daily usability and ambient experience

---

## The Vision

```
Now          →   Voice-enabled ambient companion with memory and modular intelligence

Near future  →   Observational memory, proactive nudges, deeper personalization

Mid vision   →   Multi-device presence across physical spaces

Long term    →   Perception, sensors, autonomous environment-aware behavior
```

The goal isn't to build a better chatbot.

It's to build something that fits quietly into your life - and makes you wonder how you worked without it.

---

## Getting Started

> Setup instructions and self-hosting guide coming soon.

---

## Philosophy

> Intelligence is not just about answering.
> It's about being present, understanding context, and responding at the right moment.

Rexy is an ongoing experiment in what AI can feel like when it stops being a tool and starts being a companion.

---

## Author

Built by a first-year EEE student with an obsession for building things that feel alive.

Every decision - from the SmartGate architecture to the eyelid animation - was made asking the same question:

*Does this feel real?*

---

*This is just the beginning.*
