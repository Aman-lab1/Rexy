# Rexy 🤖

> A safety-first personal AI assistant with a plugin system. Built by an EEE student who had no business building this. 🔥

Rexy is a fully local, modular AI assistant built in Python. It runs on your own machine using Ollama (no cloud, no API keys for core features), communicates via WebSocket, and speaks using Piper TTS. Every message flows through a strict **THINK → VERIFY → EXECUTE** pipeline before anything happens.

---

## ✨ Features

- 🧠 **Local LLM** — powered by Ollama (`llama3.2`), runs 100% offline
- 🔒 **Safety-first pipeline** — THINK → VERIFY → EXECUTE, every single message
- ⚡ **Pre-checks** — critical intents caught by regex before LLM is even called
- 🔌 **Plugin system** — drop a file in `modules/plugins/`, Rexy finds it automatically
- 💾 **Identity memory** — remembers your name across sessions
- 🗣️ **Text-to-speech** — non-blocking Piper TTS with pygame
- 🌐 **WebSocket interface** — real-time communication via FastAPI
- ✅ **49/49 test cases passing**

---

## 🧩 Built-in Intents

| Intent | Description |
|--------|-------------|
| `CHAT` | General conversation via Ollama |
| `CALCULATOR` | Math expressions with chain mode |
| `GET_TIME` | Current local time |
| `LIST_FILES` | List files in current directory |
| `RESET` | Clear session state |
| `MUSIC` | Music mode |
| `ADVISOR` | Activity suggestions when bored |
| `EMOTION_SUPPORT` | Emotional support responses |
| `GREET` | Greetings with personality |

---

## 🔌 Plugins

| Plugin | Description |
|--------|-------------|
| 🌤️ Weather | Live weather via wttr.in (no API key) |
| 🔍 Web Search | DuckDuckGo Instant Answer API |
| 🧠 Memory | Remember/recall/forget things across sessions |
| 📄 File Reader | Read txt, pdf, pptx, docx, csv, json from inbox |
| 🖥️ System Info | CPU, RAM, battery, disk, uptime via psutil |

---

## 🏗️ Architecture

```
User Message
     │
     ▼
┌─────────────┐
│    THINK    │  Pre-checks (regex) → LLM intent detection
└─────────────┘
     │
     ▼
┌─────────────┐
│   VERIFY    │  ALLOW / CLARIFY / REJECT
└─────────────┘
     │
     ▼
┌─────────────┐
│   EXECUTE   │  Route to handler or plugin
└─────────────┘
     │
     ▼
  Response
```

---

## 📁 File Structure

```
Rexy/
├── orchestrator.py          # Main pipeline (THINK → VERIFY → EXECUTE)
├── observer.py              # Passive observability logging
├── test_rexy.py             # Test harness (49 test cases)
├── identity.json            # Persisted user identity
│
├── modules/
│   ├── calculator.py        # Calculator with chain mode
│   ├── chat_intent.py       # Chat intelligence (Ollama)
│   ├── plugin_base.py       # Base class for all plugins
│   ├── plugin_manager.py    # Auto-discovery engine
│   └── plugins/
│       ├── weather_plugin.py
│       ├── websearch_plugin.py
│       ├── memory_plugin.py
│       ├── filereader_plugin.py
│       └── sysinfo_plugin.py
│
├── config/
│   └── settings.py
│
└── voices/                  # Piper TTS voice models
```

---

## 🚀 Getting Started

### Prerequisites
- Python 3.12
- [Ollama](https://ollama.com/download) with `llama3.2` model
- [Piper TTS](https://github.com/rhasspy/piper) (for voice output)

### Installation

```bash
# Clone the repo
git clone https://github.com/Aman-lab1/Rexy.git
cd Rexy

# Create virtual environment
python -m venv venv
venv\Scripts\activate  # Windows
# source venv/bin/activate  # Linux/Mac

# Install dependencies
pip install fastapi uvicorn ollama pygame python-dotenv psutil

# Optional (for file reading)
pip install pypdf python-pptx python-docx

# Pull the LLM
ollama pull llama3.2
```

### Run

```bash
# Terminal 1 — start Ollama
ollama serve

# Terminal 2 — start Rexy
uvicorn orchestrator:app --host 127.0.0.1 --port 8000 --reload
```

Then open your browser at `http://localhost:8000`

---

## 🧪 Running Tests

```bash
python test_rexy.py
```

Expected output: **49/49 passed** ✅

---

## 🔌 Adding a New Plugin

1. Create a file in `modules/plugins/` ending in `_plugin.py`
2. Inherit from `RexyPlugin`
3. Implement 5 methods: `intent_name`, `description`, `risk_level`, `intent_examples`, `execute`
4. Add the intent to `SYSTEM_PROMPT` in `orchestrator.py`
5. Restart Rexy — plugin is auto-discovered

```python
from modules.plugin_base import RexyPlugin

class JokesPlugin(RexyPlugin):
    @property
    def intent_name(self): return "JOKES"
    
    @property
    def description(self): return "Tell a random joke"
    
    @property
    def risk_level(self): return "low"
    
    @property
    def intent_examples(self): return ["tell me a joke", "say something funny"]
    
    def execute(self, message, emotion, state):
        return {"reply": "Why did the EEE student cross the road? To get to the other circuit! 😄", "emotion": "happy", "state": "speaking"}
```

---

## 🛠️ Tech Stack

| Technology | Purpose |
|------------|---------|
| Python 3.12 | Core language |
| FastAPI | WebSocket server |
| Ollama + llama3.2 | Local LLM |
| Piper TTS | Text-to-speech |
| pygame | Audio playback |
| psutil | System stats |
| wttr.in | Weather API |
| DuckDuckGo API | Web search |

---

## 👨‍💻 About

Built by **Aman** — an Electrical & Electronics Engineering student at Ahmedabad University who decided building an AI assistant from scratch was a perfectly normal thing to do during first year. 

No CS degree. No shortcuts. Just curiosity, Python, and way too many late nights. 🌙

---

## 📄 License

MIT License — do whatever you want with it, just don't blame me if Rexy gets too smart. 😄
