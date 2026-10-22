# JARVIS v2: the one that calls you

Inspired by "J", the Sarvam AI hackathon agent that called its builder
on a basketball court to say an assignment was still pending, and then
uploaded it for him.

JARVIS v2 takes the local JARVIS companion (v1) and gives it:

1. **A phone number.** It can call you, and you can call it back.
2. **A deadline watcher.** It checks your deadlines every 5 minutes and
   calls *you* first when one is close or overdue.
3. **Real laptop tools.** Find files and resumes, draft emails (never
   sends), open WhatsApp chats (never sends), play music, lock the
   screen, list deadlines and commitments. Add your own tool in about
   10 lines, exactly like in the reel.

Everything except the actual phone call runs **100% locally**: Ollama
brain, JSON memory, no cloud AI, no subscriptions. The phone call itself
uses Twilio (about $1.15/month for a US number, ~$0.014/min), and
Twilio's built-in speech, so no other API keys are needed. Sarvam AI
(Saaras/Bulbul) is supported as an optional speech upgrade for Indian
languages.

## Try it in 5 minutes (no accounts, no phone setup)

You need Python 3.10+ and [Ollama](https://ollama.com) for the full
chat brain. Tools and the watcher work even without Ollama.

```bash
pip install pyyaml

# 1. Simulated phone call: JARVIS "calls", you type, tools actually run
python main.py --phone-sim

# 2. Give it a deadline and watch it notice
cp data/deadlines.example.json data/deadlines.json   # edit the due time to ~1 hour from now
python main.py --watch-once                          # it will "call" you about it

# 3. Terminal chat with tools
python main.py --text
# try: "find my resume" / "what are my deadlines" / "draft an email to Alex about the interview"
```

## Make real phone calls (about 20 minutes)

1. Create a [Twilio](https://www.twilio.com) account and buy a US
   voice number (~$1.15/mo).
2. Copy `.env.example` to `.env` and fill in `TWILIO_ACCOUNT_SID`,
   `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER`.
3. Set `phone.provider: "twilio"` in `config.yaml`.
4. Start the server: `python main.py --serve` (listens on port 8765).
5. Expose it: `ngrok http 8765`, paste the https URL into
   `PUBLIC_BASE_URL` in `.env`, restart the server.
6. In the Twilio console, set your number's Voice webhook to
   `<PUBLIC_BASE_URL>/voice` (POST).
7. Call your Twilio number. JARVIS answers. Or run
   `python call_me.py --twilio --reason "Sir, testing the line"` and
   it calls you.
8. Leave `python main.py --watch` running and it will call you before
   deadlines, on its own.

Full step-by-step, including Windows notes and troubleshooting, is in
[PLAYBOOK.md](PLAYBOOK.md).

## Architecture

```
 deadlines.json ──> [watcher.py] ──alert──> [telephony.py]
                                                  │ simulated: terminal + transcript
                                                  │ twilio: real call to your phone
                                                  v
 your phone ──call──> [phone_server.py] ──> [conversation.py]
                        stdlib HTTP, TwiML      │ tool intents first
                                                │ then Ollama brain
                                                v
                                        [tools.py] find files, draft email,
                                        whatsapp, music, lock screen, ...
                                        [memory.py] facts, commitments, journal
                                        [brain.py] Ollama llama3.1:8b (local)
```

| Module | Job |
|---|---|
| `phone_server.py` | Twilio webhooks, TwiML, `/api/call-me`, pure stdlib |
| `telephony.py` | Simulated + Twilio providers, TwiML builder, optional Sarvam TTS |
| `watcher.py` | Deadline windows (24h, 2h, 30m, overdue), dedupe, proactive calls |
| `deadlines.py` | deadlines.json store |
| `conversation.py` | One brain for terminal, mic, and phone; tool intents + `[tool: ...]` tags |
| `tools.py` | The tool registry. Add yours here. |
| `call_me.py` | CLI to trigger a call right now |
| `main.py`, `brain.py`, `memory.py`, `persona.py`, `stt.py`, `tts.py`, `wakeword.py` | JARVIS v1, carried forward |

## Deadlines

Edit `data/deadlines.json` by hand, or say on a call:
"add deadline submit the Podium application by tomorrow".
On a call you can also say "mark deadline 2 done".

Seed it from the example: `cp data/deadlines.example.json data/deadlines.json`.

## Safety defaults

- Email and WhatsApp tools **draft only, never send**.
- Lock screen is a **dry run** until you set
  `tools.lock_screen_dry_run: false`.
- `/api/call-me` requires the `X-Jarvis-Secret` header when
  `JARVIS_API_SECRET` is set. Set it before exposing the server.
- `.env` is gitignored. Never commit real Twilio credentials.

## Tests

```bash
python -m pytest tests/ -q     # or: python -m unittest discover -s tests -v
```

## Roadmap

- Google Calendar and Gmail as deadline sources (the watcher currently
  reads deadlines.json; the store interface is ready for more sources).
- Streaming Sarvam Saaras/Bulbul instead of Twilio Gather/Say for
  Telugu/Hindi/English code-switching.
- This same code becomes the robot buddy's brain, as planned in v1.
