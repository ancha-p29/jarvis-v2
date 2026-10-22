#!/usr/bin/env python3
"""JARVIS v2: a local companion that can also CALL YOUR PHONE.

Everything from v1, plus the J treatment from the reel:
  python main.py --text        terminal chat, zero audio dependencies
  python main.py --check       diagnose the environment
  python main.py               laptop voice loop: wake word, listen, speak

  python main.py --phone-sim   simulated phone call in the terminal:
                               JARVIS "calls", you type replies, tools run
  python main.py --watch-once  check deadlines once, call about any alerts
  python main.py --watch       watcher loop (calls you before deadlines)
  python main.py --serve       phone server for real Twilio calls
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EXIT_PHRASES = ("goodbye", "good night", "shut down", "power off", "that is all")


def load_config(path: str | None = None) -> dict:
    import yaml
    cfg_path = Path(path) if path else ROOT / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def resolve(path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else ROOT / p


def build_brain(config: dict):
    import brain as brain_mod
    import memory as memory_mod
    import persona as persona_mod
    mem = memory_mod.Memory(resolve(config["memory"]["dir"]),
                            resolve(config["memory"]["journal_dir"]))
    return brain_mod.Brain(config, mem, persona_mod.build_system_prompt), mem


def build_conversation(config: dict):
    import memory as memory_mod
    import persona as persona_mod
    import brain as brain_mod
    from conversation import Conversation
    from deadlines import DeadlineStore
    from tools import ToolRegistry
    mem = memory_mod.Memory(resolve(config["memory"]["dir"]),
                            resolve(config["memory"]["journal_dir"]))
    brain = brain_mod.Brain(config, mem, persona_mod.build_system_prompt)
    if not brain.configured():
        brain = None
    deadlines = DeadlineStore(resolve(
        (config.get("watcher", {}) or {}).get("deadlines_file", "data/deadlines.json")))
    tools = ToolRegistry(config, deadlines=deadlines, memory=mem)
    conv = Conversation(config, memory=mem, brain=brain, tools=tools,
                        deadlines=deadlines)
    return conv, mem, deadlines


def check_environment(config: dict) -> bool:
    import brain as brain_mod
    import memory as memory_mod
    import persona as persona_mod
    ok = True

    def line(good: bool, msg: str) -> None:
        nonlocal ok
        print(f"[{'ok' if good else '!!'}] {msg}")
        ok = ok and good

    print("JARVIS v2 environment check")
    print(f"Python {sys.version.split()[0]} at {sys.executable}")
    mem = memory_mod.Memory(resolve(config["memory"]["dir"]),
                            resolve(config["memory"]["journal_dir"]))
    b = brain_mod.Brain(config, mem, persona_mod.build_system_prompt)
    if b.configured():
        line(b.is_up(), f"Brain API reachable: {b.describe()} (tools work without it too)")
    else:
        print("[!!] No brain API key set (full chat needs one, tools work without it)")
        print(b.missing_key_help())
        ok = False
    voice_path = resolve(config["tts"]["voice_model"])
    line(voice_path.exists(), f"Piper voice model: {voice_path} (laptop voice mode only)")
    for module, label in [("sounddevice", "sounddevice (mic/speaker)"),
                          ("faster_whisper", "faster-whisper (STT)"),
                          ("openwakeword", "openwakeword (wake word)"),
                          ("piper", "piper-tts (TTS)")]:
        try:
            __import__(module)
            line(True, f"{label} installed")
        except ImportError:
            line(False, f"{label} MISSING (only needed for laptop voice mode)")

    phone = config.get("phone", {}) or {}
    provider = phone.get("provider", "simulated")
    print(f"[info] Phone provider: {provider}")
    if provider == "twilio":
        import os
        from telephony import TwilioProvider
        missing = TwilioProvider().missing()
        if missing:
            print(f"[!!] Twilio missing env vars: {', '.join(missing)} (see .env.example)")
            ok = False
        else:
            print("[ok] Twilio env vars present")
    else:
        print("[ok] Simulated phone provider needs no accounts. You are testable today.")
    print()
    print("Text mode: python main.py --text")
    print("Simulated call: python main.py --phone-sim")
    return ok


def text_mode(config: dict) -> int:
    conv, _mem, _dl = build_conversation(config)
    bot_name = config.get("persona", {}).get("name", "JARVIS")
    print(f"{bot_name} v2 text mode. Tools are live. Type 'quit' to exit.\n")
    while True:
        try:
            user = input("You: ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if user.strip().lower() in ("quit", "exit"):
            break
        result = conv.handle(user)
        print(f"{bot_name}: {result['reply']}")
        if result.get("tool"):
            print(f"  (tool) {result['tool']['detail']}")
    return 0


def phone_sim_mode(config: dict) -> int:
    conv, _mem, deadlines = build_conversation(config)
    bot_name = config.get("persona", {}).get("name", "JARVIS")
    phone = (config.get("phone", {}) or {}).get("user_phone", "you")
    print(f"\nRing ring. {bot_name} is calling {phone} (simulated).")
    upcoming = deadlines.due_within(48)
    if upcoming:
        from deadlines import DeadlineStore
        first = upcoming[0]
        opening = (f"Sir, this is {bot_name}. Your deadline, {first['title']}, is "
                   f"{DeadlineStore.human_when(first)}. Shall we handle it?")
    else:
        opening = f"Sir, this is {bot_name} calling. No deadlines in the next 48 hours. What shall we handle?"
    print(f"{bot_name}: {opening}")
    print("Type what you would say on the call. 'goodbye' ends the call.\n")
    while True:
        try:
            user = input("You (on the phone): ")
        except (EOFError, KeyboardInterrupt):
            print()
            break
        result = conv.handle(user)
        print(f"{bot_name}: {result['reply']}")
        if result.get("tool"):
            print(f"  (tool) {result['tool']['detail']}")
        if result["exit"]:
            break
    print("Call ended.")
    return 0


def voice_mode(config: dict) -> int:
    import stt as stt_mod
    import tts as tts_mod
    import wakeword as wakeword_mod
    brain, _mem = build_brain(config)
    if not brain.configured():
        print(brain.missing_key_help())
        return 1
    audio_cfg = config.get("audio", {})
    mic, speaker = audio_cfg.get("mic_device"), audio_cfg.get("speaker_device")
    sample_rate = int(audio_cfg.get("sample_rate", 16000))
    stt_cfg = config.get("stt", {})
    listener = wakeword_mod.WakeWordListener(
        model_name=config["wakeword"]["model"],
        sensitivity=config["wakeword"]["sensitivity"], sample_rate=sample_rate)
    recognizer = stt_mod.SpeechToText(
        model_name=stt_cfg.get("model", "small"), device=stt_cfg.get("device", "cpu"),
        compute_type=stt_cfg.get("compute_type", "int8"),
        language=stt_cfg.get("language", "en"))
    speaker_out = tts_mod.TextToSpeech(resolve(config["tts"]["voice_model"]))
    bot_name = config.get("persona", {}).get("name", "JARVIS")
    print('Say "hey jarvis", then speak. Say "goodbye" to stop.\n')
    try:
        while True:
            print("Listening for 'hey jarvis'... (Ctrl+C to quit)")
            listener.wait(mic_device=mic)
            print("Listening...")
            text = recognizer.listen_once(sample_rate=sample_rate, mic_device=mic).strip()
            if not text:
                continue
            print(f"You: {text}")
            if any(p in text.lower() for p in EXIT_PHRASES):
                farewell = "Powering down, sir. Do try to stay out of trouble."
                print(f"{bot_name}: {farewell}")
                speaker_out.speak(farewell, speaker_device=speaker)
                break
            try:
                reply, _notes = brain.chat(text)
            except Exception as exc:
                reply = f"My apologies, sir, the model stumbled: {exc}"
            print(f"{bot_name}: {reply}")
            speaker_out.speak(reply, speaker_device=speaker)
    except KeyboardInterrupt:
        print("\nPowering down, sir.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="JARVIS v2, now with phone calls.")
    parser.add_argument("--text", action="store_true", help="Terminal chat, tools live.")
    parser.add_argument("--check", action="store_true", help="Diagnose the environment.")
    parser.add_argument("--phone-sim", action="store_true",
                        help="Simulated phone call in the terminal.")
    parser.add_argument("--watch-once", action="store_true",
                        help="Check deadlines once and call about alerts.")
    parser.add_argument("--watch", action="store_true", help="Watcher loop.")
    parser.add_argument("--serve", action="store_true",
                        help="Run the phone server for real Twilio calls.")
    parser.add_argument("--config", default=None, help="Path to config.yaml.")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.config)
    except FileNotFoundError:
        print("config.yaml not found next to main.py.")
        return 1
    except ImportError:
        print("pyyaml is missing. Run: pip install pyyaml")
        return 1

    if args.check:
        return 0 if check_environment(config) else 1
    if args.text:
        return text_mode(config)
    if args.phone_sim:
        return phone_sim_mode(config)
    if args.watch_once:
        import watcher as watcher_mod
        return watcher_mod.main(["--once"])
    if args.watch:
        import watcher as watcher_mod
        return watcher_mod.main(["--loop"])
    if args.serve:
        import phone_server
        return phone_server.main()
    return voice_mode(config)


if __name__ == "__main__":
    raise SystemExit(main())
