"""
Measure whether the LLM actually obeys the mood-tag format.

The whole emotion system rests on the model emitting a tag on every sentence. That is an
assumption, and it has already been wrong once: with Lumimaid every captured request went
out as the neutral style, including plainly excited lines. This turns "will it work?" into
two numbers - how often a tag appears at all, and whether the moods are actually varied.

It calls Ollama directly, so no TTS and no web server are involved.

    python check_moods.py                     # ~8 prompts against the configured model
    python check_moods.py -n 3                # fewer, for a quick look
    python check_moods.py --model <tag>       # compare a different model
    python check_moods.py --persona cheerful  # the other persona's mood set
    python check_moods.py --show              # print every tagged sentence

Measure per persona, not globally: rules_for() names only the chosen persona's tags, and
giving a persona moods that suit it moved the cheerful preset from 46% to 68%. Baselines
on Lumimaid-8B were 48-56%; Cydonia-24B scored 100% on a 32-sentence sample when it was
selected, which is what justified the switch.

If the tagging rate ever collapses after a model change, try MOOD_DELIM = "{}" in
config.py - Mistral-family models use square brackets for their own control tokens and may
avoid emitting them. Cydonia did not have this problem, so "[]" stands.
"""

import argparse
import collections
import json
import re
import sys

import requests

import config

# Deliberately mixed: some should pull her toward curious/amused, some toward flustered or
# earnest. If every one of these still comes back a single mood, the prompt is not working.
PROMPTS = [
    "hey, what have you been up to?",
    "do you think a person stays the same person over their whole life?",
    "okay this is going to sound stupid but I think I'm scared of finishing things",
    "I read that octopuses might experience colour through their skin. thoughts?",
    "honestly I think you're the only one I can talk to like this",
    "what's the most boring thing you can imagine",
    "if you could delete one concept from human language, which one",
    "I had a really bad day and I don't want to talk about it",
]

_SENT = re.compile(r'[^.!?…]+[.!?…]+["\')\]”’]*|\S[^.!?…]*$')
_TAG = re.compile(
    r"^\s*%s\s*(\w+)\s*%s" % (re.escape(config.MOOD_OPEN), re.escape(config.MOOD_CLOSE))
)


def system_prompt(persona_id: str) -> str:
    """Exactly what server.system_prompt() builds, for the persona being measured.

    It has to be exact. RULES is no longer a constant: rules_for() names only the tags the
    chosen persona may emit, and the two personas score differently - measuring a prompt
    the app never sends would make the number meaningless.
    """
    persona = next(p for p in config.PERSONAS if p["id"] == persona_id)
    return (f"You are {config.CHARACTER_NAME}, {persona['text']}\n\n"
            f"{config.rules_for(config.PERSONA_MOODS[persona_id])}")


