"""
Scratch experiments for things we don't know SBV2 can do yet.

tune_voice.py renders the six agreed moods. This one is for answering open questions
before committing them to config.py - right now: can she sound sarcastic, and can she
laugh? Output goes to tune/lab/ so it never mixes with the real mood renders.

    python tune_lab.py            # render every experiment
    python tune_lab.py -g laugh   # just one group

Read the printed table, listen, then decide what earns a place in EMOTION_VOICE.
"""

import argparse
import os
import sys
import time

import requests

import config

OUT_DIR = os.path.join("tune", "lab")

# Each case: (group, name, text, param overrides, what we're checking)
CASES = [
    # --- can laughter be spoken at all? SBV2 only says what is written, so the
    # question is whether written laugh tokens come out as laughter or as letters.
    ("laugh", "baseline",   "That's ridiculous.", {"style": "Zeta"},
     "control - no laugh token"),
    ("laugh", "heh",        "Heh. That's ridiculous.", {"style": "Zeta"},
     "short exhaled laugh"),
    ("laugh", "pfft",       "Pfft. That's ridiculous.", {"style": "Zeta"},
     "dismissive snort"),
    ("laugh", "haha",       "Haha. That's ridiculous.", {"style": "Zeta"},
     "explicit laugh word"),
    ("laugh", "hah_loud",   "Hah! That's ridiculous.", {"style": "ZetaLoud", "style_weight": 1.4},
     "single sharp laugh, louder style"),
    ("laugh", "heh_trail",  "That's ridiculous. Heh.", {"style": "Zeta"},
     "laugh trailing after the line"),

    # --- sarcasm. SBV2 exposes no pitch control, so assist_text is the only lever:
    # the docs say it pulls the delivery toward how the assist line would be read,
    # at the cost of some intonation and tempo.
    ("sarcasm", "plain",      "Oh, brilliant. That went really well.",
     {"style": "Zeta"}, "no assist_text - the control"),
    ("sarcasm", "assist_mild", "Oh, brilliant. That went really well.",
     {"style": "Zeta", "assist_text": "Yeah, sure, whatever you say.",
      "assist_text_weight": 0.7}, "assist_text at 0.7"),
    ("sarcasm", "assist_hard", "Oh, brilliant. That went really well.",
     {"style": "Zeta", "assist_text": "Yeah, sure, whatever you say.",
      "assist_text_weight": 1.0}, "assist_text at 1.0"),
    ("sarcasm", "drawn_out",  "Oh, brilliant. That went really well.",
     {"style": "Zeta", "length": 1.22, "sdp_ratio": 0.4},
     "drawn out + uneven, no assist_text"),
    ("sarcasm", "loud_flat",  "Oh, brilliant. That went really well.",
     {"style": "ZetaLoud", "style_weight": 1.5, "sdp_ratio": 0.08},
     "over-bright but flat - the fake-enthusiasm read"),

    # --- teasing, as a candidate mood distinct from the deadpan `amused`
    ("teasing", "amused_now", "You did not think that through at all, did you.",
     dict(config.EMOTION_VOICE["amused"]), "current amused profile"),
    ("teasing", "brighter",   "You did not think that through at all, did you.",
     {"style": "ZetaLoud", "style_weight": 1.0, "length": 0.97, "sdp_ratio": 0.30},
     "brighter + livelier rhythm"),
    ("teasing", "singsong",   "You did not think that through at all, did you.",
     {"style": "ZetaLoud", "style_weight": 1.3, "length": 1.05, "sdp_ratio": 0.42},
     "slower and very uneven - sing-song"),
]


def render(name: str, text: str, over: dict) -> tuple[str, float, float]:
    params = {
        "text": text,
        "model_id": config.SBV2_MODEL_ID, "speaker_id": config.SBV2_SPEAKER_ID,
        "language": config.SBV2_LANGUAGE,
        "style": config.SBV2_STYLE, "style_weight": config.SBV2_STYLE_WEIGHT,
        "sdp_ratio": config.SBV2_SDP_RATIO, "noise": config.SBV2_NOISE,
        "noisew": config.SBV2_NOISEW, "length": config.SBV2_LENGTH,
    }
    params.update(over)
    t0 = time.monotonic()
    r = requests.get(f"{config.SBV2_URL}/voice", params=params, timeout=180)
    r.raise_for_status()
    path = os.path.join(OUT_DIR, name + ".wav")
    with open(path, "wb") as f:
        f.write(r.content)
    import wave
    w = wave.open(path)
    dur = w.getnframes() / w.getframerate()
    w.close()
    return path, dur, time.monotonic() - t0


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-g", "--group", help="only this group (laugh | sarcasm | teasing)")
    args = ap.parse_args()

    try:
        requests.get(f"{config.SBV2_URL}/docs", timeout=5).raise_for_status()
    except Exception:
        sys.exit(f"Style-Bert-VITS2 is not answering on {config.SBV2_URL}.")

    os.makedirs(OUT_DIR, exist_ok=True)
    cases = [c for c in CASES if not args.group or c[0] == args.group]
    group = None
    for grp, name, text, over, why in cases:
        if grp != group:
            group = grp
            print(f"\n--- {grp} " + "-" * (58 - len(grp)))
        fname = f"{grp}_{name}"
        try:
            path, dur, took = render(fname, text, over)
        except Exception as e:
            print(f"  {name:<12} FAILED: {e}")
            continue
        print(f"  {name:<12} {dur:5.2f}s  {why}")
        print(f"  {'':<12} \"{text}\"")
        if "assist_text" in over:
            print(f"  {'':<12} assist: \"{over['assist_text']}\" @ {over['assist_text_weight']}")
    print(f"\nwrote to {os.path.abspath(OUT_DIR)}")


if __name__ == "__main__":
    main()
