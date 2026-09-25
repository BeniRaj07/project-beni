# Awaaz — Bilingual AI Voice & Chat Assistant

**A ChatGPT-style, voice-first assistant for everyday task management, weather and football news,
in Nepali (नेपाली) and English.**
University data-science project · Python 3.11+ · Gradio · Groq Whisper + Claude LLM · Gemini/ElevenLabs TTS
· JSON data store · APScheduler

The assistant has a deliberately **limited scope**: greetings and small talk, personal reminders,
monthly tasks, weather, and football (soccer). Everything else is politely refused. There are no
feature tabs, dashboards or forms — every feature is reached through one conversation, by voice or
by typing.

---

## 1. Interface

A single, minimal ChatGPT-style screen:

- **Left sidebar** — a prominent **＋ New chat** button, a search box, and your conversation history
  grouped into *Today / Yesterday / Previous 7 Days / Older*, each with an auto-generated title.
  Click a conversation to reopen it with its full history and context; hover a row to rename (✏️)
  or delete (🗑️) it. Collapses into a slide-out drawer on narrow screens.
- **Main chat column** — a plain conversation: your messages, the assistant's replies, a welcome
  message on a fresh chat, a subtle "Awaaz is thinking…" line while it works, and a spoken-reply
  player with a **Stop** button. A composer at the bottom has a text box, a **Send** button, and a
  round 🎤 **mic button**: tap once to start recording (it pulses and shows a live level meter),
  tap again to send — no separate record/stop screen.

Dark by default; a 🌓 toggle in the sidebar switches to light. No intent JSON, API responses or
debugging information is ever shown — only the final conversational answer.

## 2. Features

| Capability | What it does | Data source |
|---|---|---|
| 💬🎙️ Conversation | Type or speak, in English, Devanagari Nepali or Romanized Nepali; the reply is shown as text and (optionally) spoken back; follow-up questions ("What time?" → "8 PM") keep context; every conversation is saved and searchable | Groq Whisper + Claude |
| ⏰ Reminders | Created, listed, edited and deleted entirely by voice/text — "remind me to call mum tomorrow at 8", "what reminders do I have today?", "delete my assignment reminder"; one-time, daily, weekly or monthly; due reminders appear as a chat message (and are spoken, if enabled) while the app is running | Local JSON + APScheduler |
| 📝 Monthly tasks | Add, list, complete and delete by voice/text — "add finishing my report to this month's tasks", "what are my pending tasks?", "mark my report as completed"; recurring monthly tasks never duplicate; a task can carry a linked reminder | Local JSON |
| 🌤️ Weather | Current conditions kept clearly separate from forecasts; the location's own timezone; remembers the last city you asked about | Open-Meteo |
| ⚽ Football | Standings, recent results, upcoming fixtures, team results, and short news summaries with sources — six competitions (Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League); American football is excluded | Football-Data.org, NewsAPI |

---

## 3. Review of the original script (`legacy/original_app.py`)

**Reused (kept almost unchanged):** `generate_with_retry`, `transcribe_file` → `services/speech_to_text.py`,
`save_wave_file` and the Gemini `text_to_speech` call → `services/text_to_speech.py`, the `WEATHER_CODES`
table (completed and translated), `LEAGUE_CODES` (extended with Nepali names), the
`classify_intent` → handler → reply design, and the `get_football_news_summary` prompt idea.

**Problems found and fixed:**

