"""Measure the DEPLOYED Zeta end to end, from inside Modal.

    python -m modal run probe_cloud.py::probe

Forces a cold start, then times two turns and taps the sleep button, printing every
sentence with the mood it was voiced in. Use it after a deploy, or whenever a turn feels
slow, instead of guessing from `modal app logs` - the CLI only hands back the last ~130
lines, which is not enough to reach a container's startup.

It runs INSIDE Modal on purpose: the ZETA_TOKEN secret is mounted into the probe container,
so the token never reaches a local terminal, shell history, or this file.

What healthy looks like (measured 2026-09-05, Cydonia-24B on an A10):

    cold start + health   ~89 s     health must report llm_warm and tts_warm true
    turn 1  TTFA          ~8.7 s    the one that still carries first-request cost
    turn 2  TTFA          ~1-2.7 s  the number you actually live with
    tagged                100%      anything under ~90% means read check_moods.py

Costs one cold start of A10 time (a few cents) per run, and leaves the container asleep
rather than idling for 15 minutes.
"""
import json
import os
import time

import modal

app = modal.App("zeta-probe")
image = modal.Image.debian_slim().pip_install("requests")
BASE = "https://gun-89398--zeta-zeta-web.modal.run"


@app.function(image=image, secrets=[modal.Secret.from_name("zeta-auth")], timeout=1800)
def probe():
    import requests

    s = requests.Session()
    s.cookies.set("zeta_auth", os.environ["ZETA_TOKEN"],
                  domain="gun-89398--zeta-zeta-web.modal.run")

    t0 = time.monotonic()
    h = s.get(f"{BASE}/api/health", timeout=900)
    cold = time.monotonic() - t0
    print(f"[probe] cold start + health: {cold:.1f}s -> {h.status_code} {h.text}")
    if h.status_code != 200:
        return

    def turn(text):
        t = time.monotonic()
        first_audio = None
        sents = []
        r = s.post(f"{BASE}/api/say", json={"text": text},
                   stream=True, timeout=600)
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            try:
                m = json.loads(line)
            except Exception:
                print("[probe] non-JSON:", line[:200]); continue
            if m.get("type") == "text":
                sents.append((m.get("mood"), m.get("text")))
            elif m.get("type") == "audio" and first_audio is None:
                first_audio = time.monotonic() - t
            elif m.get("type") == "error":
                print("[probe] ERROR event:", m.get("text"))
        total = time.monotonic() - t
        tagged = sum(1 for mood, _ in sents if mood)
        moods = sorted({mood for mood, _ in sents if mood})
        print(f"[probe] {text!r}")
        print(f"        TTFA {first_audio if first_audio is None else round(first_audio,2)}s"
              f"  total {total:.1f}s  {len(sents)} sentences"
              f"  tagged {tagged}/{len(sents)}  moods={moods}")
        for mood, txt in sents:
            print(f"          [{mood}] {txt}")
        return first_audio

    print("\n[probe] --- turn 1 (the one that used to cost ~33 s) ---")
    turn("Hey, can you hear me?")
    print("\n[probe] --- turn 2 (warm baseline) ---")
    turn("Do you think people are more like systems or more like stories?")

    print("\n[probe] --- sleep ---")
    t = time.monotonic()
    r = s.post(f"{BASE}/api/sleep", timeout=120)
    print(f"[probe] /api/sleep -> {r.status_code} {r.text} in {time.monotonic()-t:.1f}s")
