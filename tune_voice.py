"""
Render one sentence in all six mood profiles so you can hear them back to back.

Tuning EMOTION_VOICE by talking to Zeta is painful - locally a turn costs ~15s and you
only hear whichever mood the model happened to pick. This skips the LLM entirely and
only needs the Style-Bert-VITS2 server on :5000, so you can leave Ollama shut down and
keep the ~5 GB of VRAM free while you iterate.

Loop:
    python tune_voice.py                       # writes tune/<mood>.wav for all six
    ... listen, edit EMOTION_VOICE in config.py ...
    python tune_voice.py                       # again

Options:
    python tune_voice.py -t "your own line here"
    python tune_voice.py -m curious -m flustered      # only these moods
    python tune_voice.py --per-mood                   # a line chosen to suit each mood
"""

import argparse
import os
import sys
import time

import requests

import config

OUT_DIR = "tune"

# One neutral line reads the parameter differences most clearly, because the words stay
# constant and only the delivery changes.
DEFAULT_LINE = "I've been thinking about what you said earlier, and I'm not sure I agree."

# ...but each mood also has a line that actually fits it, for judging whether a profile
# sounds right in context rather than just different.
PER_MOOD_LINES = {
    "pondering": "Hm. I think the premise might be wrong, actually.",
    "curious":   "Wait, say that again. That connects to something else.",
    "amused":    "Sure. That went about as well as you'd expect.",
    "flustered": "Oh. Um. I don't really know what to say to that.",
    "detached":  "It's fine. Nothing much happened today.",
    "earnest":   "I mean it. That mattered more to me than I let on.",
    "happy":     "Oh, that's actually really nice. I like that.",
    "excited":   "Wait, seriously? Tell me everything, right now.",
    "pouty":     "Fine. See if I tell you anything next time.",
}


def profile(mood: str) -> dict:
    """Same fallback logic as server.voice_profile, kept standalone so this script has
    no import-time dependency on the web server."""
    p = config.EMOTION_VOICE.get(mood, {})
    return {
        "style":        p.get("style", config.SBV2_STYLE),
        "style_weight": p.get("style_weight", config.SBV2_STYLE_WEIGHT),
        "sdp_ratio":    p.get("sdp_ratio", config.SBV2_SDP_RATIO),
        "noise":        p.get("noise", config.SBV2_NOISE),
        "noisew":       p.get("noisew", config.SBV2_NOISEW),
        "length":       p.get("length", config.SBV2_LENGTH),
    }


def render(mood: str, text: str) -> tuple[str, float]:
    prof = profile(mood)
    t0 = time.monotonic()
    r = requests.get(f"{config.SBV2_URL}/voice", params={
        "text": text, "model_id": config.SBV2_MODEL_ID, "speaker_id": config.SBV2_SPEAKER_ID,
        "language": config.SBV2_LANGUAGE, **prof,
    }, timeout=180)
    r.raise_for_status()
    path = os.path.join(OUT_DIR, f"{mood}.wav")
    with open(path, "wb") as f:
        f.write(r.content)
    return path, time.monotonic() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-t", "--text", default=None, help="line to speak (default: one fixed line)")
    ap.add_argument("-m", "--mood", action="append", dest="moods",
                    help="only render this mood (repeatable)")
    ap.add_argument("--per-mood", action="store_true",
                    help="use a different, mood-appropriate line for each")
    args = ap.parse_args()

    moods = args.moods or list(config.EMOTION_VOICE)
    unknown = [m for m in moods if m not in config.EMOTION_VOICE]
    if unknown:
        sys.exit(f"unknown mood(s): {', '.join(unknown)}\n"
                 f"available: {', '.join(config.EMOTION_VOICE)}")

    try:
        requests.get(f"{config.SBV2_URL}/docs", timeout=5).raise_for_status()
    except Exception:
        sys.exit(f"Style-Bert-VITS2 is not answering on {config.SBV2_URL}.\n"
                 f"Start it first (start.ps1 launches it, or run server_fastapi.py yourself).")

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"writing to {os.path.abspath(OUT_DIR)}\n")

    for mood in moods:
        text = args.text or (PER_MOOD_LINES.get(mood, DEFAULT_LINE) if args.per_mood
                             else DEFAULT_LINE)
        p = profile(mood)
        try:
            path, secs = render(mood, text)
        except Exception as e:
            print(f"  {mood:<10} FAILED: {e}")
            continue
        print(f"  {mood:<10} {p['style']:<9} w={p['style_weight']:<4} "
              f"len={p['length']:<5} sdp={p['sdp_ratio']:<5} -> {path}  ({secs:.2f}s)")
        if args.per_mood or args.text:
            print(f"             \"{text}\"")

    print(f"\nListen in order, then edit EMOTION_VOICE in config.py and run this again.")
    print("If a voice sounds distorted, lower that mood's style_weight first.")


if __name__ == "__main__":
    main()