| # | Problem in the original | Fix |
|---|---|---|
| 1 | `os.environ["…"]` at import crashed the whole app if any key was missing | Keys are optional at start-up; each feature shows *"This feature needs X in .env"* |
| 2 | No `timeout=` on any `requests.get` — a slow API froze the UI forever | Shared session with timeouts and retry/backoff on 5xx (`services/http.py`) |
| 3 | Errors (quota, network, 403 plan limits) bubbled up as stack traces in the UI | Every failure becomes a friendly bilingual message; TTS failure keeps the text reply |
| 4 | `text_to_speech()` always wrote `output.wav` → simultaneous users overwrote each other's audio | Unique file per reply + periodic clean-up |
| 5 | Gemini TTS used for Nepali without checking support | Nepali falls back to edge-tts's native ne-NP voices automatically if Gemini/ElevenLabs can't speak it, and `scripts/check_setup.py` lets you compare all three by ear |
| 6 | `classify_intent` parsed JSON with `.replace("json", "", 1)` and `json.loads` → crashed on fences/chatter and could corrupt values containing "json" | JSON mode + robust extraction + retry + **Pydantic** validation; bad fields become `None` instead of crashing |
| 7 | News API key sent in the URL query string (ends up in logs/proxies) | Sent as the `X-Api-Key` header |
| 8 | `current_weather=True` only — could not answer *"is it raining?"* or *"tomorrow?"* | Current rain/precipitation/feels-like + hourly/daily forecast, clearly labelled "now" vs "forecast" |
| 9 | League results fetched the whole season on every question; no rate-limit handling (free tier = 10 req/min) | Caching + client-side limiter; one request serves both results and fixtures |
| 10 | NFL filtering relied only on the query | Query exclusions **and** local keyword filter |
| 11 | Replies were always generated in English for data answers; no memory between turns | Language detection (script + LLM), bilingual templates, conversation state and follow-ups |
| 12 | `demo.launch()` at module level; single 300-line file, one giant multi-tab dashboard UI | Modules with one responsibility each; a single, minimal chat interface — see §5 |

---

## 4. Architecture

```
                     ┌──────────── app.py (ChatGPT-style UI) ─────────────┐
  type ─────────────►│  sidebar: conversations   ·   chat + composer + 🎤 │◄── gr.Timer polls due reminders
  speak (mic) ───────►└───────┬───────────────────────┬───────────────────┘
                              │ speech_to_text        │ text_turn()
                              ▼ (Whisper)              ▼
                      assistant/conversation.respond()
                              │  ① intent_classifier (Claude → JSON → Pydantic)
                              │  ② merge follow-up answers   ③ dispatch
                              ▼
                      assistant/handlers.py ──► services/{weather, football, news, reminders, tasks}
                              │                          │
                              ▼                          ▼
                      response_generator            data/*.json (database/json_store.py)
                      (templates for facts,         ◄── scheduler/reminder_scheduler.py
                       LLM only for small talk
                       + news summaries)
                              ▼
                      Reply(text, spoken, language) ──► text_to_speech (Gemini/ElevenLabs → edge-tts) ──► WAV
                              ▼
                      services/conversations.py saves the turn to data/conversations.json
```

```
voice-assistant/
├── app.py                        # the ChatGPT-style UI (sidebar + chat) + start-up
├── theme.py                      # dark/light CSS + the small amount of client JS (mic recorder,
│                                  #   theme toggle, mobile sidebar drawer)
├── config.py                     # settings from .env, JSON structured logging
├── assistant/
│   ├── intent_classifier.py      # 17 intents, entity extraction, Pydantic validation
│   ├── conversation.py           # respond()/run_intent(): the shared backend for every turn
│   ├── handlers.py               # one function per intent
│   ├── response_generator.py     # bilingual templates, formatters, LLM greeting/news summary
│   └── briefing.py               # "what's my update?" daily-briefing intent
├── services/
│   ├── http.py                   # timeouts, retries, friendly errors, cache, rate limiter
│   ├── llm.py                    # Claude chat wrapper (JSON retry) + the Groq client for Whisper
│   ├── speech_to_text.py         # Groq Whisper
│   ├── text_to_speech.py         # Gemini/ElevenLabs + edge-tts fallback, unique WAV files
│   ├── weather.py  football.py  news.py
│   ├── reminders.py  tasks.py    # business logic, on top of the JSON store
│   ├── conversations.py          # sidebar persistence: CRUD, auto-title, search, grouping
│   └── user_settings.py          # the handful of UI-editable prefs (autoplay, theme, …)
├── database/
│   ├── json_store.py             # atomic, locked, schema-validated read/write for one JSON file
│   ├── models.py                 # Pydantic schemas for every data/*.json file
│   └── stores.py                 # the four JsonStore instances (conversations/reminders/tasks/settings)
├── scheduler/reminder_scheduler.py
├── scripts/check_setup.py        # pre-demo API + TTS check
├── tests/                        # 140 unit tests, all external services mocked
└── legacy/original_app.py        # the original script, for comparison
```

