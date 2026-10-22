# JARVIS v2 Playbook (Windows first)

You downloaded this from GitHub. This playbook takes you from a fresh
clone to JARVIS calling your actual phone.

## Phase 0: Get the code

```powershell
git clone https://github.com/ancha-p29/jarvis-v2.git
cd jarvis-v2
```
No git? GitHub repo page, green Code button, Download ZIP, extract.

## Phase 1: Install the core (5 minutes)

You need Python 3.10+ (python.org, tick "Add python.exe to PATH").

```powershell
pip install pyyaml
python main.py --phone-sim
```

That is a full simulated call. JARVIS greets you, you type replies,
tools run for real: try "find my resume", "what are my deadlines",
"draft an email to Alex about the interview", "lock my screen"
(dry run, it will explain), then "goodbye".

Optional full brain: install Ollama from ollama.com, then
`ollama pull llama3.1:8b` and `ollama serve`. Without it, JARVIS
still answers with tools and deadlines (house rules mode).

## Phase 2: Deadlines and the watcher (5 minutes)

```powershell
copy data\deadlines.example.json data\deadlines.json
notepad data\deadlines.json
```
Set one deadline about an hour from now. Then:

```powershell
python main.py --watch-once
```
JARVIS "calls" (simulated) and writes a transcript in data\calls\.
Run `python main.py --watch` to leave the watcher on. It checks
every 5 minutes and alerts once per window: 24h, 2h, 30 min, overdue.

On any call you can also say: "add deadline finish the cover letter
by friday" and "mark deadline 1 done".

## Phase 3: Real phone calls with Twilio (about 20 minutes)

Costs: number about $1.15/month, US calls about $0.014/minute.
Free Twilio trial credit covers testing.

1. Sign up at twilio.com. Buy a voice-capable US number.
2. In the repo folder, copy `.env.example` to `.env` and fill in
   TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_PHONE_NUMBER
   (E.164 format, like +16175551234).
3. Edit config.yaml: set phone.provider to "twilio", confirm
   phone.user_phone is your cell in E.164 format.
4. Set real environment variables for this PowerShell session:
   ```powershell
   Get-Content .env | Where-Object { $_ -match '=' } | ForEach-Object {
     $k, $v = $_ -split '=', 2; Set-Item "env:$k" $v }
   ```
5. Start the server in its own window: `python main.py --serve`
6. Expose it (dev): install ngrok, run `ngrok http 8765`, copy the
   https URL into PUBLIC_BASE_URL in .env, reload env vars (step 4),
   restart the server.
7. Twilio console, Phone Numbers, your number, Voice configuration:
   webhook = `<PUBLIC_BASE_URL>/voice`, method POST. Save.
8. Test both directions:
   - Call the Twilio number from your cell. JARVIS answers.
   - `python call_me.py --twilio --reason "Sir, the line works"`
     and JARVIS calls you.
9. Set a JARVIS_API_SECRET in .env before leaving the server exposed.
   The watcher and call_me do not need the server for simulated
   calls, but real proactive calls do: the watcher asks Twilio to
   call you, and Twilio fetches the greeting from your server.

Keep three windows running for the full J experience:
server (`--serve`), watcher (`--watch`), and Ollama (`ollama serve`).

## Optional: Sarvam voices

The reel used Sarvam (Saaras listens, Sarvam-105B thinks, Bulbul
speaks). In v2, Twilio's built-in Gather/Say handles speech so you
need no extra key. If you want Bulbul's Indian-language TTS, set
SARVAM_API_KEY in .env; telephony.SarvamSpeech is the client, and
the README roadmap notes the streaming swap.

## Optional: laptop voice mode (v1)

Install the voice extras from requirements.txt (uncomment them),
download a Piper voice into data\voices\, run `python main.py --check`,
then `python main.py` and say "hey jarvis". Wake-word model files come
from the openwakeword package on first run.

## Troubleshooting

| Symptom | Fix |
|---|---|
| Twilio says missing env vars | Reload .env into the session (Phase 3, step 4), restart server |
| Twilio call connects but silence | Webhook URL wrong or ngrok stopped. Check PUBLIC_BASE_URL and the /voice POST setting |
| JARVIS answers but cannot hear long replies | Speak after the greeting finishes; Gather times out after silence |
| Watcher never calls | Deadline file is data\deadlines.json (not the .example), due time is in a window, state file not already marked. Delete data\watcher_state.json to re-test |
| Ollama offline message | `ollama serve` in its own window; tools still work without it |
| Port 8765 busy | Set PORT env var or phone.port in config.yaml |

## Make it yours

- Rename the assistant: persona.name in config.yaml.
- Change how it addresses you: persona.address_mode.
- Add a tool: copy any function in tools.py, decorate, restart.
  The model can call tools too by ending a reply with
  [tool: find_resume {"role": "product"}].
