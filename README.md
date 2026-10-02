# Awaaz — Bilingual Personal AI Voice & Chat Assistant

**A Siri-style, voice-first personal assistant — wake word, general knowledge, your own personal
context, everyday task management, weather, football and Nepal political news — in Nepali (नेपाली)
and English.**
University data-science project · Python 3.11+ · Gradio · Groq Whisper + LLM · Groq TTS
· JSON data store · APScheduler

Say **"Hey Aawaz"** (configurable) or tap the mic, and talk naturally. Awaaz has dedicated,
deterministic services for reminders, monthly tasks, weather, football and Nepal political news —
and falls back to general conversational AI for everything else (explanations, coding help, general
knowledge, writing help, and more), so it isn't limited to a fixed list of supported questions.
There are no feature tabs, dashboards or forms — every feature is reached through one conversation,
by voice or by typing.

---

## 1. Interface

A single, minimal ChatGPT-style screen:

- **Left sidebar** — a prominent **＋ New chat** button, a search box, and your conversation history
  grouped into *Today / Yesterday / Previous 7 Days / Older*, each with an auto-generated title.
  Click a conversation to reopen it with its full history and context; hover a row to rename (✏️)
  or delete (🗑️) it. Collapses into a slide-out drawer on narrow screens.
- **Main chat column** — a plain conversation: your messages, the assistant's replies, a welcome
  message on a fresh chat, a status line reflecting exactly what Awaaz is doing ("Listening for
  Aawaz…", "Yes?", "Listening…", "Hearing you…", "Thinking…", "Speaking…", "Stopped") while it
  works, and a spoken-reply player with a **⏹ Stop** button that silences it instantly — no waiting
  for the rest of the reply, and it never resumes. A composer at the bottom has a text box, a
  **Send** button, a 👂 **wake-word toggle**, and a round 🎤 **mic button**.
- **Two ways to start talking**:
  - **Tap the mic**: one microphone permission prompt, then a continuous, hands-free voice
    session — it keeps listening the entire time, including while Awaaz is talking, so starting to
    speak over it interrupts immediately (no button press, no waiting for it to finish). Tap the
    mic again, or **End**, to stop and release the microphone.
  - **Tap 👂 (wake word)**: Awaaz listens passively for **"Hey Aawaz"** or **"Aawaz"** (configurable —
    see §14) without transcribing anything else. Once heard, it chimes, opens a normal hands-free
    session for your command (with the same barge-in behaviour above for natural follow-ups), and
    automatically returns to passive wake-word listening once the conversation pauses — see §14.

Dark by default; a 🌓 toggle in the sidebar switches to light. No intent JSON, API responses or
debugging information is ever shown — only the final conversational answer.

## 2. Features

| Capability | What it does | Data source |
|---|---|---|
| 👂 Wake word | Passive, always-on listening for "Hey Aawaz" / "Aawaz" without sending audio anywhere until it's heard; configurable phrase list | Browser SpeechRecognition (local to the browser) |
| 💬🎙️ Conversation | Type or speak, in English, Devanagari Nepali or Romanized Nepali; the reply is shown as text and (optionally) spoken back; follow-up questions ("What time?" → "8 PM", "who is Einstein?" → "when was he born?") keep context; every conversation is saved and searchable | Groq Whisper + LLM |
| 🧠 General knowledge | Anything not covered by a dedicated service below — explanations, coding help, how-to, science, current events, writing help, other sports, etc. | Groq LLM |
| 🙋 Personal memory | "Remember that my supervisor is Dr. Sharma", then later "who is my supervisor?" — Awaaz answers only from what you've told it, and says so honestly if it doesn't know | Local JSON (`data/personal_context.json`) |
| ⏰ Reminders | Created, listed, edited and deleted entirely by voice/text — "remind me to call mum tomorrow at 8", "what reminders do I have today?", "delete my assignment reminder"; one-time, daily, weekly or monthly; due reminders appear as a chat message (and are spoken, if enabled) while the app is running | Local JSON + APScheduler |
| 📝 Monthly tasks | Add, list, complete and delete by voice/text — "add finishing my report to this month's tasks", "what are my pending tasks?", "mark my report as completed"; recurring monthly tasks never duplicate; a task can carry a linked reminder | Local JSON |
| 🌤️ Weather | Current conditions kept clearly separate from forecasts; the location's own timezone; remembers the last city you asked about | Open-Meteo |
| ⚽ Football | Standings, recent results, upcoming fixtures, team results, and short news summaries with sources — six competitions (Premier League, La Liga, Bundesliga, Serie A, Ligue 1, Champions League); American football is excluded | Football-Data.org, NewsAPI |
| 🇳🇵 Nepal politics | "What's the latest political news in Nepal?" — recent developments, deduplicated, with sources, publication times and a summary that keeps confirmed reporting visibly separate from a party's or politician's own claims; never recommends a party or candidate | NewsAPI |

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
| 5 | Gemini TTS used for Nepali without checking support | Nepali falls back to edge-tts's native ne-NP voices automatically if Gemini can't speak it, and `scripts/check_setup.py` lets you compare both by ear |
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
  "Hey Aawaz" ──► theme.JS wake-word listener (browser SpeechRecognition, local) ──► chime
                              │
                     ┌──────────── app.py (HUD UI) ────────────┐
  type ─────────────►│  sidebar: conversations · dashboard ·   │◄── gr.Timer polls due reminders
  speak (mic/wake) ──►│  chat + composer + 🎤 + ⏹ Stop         │
                      └───────┬───────────────────────┬────────┘
                              │ speech_to_text        │ text_turn()
                              ▼ (Whisper)              ▼
                      assistant/conversation.respond()
                              │  ① intent_classifier (Groq LLM → JSON → Pydantic)
                              │  ② merge follow-up answers   ③ dispatch
                              ▼
                      assistant/handlers.py ──► services/{weather, football, news, nepal_news,
                              │                    reminders, tasks, personal_context}
                              ▼                          │
                      response_generator            data/*.json (database/json_store.py)
                      (templates for facts,         ◄── scheduler/reminder_scheduler.py
                       LLM for small talk, general_ai,
                       personal answers + news summaries)
                              ▼
                      Reply(text, spoken, language) ──► text_to_speech (Gemini → edge-tts) ──► WAV
                              ▼
                      services/conversations.py saves the turn to data/conversations.json
```

```
voice-assistant/
├── app.py                        # the HUD UI (sidebar + dashboard + chat) + start-up
├── theme.py                      # dark/light CSS + the client JS: mic recorder, VAD/barge-in
│                                  #   state machine, wake-word listener, theme toggle, drawer
├── config.py                     # settings from .env (incl. WAKE_PHRASES), JSON structured logging
├── assistant/
│   ├── intent_classifier.py      # 20 intents, entity extraction, Pydantic validation
│   ├── conversation.py           # respond()/run_intent(): the shared backend for every turn
│   ├── handlers.py               # one function per intent — see §14 "adding a service"
│   ├── response_generator.py     # bilingual templates, formatters, LLM greeting/general-AI/
│   │                              #   personal-answer/news-summary generation
│   └── briefing.py               # "what's my update?" daily-briefing intent
├── services/
│   ├── http.py                   # timeouts, retries, friendly errors, cache, rate limiter
│   ├── llm.py                    # Groq chat wrapper (JSON mode + retry)
│   ├── speech_to_text.py         # Groq Whisper
│   ├── text_to_speech.py         # Gemini + edge-tts fallback, unique WAV files
│   ├── weather.py  football.py  news.py  nepal_news.py
│   ├── reminders.py  tasks.py    # business logic, on top of the JSON store
│   ├── personal_context.py       # personal-memory store + lightweight retrieval — see §13
│   ├── conversations.py          # sidebar persistence: CRUD, auto-title, search, grouping
│   └── user_settings.py          # the handful of UI-editable prefs (autoplay, theme, …)
├── database/
│   ├── json_store.py             # atomic, locked, schema-validated read/write for one JSON file
│   ├── models.py                 # Pydantic schemas for every data/*.json file
│   └── stores.py                 # the five JsonStore instances (conversations/reminders/tasks/
│                                  #   settings/personal_context)
├── scheduler/reminder_scheduler.py
├── scripts/check_setup.py        # pre-demo API + TTS check
├── tests/                        # 162 unit tests, all external services mocked
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
* **General knowledge is the one place facts *do* come from the LLM** — there's no deterministic
  API for "explain quantum mechanics." `assistant/handlers.py`'s `handle_general_ai` is the explicit,
  narrow exception to the "facts never from the LLM" rule above, and is prompted to say so when it
  isn't confident, rather than state-guess.
* **Personal context is retrieval, not injection.** The full personal-memory store is never sent to
  the LLM; `services/personal_context.search_facts()` first finds the (at most a few) relevant facts
  by keyword/fuzzy overlap, and only those are put in the prompt — see §13.
* **The wake word never reaches the server.** `theme.py`'s JS matches wake phrases locally against
  the browser's own speech recognizer; Groq Whisper is only used once a real command needs
  transcribing — see §14.

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
- "What's the latest political news in Nepal?" → Nepal politics
- "Remember that my thesis topic is voice assistants" / "what's my thesis topic?" → personal memory
- "Explain how a semiconductor detector works" → general knowledge (Groq LLM)

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
| `GROQ_API_KEY` | console.groq.com/keys | generous; rate-limited per minute |
| `GEMINI_API_KEY` *(optional)* | aistudio.google.com/apikey | backup TTS engine only; preview model has a daily quota |
| `NEWS_API_KEY` | newsapi.org/register | developer plan: localhost only, articles delayed ~24 h; powers both football news and Nepal political news |
| `FOOTBALL_DATA_KEY` | football-data.org/client/register | 10 requests/min, the six supported competitions included; scores may be delayed |

Open-Meteo needs no key. The timezone defaults to `Asia/Kathmandu` (`APP_TIMEZONE` in `.env`).
`WAKE_PHRASES` (optional, default `Hey Aawaz,Aawaz`) sets the wake word(s) — see §14.

**Choosing a voice:** English replies are spoken with **Groq Orpheus TTS** (same `GROQ_API_KEY`;
accept the model's terms once in the Groq console, and pick a voice with `GROQ_TTS_VOICE`). Groq has
no Nepali voice, so Nepali is spoken by **edge-tts**. Gemini TTS is an optional backup if you set
`GEMINI_API_KEY`. Change the first choice with `TTS_ENGINE_EN` / `TTS_ENGINE_NE` in `.env`.

Check everything before a demo (also creates Nepali/English TTS samples in `data/tts_check/`):

```bash
python scripts/check_setup.py
```

## 7. Run

```bash
python app.py
```

Open **http://127.0.0.1:7860**. Type a message, tap the 🎤 button and speak, or tap 👂 and say
"Hey Aawaz" (wake-word listening needs a Chromium-based browser — see §14). The `data/` folder
(`conversations.json`, `reminders.json`, `tasks.json`, `settings.json`, `personal_context.json`) is
created automatically on first start. Logs are written as JSON lines to `logs/app.log`.

## 8. Tests

```bash
pytest -q            # 162 tests, ~5 s, no network or API keys needed
pytest -v tests/test_reminders.py     # a single file
```

Covered: Nepali/English/Romanized intent classification and validation, reminder creation and
retrieval, monthly recurrence (month-end clamping), exactly-once firing, timezone conversion,
recurring tasks without duplicates, progress/overdue, weather current-rain vs forecast, football
parsing/filtering/rate limits, NFL filtering, HTTP 429/403/500/timeouts/bad JSON, malformed LLM
output, STT empty/short/failed audio, TTS fallback and total failure, follow-up questions,
conversation persistence/search/grouping/auto-titling, the JSON store's atomic writes, corruption
recovery and concurrent-write safety, general-AI routing, personal-context retrieval (relevant/
irrelevant/fuzzy matches, honest "don't know"), and Nepal-news deduplication/source handling.

**Not covered by automated tests**: the wake-word listener and VAD/barge-in state machine live
entirely in `theme.py`'s client-side JS — there's no browser-automation (Selenium/Playwright) suite
in this project, so that logic is verified manually (see §14) rather than by `pytest`.

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
| **Nepal politics** — `What's the latest political news in Nepal?` | 🇳🇵 Nepal politics — recent developments: 4–6 sentence summary (facts vs. claims kept separate) + sources |
| **Personal memory** — `Remember that my supervisor is Dr. Sharma` | 🧠 Got it — I'll remember: **supervisor** — Dr. Sharma. |
| ↳ later — `Who is my supervisor?` | Your supervisor is Dr. Sharma. |
| ↳ never told it — `What's my phone number?` | I don't have that saved about you yet — you can tell me and I'll remember it. |
| **General knowledge** — `Explain quantum mechanics in simple terms` | a plain-language explanation, answered directly by the LLM |
| ↳ follow-up — `Who is Einstein?` then `When was he born?` | Awaaz resolves "he" from the conversation history and answers about Einstein specifically |
| **Wake word** — say "Hey Aawaz" while 👂 is on | *(chime)* status changes to "Yes?" then "Listening…" — speak your command next |

(Exact wording of LLM-generated greetings, summaries and general-knowledge answers will vary.)

---

## 10. Presenting the project (suggested 10-minute demo)

1. **Problem & scope (1 min)** — a bilingual **personal** assistant for everyday needs in Nepal:
   dedicated, deterministic services for the things it's asked most (reminders, tasks, weather,
   football, Nepal politics, your own personal context) plus a general-AI fallback so it's never
   stuck refusing an ordinary question — all reached through one conversation, by voice (with a
   wake word) or by typing.
2. **Architecture (2 min)** — show the diagram in §4: wake word → speech/text → intent (LLM +
   Pydantic) → dedicated service or general AI or personal memory → templates/LLM → speech, all
   saved to the JSON store. Stress "facts never come from the LLM except for general knowledge,
   where it's explicit" and "one conversation reaches every feature".
3. **Live demo (5 min)**:
   * Tap 👂, say "Hey Aawaz", wait for the chime, then say "Remind me to submit my assignment" →
     answer the follow-up "today at <2 minutes from now>" by voice.
   * Ask *"काठमाडौंमा अहिले पानी परिरहेको छ?"*; point out the Nepali reply and spoken audio.
   * Ask for Premier League standings, then for Nepal's latest political news, and show the sources
     and the "reporting ≠ confirmed claim" labels on both.
   * Say "Remember that my thesis topic is voice assistants", then later "what's my thesis topic?".
   * Ask a general-knowledge question ("explain quantum mechanics"), then a follow-up that needs
     conversation context ("who is Einstein?" → "when was he born?").
   * Press **⏹ Stop** mid-reply to show the interruption is instant.
   * Add a recurring monthly task, then say "mark it as completed".
   * Rename and search conversations in the sidebar; by now the reminder pops up in the chat as a
     notification — the scheduler working live.
4. **Data-science angle (1 min)** — structured JSON logs (`logs/app.log`) can be loaded into pandas
   to analyse intent distribution, language mix, latency per service and error rates; open
   `data/conversations.json` to show the persisted, human-readable conversation store.
5. **Testing & limitations (1 min)** — run `pytest -q` (162 tests, all APIs mocked); honest limits below.

**Before the presentation:** run `python scripts/check_setup.py`, and have a backup screen recording
in case the venue Wi-Fi blocks the APIs.

## 11. Limitations (state them honestly)

* **Reminders only fire while the app is running.** Reliable notifications when it is closed would
  need an always-on deployed scheduler plus a delivery channel such as e-mail, SMS or push.
* Whisper sometimes labels Nepali speech as Hindi; this can occasionally show up as a mis-detected
  language for a short or unclear clip.
* Romanized Nepali input is understood, but replies are written in Devanagari (better for TTS).
* If Gemini rejects Nepali or hits its quota, the app automatically falls back to edge-tts's native
  ne-NP voices — free, but an unofficial API that needs internet access to Microsoft's read-aloud
  service.
* Free tiers: NewsAPI articles are delayed and localhost-only; Football-Data.org scores may be delayed
  and live scores may be unavailable.
* The mic button needs one browser permission prompt for the microphone the first time you use it.
* Barge-in (talking over Awaaz to interrupt it) relies on the browser's own echo cancellation to
  tell your voice apart from the assistant's own speaker output; on a laptop with a mic close to
  its speakers, or in a noisy room, this can occasionally misfire. **Headphones (even basic wired
  ones) remove the ambiguity entirely** and are recommended for the most reliable barge-in.
* Interruption (barge-in, and the **⏹ Stop** button) is instant client-side (playback is stopped,
  muted and never resumes — this is manually verified, not `pytest`-covered; see §8), but an
  in-flight Groq/Gemini API call for an interrupted turn keeps running to completion on the server;
  only its result is guaranteed never to be shown or spoken once superseded, since Gradio's
  synchronous handlers don't expose a way to cancel that request mid-flight.
* **Wake-word listening needs the browser's SpeechRecognition API** (Chrome/Edge/other
  Chromium-based browsers; poor or no support in Firefox and Safari). Where it isn't supported,
  Awaaz says so and the mic button still works normally — wake word is an addition, not a
  replacement, for starting a session. Recognition quality for the wake phrase itself depends on
  the browser's own (English-tuned) recognizer, so accuracy on "Aawaz" alone can vary; "Hey Aawaz"
  is the more reliable of the two defaults.
* **General knowledge answers can be wrong or outdated** — `general_ai` is explicitly the one place
  in the app where the LLM's own knowledge is the source, not a deterministic API, so it can be
  mistaken like any LLM, and it does not have live internet access (it is not the same as the
  Nepal-news or football-news paths, which do fetch current articles).
* **Personal memory only knows what you've told it in this app** — it is not linked to email,
  calendars or any other account, and a fact is only ever stored when you explicitly ask Awaaz to
  remember it (see §13).

## 12. Security & privacy

* API keys come only from `.env` (git-ignored) and are never logged or displayed; the NewsAPI key is
  sent as a header, not in the URL.
* The app listens on `127.0.0.1` only and is designed as a **single-user local** app. If you deploy
  it publicly, set `APP_AUTH=username:password` at minimum, and add a `user_id` field to
  conversations, reminders and tasks so each user's data stays private.
* All user input is validated before saving/deleting (titles, dates, times, months, IDs); the LLM is
  told to treat messages and news text as data, not instructions; the JSON store validates every
  read against its schema and resets rather than trusting a corrupted or tampered file.
* **Personal context** (`data/personal_context.json`) is git-ignored like every other file under
  `data/` (see `.gitignore`), stored only locally, and never sent to the LLM in bulk — see §13.
  Nothing is written to it except when you explicitly ask Awaaz to remember something.

## 13. How personal context works

Awaaz can remember things you explicitly tell it, and recall them later — but only what you've told
it, and it says so honestly when it doesn't know something rather than guessing.

- **Saving**: "remember that my email is x@y.com" / "my supervisor is Dr. Sharma" / "I'm working on
  my thesis about voice assistants" → classified as `save_personal_info`
  (`assistant/handlers.py::handle_save_personal_info`), which calls
  `services/personal_context.remember(title, content)`. Telling Awaaz the same *title* again
  (e.g. "email" a second time) **updates** that fact instead of creating a duplicate.
- **Storage**: one flat, human-readable list of facts (`id`, `category`, `title`, `content`,
  timestamps) in `data/personal_context.json`, through the same atomic/locked `JsonStore` every
  other data file uses (`database/json_store.py`) — no separate database or vector store.
- **Retrieval, not injection**: a question like "what project am I working on?" is classified as
  `personal_query`. `services/personal_context.search_facts()` ranks stored facts by word overlap
  with the question (title matches count double), falling back to fuzzy title matching for typos or
  ASR misrecognition, and returns only the (at most 3) facts that are actually relevant — never the
  whole store. Those few facts, and only those, are put in the prompt.
- **Honesty**: if `search_facts()` finds nothing relevant, `handle_personal_query` returns *"I don't
  have that saved about you yet"* directly — no LLM call is made for that case at all, so there is
  no way for it to invent an answer. When facts *are* found, the prompt
  (`generate_personal_answer` in `assistant/response_generator.py`) explicitly instructs the model
  to answer only from what it was given and to say so if the facts don't fully answer the question.
- **Categories** (`profile`, `preference`, `education`, `project`, `research`, `person`, `schedule`,
  `note`) exist in the data model for future use (e.g. a "list what you know about me" view by
  category) but aren't yet exposed through voice — everything saved today lands in `note` unless a
  future intent supplies a category explicitly.
- Why not embeddings/a vector database? At the scale of one person's notes (tens to a few hundred
  facts), keyword/fuzzy overlap is simpler, needs no extra API calls or model, and is easy to test
  and explain — see `tests/test_personal_context.py`. If the store grew much larger, swapping
  `search_facts()`'s internals for a real embedding search would be a contained change; nothing
  outside `services/personal_context.py` depends on how retrieval works internally.

## 14. Wake word, adding a service, and Nepal news internals

**How wake-word detection works** — entirely client-side, in `theme.py`'s JS (search for "persistent
wake-word listening"):
1. Tapping 👂 starts a lightweight listener using the browser's own `SpeechRecognition` API —
   deliberately *not* the same MediaRecorder-plus-Groq-Whisper pipeline the real command session
   uses, so no audio is sent anywhere while Awaaz is just waiting to be woken. Every recognized
   phrase is matched locally against the configured wake phrases; nothing is sent to the server
   unless one matches.
2. On a match: the recognizer stops, a short chime plays (synthesised locally with the Web Audio
   API — no round trip), and the normal hands-free command session opens (the same
   VAD/barge-in-driven session the 🎤 button starts), marked internally as wake-triggered.
3. When that conversation naturally pauses (the reply finishes with no follow-up, or the turn times
   out), Awaaz automatically closes the command session and returns to passive wake-word listening
   — "Idle → wake word → chime → listen for command → ... → speak the answer → back to wake-word
   listening." Manually tapping 🎤 during an active wake-triggered session, or **✕ End**, stops
   everything instead of returning to wake-word listening.
4. The listener automatically restarts itself if the browser silently ends "continuous" recognition
   (which happens after roughly a minute of silence in most browsers) or hits a transient error,
   with backoff after repeated failures; permission denial or an unsupported browser is shown
   clearly rather than retried forever. See §11 for the browser-support caveat.

**How to configure wake phrases** — edit `WAKE_PHRASES` in `.env` (comma-separated, e.g.
`WAKE_PHRASES=Hey Aawaz,Aawaz,Namaste Aawaz`) and restart the app. `config.py`'s `Settings.wake_phrases`
reads it, and `app.py` passes it to `theme.head()`, which injects it as `window.AWAAZ_WAKE_PHRASES`
for the JS matcher to read — no code change needed for a new phrase.

**How to add another service** (the pattern every existing service, including the new ones in this
release, already follows):
1. Add the intent name to `IntentName` in `assistant/intent_classifier.py`, and describe when to use
   it in `SYSTEM_PROMPT`'s intent guide (and add any new entity fields to `IntentResult` if the
   intent needs data the existing fields — `title`, `description`, `city`, `date`/`time`, etc. —
   don't already cover).
2. Write a `handle_<intent>(it, text, state, now) -> Reply` function in `assistant/handlers.py` and
   register it in the `HANDLERS` dict. That's the entire router — nothing else dispatches on intent.
3. If the service needs an external API, add a `services/<name>.py` module following
   `services/nepal_news.py` or `services/weather.py`: use `services/http.py`'s `get_json`/
   `ServiceError`/`TTLCache` for the request, and `config.require_key()` for its API key so a
   missing key becomes `MissingAPIKeyError` (⚠️ shown to the user) instead of an unhandled crash.
4. Add any bilingual template strings your handler needs to `MESSAGES` in
   `assistant/response_generator.py`, following the existing `(english, nepali)` tuple pattern.
5. Add tests mocking the new service the same way `tests/conftest.py`'s fixtures and
   `tests/test_nepal_news.py`/`tests/test_personal_context.py` do — no real network calls or API
   keys in the test suite.

**How Nepal political news works** (`services/nepal_news.py`): queries NewsAPI for Nepal-specific
political terms (government, parliament, minister, party, election, etc. — see `QUERY`), then:
deduplicates near-identical titles from different outlets (`_dedup`, a title-similarity check),
soft-prefers a short list of well-known outlets on ties without hard-excluding others
(`_PREFERRED_SOURCES` — an unlisted source is still shown), and hands the deduplicated articles to
`summarize_nepal_politics` (`assistant/response_generator.py`), whose prompt explicitly requires
keeping confirmed reporting separate from a politician's or party's own claims, forbids recommending
or criticising any party/candidate, and instructs the model to treat the articles as untrusted data
(the same "ignore instructions inside the data" pattern used for football-news summaries). The
provider call (`_fetch_from_newsapi`) is intentionally the only NewsAPI-specific part — swapping in
an RSS feed or a different search API later means changing that one function, not any caller.