**Design decisions worth mentioning in the report**
* **Facts are never generated by the LLM.** Scores, tables, weather numbers and reminder times are
  formatted by deterministic templates from API data. The LLM only classifies intents, makes small
  talk and summarises the news articles it is given (with an instruction to treat them as untrusted data).
* **JSON, not SQLite, for storage.** Right-sized for a single-user university project: the four
  files under `data/` (`conversations.json`, `reminders.json`, `tasks.json`, `settings.json`) are
  easy to open and show in a demo. `database/json_store.py` still gives real guarantees — atomic
  writes (write to a temp file, `os.replace()` into place), an in-process lock plus a cross-process
  file lock (via `filelock`) so the background reminder scheduler and a chat request can never
  interleave a write, and Pydantic schema validation on every read (a corrupted or hand-edited file
  resets to a safe empty default instead of crashing the app, with a `.bak` copy kept for inspection).
* **Timestamps** are stored in UTC with the IANA timezone; recurring reminders keep their local
  wall-clock time (a "31st of every month" reminder fires on 28 Feb, then 31 Mar).
* **Exactly-once notifications** and **no duplicate recurring tasks** are enforced the same way SQL
  UNIQUE constraints would, just in Python: one locked read-modify-write per check, checking for an
  existing (reminder, occurrence) or (series, month) pair before adding a new record.
* **Conversation context survives everything.** A follow-up question's pending state, the last city
  you asked about, and the detected language are saved on the conversation record itself, so
  switching to another chat and back — or restarting the app entirely — doesn't lose the thread.

---

## 5. Why a plain chat interface, not a dashboard

The original design task called for separate tabs for voice, reminders, tasks and football/weather.
That is deliberately **not** what this app does. Every one of those features is fully implemented in
`services/` and `assistant/handlers.py` exactly as before — nothing was removed — but the *only* way
to reach any of them is through the one conversation column, by typing or speaking naturally:

- "Remind me to submit my assignment tomorrow at 9 AM" → reminders
- "What are my pending tasks?" → monthly tasks
- "Is it raining in Kathmandu right now?" → weather
- "Show the Premier League standings" → football

This keeps the interface to the two sections asked for (a conversation sidebar and a chat), while
every backend capability stays reachable — just through conversation, not through a form.

## 6. Installation

```bash
cd voice-assistant
python -m venv .venv
# Windows: .venv\Scripts\activate      macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # Windows: copy .env.example .env
```

Fill in `.env`:

| Key | Where to get it | Free tier notes |
|---|---|---|
| `ANTHROPIC_API_KEY` | console.anthropic.com/settings/keys | powers intent classification, small talk and news summaries (`CLAUDE_MODEL`, default `claude-haiku-4-5`) |
| `GROQ_API_KEY` | console.groq.com/keys | speech-to-text (Whisper) only; generous, rate-limited per minute |
| `GEMINI_API_KEY` | aistudio.google.com/apikey | primary TTS engine by default; preview model has a daily quota |
| `NEWS_API_KEY` | newsapi.org/register | developer plan: localhost only, articles delayed ~24 h |
| `FOOTBALL_DATA_KEY` | football-data.org/client/register | 10 requests/min, the six supported competitions included; scores may be delayed |
| `ELEVENLABS_API_KEY` *(optional)* | elevenlabs.io/app/settings/api-keys | only needed if you want an ElevenLabs voice instead of Gemini's — see below |