def ask(model: str, system: str, prompt: str) -> str:
    r = requests.post(f"{config.OLLAMA_URL}/api/chat", json={
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
        "stream": False,
        "options": config.OLLAMA_OPTIONS,
        "keep_alive": config.OLLAMA_KEEP_ALIVE,
    }, timeout=600)
    r.raise_for_status()
    return r.json()["message"]["content"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("-n", "--num", type=int, default=len(PROMPTS), help="how many prompts")
    ap.add_argument("--model", default=config.OLLAMA_MODEL)
    ap.add_argument("--show", action="store_true", help="print each sentence and its mood")
    ap.add_argument("--persona", default=config.PERSONAS[0]["id"],
                    choices=[p["id"] for p in config.PERSONAS],
                    help="which persona's mood set to measure (they score differently)")
    args = ap.parse_args()

    try:
        requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=5).raise_for_status()
    except Exception:
        sys.exit(f"Ollama is not answering on {config.OLLAMA_URL}. Start it first.")

    allowed = config.PERSONA_MOODS[args.persona]
    system = system_prompt(args.persona)

    print(f"model     : {args.model}")
    print(f"persona   : {args.persona}  ({', '.join(allowed)})")
    print(f"delimiter : {config.MOOD_OPEN}mood{config.MOOD_CLOSE}")
    print(f"prompts   : {args.num}\n")

    total = tagged = 0
    moods = collections.Counter()
    unknown = collections.Counter()

    for prompt in PROMPTS[:args.num]:
        try:
            reply = ask(args.model, system, prompt)
        except Exception as e:
            print(f"  ! {prompt[:40]}... failed: {e}")
            continue
        if args.show:
            print(f"> {prompt}")
        for raw in _SENT.findall(reply):
            raw = raw.strip()
            if not raw:
                continue
            total += 1
            m = _TAG.match(raw)
            if not m:
                if args.show:
                    print(f"    (untagged) {raw[:70]}")
                continue
            tagged += 1
            word = m.group(1).lower()
            canon = config.EMOTION_ALIASES.get(word)
            if canon is None:
                unknown[word] += 1
                canon = "?" + word
            moods[canon] += 1
            if args.show:
                print(f"    {canon:<10} {raw[m.end():].strip()[:64]}")
        if args.show:
            print()

    if not total:
        sys.exit("no sentences produced - nothing to measure.")

    pct = 100.0 * tagged / total
    print(f"sentences : {total}")
    print(f"tagged    : {tagged} ({pct:.1f}%)   untagged: {total - tagged}")
    on_set = [m for m in moods if m in allowed]
    # EMOTION_VOICE holds all nine moods, but a persona is only offered six of them, so
    # the denominator is the persona's set - otherwise every run looks like a failure.
    off_set = {m: n for m, n in moods.items() if not m.startswith("?") and m not in allowed}
    print(f"distinct  : {len(on_set)} of {len(allowed)} moods used\n")

    width = max(len(m) for m in moods) if moods else 8
    for mood, n in moods.most_common():
        bar = "#" * n
        print(f"  {mood:<{width}}  {n:>3}  {bar}")

    if unknown:
        print("\nunrecognised tags (add these to EMOTION_ALIASES):")
        for word, n in unknown.most_common():
            print(f"  {word}  x{n}")

    if off_set:
        # A tag that resolved to a mood this persona was never offered. Either the model
        # ignored the tag list, or EMOTION_ALIASES is folding a tag onto the wrong mood.
        # Check the table before blaming the model: it maps happy -> amused and
        # excited -> curious, which are wrong for the cheerful persona, whose own moods
        # those are.
        print("\nresolved OUTSIDE this persona's mood set:")
        for mood, n in sorted(off_set.items(), key=lambda kv: -kv[1]):
            print(f"  {mood}  x{n}")

    print()
    # Distinguish the failure modes, because they have completely different fixes and
    # the wrong advice sends you down a long dead end.
    if pct < 10:
        print(f"VERDICT: almost nothing tagged ({pct:.0f}%). The model is refusing the")
        print("         delimiter itself, not the instruction. Mistral-family models use")
        print(f"         square brackets for their own control tokens - switch")
        print("         MOOD_DELIM to \"{}\" in config.py and run this again.")
    elif pct < 80:
        print(f"VERDICT: {pct:.0f}% tagged - the model understands the format but applies it")
        print("         inconsistently, typically tagging the first sentence of a reply and")
        print("         letting later ones run untagged. That is a model-capability ceiling,")
        print("         not a delimiter problem: prompt wording gets you part of the way,")
        print("         a larger model gets you the rest. Untagged sentences still inherit")
        print("         the previous mood, so the result degrades gracefully rather than")
        print("         resetting to flat.")
    elif len(moods) <= 2:
        print("VERDICT: tags are landing, but the model is sitting on one or two moods.")
        print("         Strengthen the 'vary it' wording in RULES.")
    else:
        print(f"VERDICT: {pct:.0f}% tagged across {len(moods)} moods - good enough to tune voices.")


if __name__ == "__main__":
    main()