Open-Meteo needs no key. The timezone defaults to `Asia/Kathmandu` (`APP_TIMEZONE` in `.env`).

**Choosing a voice:** with no `ELEVENLABS_API_KEY`, replies are spoken with **Gemini TTS** (the
original project's engine) by default, falling back to edge-tts automatically for anything Gemini
can't say. If you add an ElevenLabs key, that becomes the default engine instead (set
`TTS_ENGINE_EN`/`TTS_ENGINE_NE=gemini` in `.env` to keep using Gemini even with a key configured).
To use a specific ElevenLabs voice, open its Voice Library page and click **Add to my voices**
(library voices must be in your account before the API can use them), then set
`ELEVENLABS_VOICE_ID` in `.env`.

Check everything before a demo (also creates Nepali/English TTS samples in `data/tts_check/`):

```bash
python scripts/check_setup.py
```

## 7. Run

```bash
python app.py
```

Open **http://127.0.0.1:7860**. Type a message, or tap the 🎤 button and speak — tap it again to
send. The `data/` folder (`conversations.json`, `reminders.json`, `tasks.json`, `settings.json`) is
created automatically on first start. Logs are written as JSON lines to `logs/app.log`.

## 8. Tests

```bash
pytest -q            # 140 tests, ~4 s, no network or API keys needed
pytest -v tests/test_reminders.py     # a single file
```

Covered: Nepali/English/Romanized intent classification and validation, reminder creation and
retrieval, monthly recurrence (month-end clamping), exactly-once firing, timezone conversion,
recurring tasks without duplicates, progress/overdue, weather current-rain vs forecast, football
parsing/filtering/rate limits, NFL filtering, HTTP 429/403/500/timeouts/bad JSON, malformed LLM
output, STT empty/short/failed audio, TTS fallback and total failure, follow-up questions,
conversation persistence/search/grouping/auto-titling, and the JSON store's atomic writes,
corruption recovery and concurrent-write safety.

---

## 9. Example interactions

| You say (typed or spoken) | Assistant (shown, and spoken if enabled) |
|---|---|
| **Greeting** — `नमस्ते! तपाईंलाई कस्तो छ?` | नमस्ते! म ठिक छु, धन्यवाद। म रिमाइन्डर, काम, मौसम र फुटबलमा सहयोग गर्न सक्छु। |
| **Reminder** — `Remind me to call mum` | What time should I remind you about "call mum"? |
| ↳ follow-up — `tomorrow at eight` | ✅ Reminder saved: **call mum** — Fri 25 Sep 2026, 8:00 AM. |
| `मलाई हरेक महिनाको १ गते घरभाडा तिर्न सम्झाउनु।` | "घरभाडा तिर्ने" बारे कति बजे सम्झाऊँ? → `बिहान ९ बजे` → ✅ रिमाइन्डर सुरक्षित भयो … हरेक महिना। |
| `What reminders do I have today?` | Your reminders for today: - **call mum** — … |
| **Tasks** — `Add paying my electricity bill as a recurring monthly task` | 📝 Added **paying my electricity bill** to your tasks for September 2026, every month. |
| `मेरो रिपोर्टको काम पूरा भयो।` | 🎉 **प्रोजेक्ट रिपोर्ट** पूरा भयो भनेर चिन्ह लगाइयो। |
| `बाँकी रहेका काम देखाऊ।` | सेप्टेम्बर 2026 का बाँकी कामहरू (3 मध्ये 1 पूरा): … |
| **Weather** — `Is it raining in Pokhara right now?` | In Pokhara it's currently 24°C … ☀️ It is not raining right now. 🔮 Forecast for the rest of today: up to 65% chance of rain. |
| `Will it rain tomorrow?` (same conversation) | 🔮 Forecast for Pokhara on Fri 25 Sep: moderate rain … 🌧️ Rain is likely (80%). _This is a forecast, not current conditions._ |
| **Football** — `Show the Premier League standings` | 🏆 table from Football-Data.org + "last updated" time |
| `What were Barcelona's recent results?` | ⚽ Confirmed results — FC Barcelona 4 – 1 Sevilla FC … |
| `प्रिमियर लिगको ताजा समाचार सुनाऊ।` | 📰 समाचार (प्रकाशित लेखहरू — पुष्टि भएका खेल नतिजा होइनन्): 4–6 वाक्यको सारांश + स्रोतहरू |
| **Daily update** — `What's my update?` | 🌤️ weather + 📝 tasks due today + ✅ completed today + ⚠️ overdue + ⏰ today's reminders, in one reply |
| **Out of scope** — `Write my essay` | Sorry, I can only help with greetings, reminders, monthly tasks, the weather and football news. |

(Exact wording of LLM-generated greetings and summaries will vary.)

---

## 10. Presenting the project (suggested 10-minute demo)

1. **Problem & scope (1 min)** — a *focused* bilingual assistant for everyday needs in Nepal; why a
   limited scope, reached through one conversation, is more reliable and simpler than a
   general chatbot with separate feature dashboards.
2. **Architecture (2 min)** — show the diagram in §4: speech/text → intent (LLM + Pydantic) →
   deterministic services → templates → speech, all saved to the JSON store. Stress "facts never
   come from the LLM" and "one conversation reaches every feature".
3. **Live demo (5 min)**:
   * New chat → type "नमस्ते" → say "Remind me to submit my assignment" (tap 🎤) → answer the
     follow-up "today at <2 minutes from now>" by voice.
   * Ask *"काठमाडौंमा अहिले पानी परिरहेको छ?"*; point out the Nepali reply and spoken audio.
   * Ask for Premier League standings, then for Premier League news **in Nepali**, and show the
     sources and the "news ≠ confirmed results" label.
   * Add a recurring monthly task, then say "mark it as completed".
   * Rename and search conversations in the sidebar; by now the reminder pops up in the chat as a
     notification — the scheduler working live.
4. **Data-science angle (1 min)** — structured JSON logs (`logs/app.log`) can be loaded into pandas
   to analyse intent distribution, language mix, latency per service and error rates; open
   `data/conversations.json` to show the persisted, human-readable conversation store.
5. **Testing & limitations (1 min)** — run `pytest -q` (140 tests, all APIs mocked); honest limits below.

**Before the presentation:** run `python scripts/check_setup.py`, and have a backup screen recording
in case the venue Wi-Fi blocks the APIs.

## 11. Limitations (state them honestly)

* **Reminders only fire while the app is running.** Reliable notifications when it is closed would
  need an always-on deployed scheduler plus a delivery channel such as e-mail, SMS or push.
* Whisper sometimes labels Nepali speech as Hindi; this can occasionally show up as a mis-detected
  language for a short or unclear clip.
* Romanized Nepali input is understood, but replies are written in Devanagari (better for TTS).
* With an ElevenLabs key configured, Nepali speech uses `eleven_v3` (`eleven_multilingual_v2` does
  not include Nepali) and costs ElevenLabs credits; if the plan or model rejects Nepali, the app
  automatically falls back to edge-tts's native ne-NP voices — free, but an unofficial API that
  needs internet access to Microsoft's read-aloud service.
* Free tiers: NewsAPI articles are delayed and localhost-only; Football-Data.org scores may be delayed
  and live scores may be unavailable.
* The mic button needs one browser permission prompt for the microphone the first time you use it.

## 12. Security & privacy

* API keys come only from `.env` (git-ignored) and are never logged or displayed; the NewsAPI key is
  sent as a header, not in the URL.
* The app listens on `127.0.0.1` only and is designed as a **single-user local** app. If you deploy
  it publicly, set `APP_AUTH=username:password` at minimum, and add a `user_id` field to
  conversations, reminders and tasks so each user's data stays private.
* All user input is validated before saving/deleting (titles, dates, times, months, IDs); the LLM is
  told to treat messages and news text as data, not instructions; the JSON store validates every
  read against its schema and resets rather than trusting a corrupted or tampered file.
