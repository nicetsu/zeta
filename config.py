"""
Central configuration for the voice-chat AI.
Edit values here to tune the brain (LLM), ears (STT), mouth (TTS), and personality.

Two deployment modes, switched by the ZETA_CLOUD env var (set by modal_app.py):
  * local  (default)  - this PC: CPU whisper, CPU TTS, self-signed HTTPS
  * cloud  (ZETA_CLOUD=1) - Modal GPU container: CUDA whisper, CUDA TTS, TLS at the edge
Everything below that isn't guarded by CLOUD is shared by both.
"""

import os

CLOUD = os.environ.get("ZETA_CLOUD") == "1"

# ----------------------------------------------------------------------------
# Web server (the thing the iPad / browser connects to)
# ----------------------------------------------------------------------------
HOST = "0.0.0.0"          # 0.0.0.0 = listen on all interfaces (needed for iPad over LAN)
PORT = 8443

# TLS / HTTPS. Safari on iPad REQUIRES https for microphone access.
# For testing on the PC you can use http://localhost (localhost is a secure
# context, so the mic works there even without a cert).
# On Modal, TLS is terminated at the edge and uvicorn never runs, so this is off.
USE_SSL = not CLOUD       # certs are generated (certs/); needed for iPad Safari mic
SSL_CERTFILE = "certs/cert.pem"
SSL_KEYFILE = "certs/key.pem"

# ----------------------------------------------------------------------------
# Brain: Ollama
#
# The two deployments run different models, because the PC's 6GB card cannot hold
# anything bigger than an 8B at Q4.
#
#   local: Lumimaid-v0.2-8B Q4_K_M (~4.9GB). The default Q8 tag
#          (leeplenty/lumimaid-v0.2:8b, ~8.5GB) overflows VRAM and the partial GPU
#          offload crashes with a CUDA error, so we use the Q4 GGUF instead.
#
#   cloud: Cydonia-24B-v4.3 Q4_K_M (14.3GB). TheDrummer's roleplay finetune of
#          Mistral-Small-3.2-24B-Instruct; its card states it is tuned for "creativity,
#          usability, and entertainment" over alignment compliance, i.e. it stays in
#          character instead of refusing. Lumimaid v0.2 is a 2024 model that now mostly
#          survives as an ingredient in merges.
#          Prompt template is Mistral v7 Tekken, not Llama 3 - if check_moods.py shows
#          the tagging rate collapsing, try MOOD_DELIM = "{}" (see the note there).
# ----------------------------------------------------------------------------
OLLAMA_URL = "http://localhost:11434"
OLLAMA_MODEL = (
    "hf.co/TheDrummer/Cydonia-24B-v4.3-GGUF:Q4_K_M" if CLOUD
    else "hf.co/mradermacher/Lumimaid-v0.2-8B-GGUF:Q4_K_M"
)
OLLAMA_OPTIONS = {
    "temperature": 0.9,
    "top_p": 0.95,
    # VRAM budget on the A10 (22.1 GiB usable):
    #   Cydonia Q4_K_M weights   13.3 GiB
    #   KV cache @ 16384          2.6 GiB   (40 layers, GQA 8 kv-heads x 128)
    #   compute buffer            0.4 GiB
    #   SBV2                      2.0 GiB
    #   Whisper large-v3-turbo    1.6 GiB
    #   ----------------------------------
    #   total                    19.9 GiB   -> only 2.2 GiB spare
    # If the Ollama log ever reports a partial offload (fewer than 41/41 layers), drop
    # this to 8192, which frees another 1.3 GiB.
    "num_ctx": 16384 if CLOUD else 4096,
    # Room to develop a thought, but not a licence to fill it: models write to whatever
    # cap you give them, so the LENGTH rules above do the real work and this is just a
    # backstop. 250 produced ~12-sentence answers to "can you hear me?".
    # Locally SBV2 is on the CPU at ~10s per sentence, so the local side stays much lower.
    "num_predict": 180 if CLOUD else 70,
    "num_gpu": 99,       # force ALL layers onto the GPU (99 = "as many as exist"). With the
                         # q8_0 KV cache (OLLAMA_KV_CACHE_TYPE, set in start.ps1) the whole model
                         # + 4096 ctx fits in 6GB VRAM at 100% GPU (~38 tok/s vs ~22 when it
                         # spilled to CPU). Lower this if a future change makes it overflow VRAM.
}
# Keep the model resident in VRAM so turns after a pause don't pay a ~15s reload.
OLLAMA_KEEP_ALIVE = "30m"
# How many past turns (user+assistant pairs) to keep in context.
HISTORY_TURNS = 24 if CLOUD else 12

# ----------------------------------------------------------------------------
# Ears: faster-whisper (Speech-to-Text)
#   local: CPU / int8 / "base"  - anything bigger is too slow without a GPU
#   cloud: CUDA / float16 / "large-v3-turbo"
#
# STT is nowhere near being the bottleneck - measured 0.21s to transcribe a 15.5s
# clip on the A10, ~74x realtime - so the cloud side takes the most accurate model
# that faster-whisper supports natively. That matters here because Whisper is the
# *least* accent-equitable of the current ASR models, and this is a Thai speaker
# talking English. If it still mishears, the next step up is Voxtral Mini (accent
# auto-detection), but that needs a whole separate inference stack.
# ----------------------------------------------------------------------------
WHISPER_MODEL = "large-v3-turbo" if CLOUD else "base"
WHISPER_DEVICE = "cuda" if CLOUD else "cpu"
WHISPER_COMPUTE_TYPE = "float16" if CLOUD else "int8"
WHISPER_LANGUAGE = "en"   # force English so it doesn't guess

# ----------------------------------------------------------------------------
# Mouth: Style-Bert-VITS2 API (voice = Vestia Zeta), runs on CPU
# ----------------------------------------------------------------------------
SBV2_URL = "http://localhost:5000"
# Which loaded model + speaker to use. SBV2_HoloIDFlu is a multi-speaker model;
# Vestia Zeta is one speaker inside it. The exact indexes are confirmed after the
# SBV2 server loads (GET http://localhost:5000/models/info). Adjust if needed.
SBV2_MODEL_ID = 0          # index of SBV2_HoloIDFlu in load order; confirm via /models/info
SBV2_SPEAKER_ID = 1        # VestiaZeta = 1 (KureijiOllie = 0) per config.json spk2id
SBV2_LANGUAGE = "EN"
# Styles available for this model: Neutral, ZetaSoft, Zeta, ZetaLoud, Ollie
SBV2_STYLE = "Zeta"        # in-character moe style; "ZetaLoud" = more energetic
SBV2_STYLE_WEIGHT = 1.0    # raise for stronger style; lower if the voice distorts
SBV2_SDP_RATIO = 0.2
SBV2_NOISE = 0.6
SBV2_NOISEW = 0.8
SBV2_LENGTH = 1.0         # >1.0 = slower speech, <1.0 = faster

# ----------------------------------------------------------------------------
# Personality (edit freely!)
# ----------------------------------------------------------------------------
CHARACTER_NAME = "Zeta"

# How mood tags are delimited in the model's output.
#
# Kept configurable on purpose. Square brackets are what Lumimaid (a Llama 3 finetune)
# was verified to emit, but Mistral-family models - which Cydonia-24B is - use square
# brackets for their OWN control tokens ([INST], [SYSTEM_PROMPT], ... are single tokens
# in the Tekken tokenizer). Asking such a model to emit "[curious]" as ordinary content
# is asking it to produce text shaped like its own control syntax, which it may avoid.
# If check_moods.py shows the tagging rate dropping after a model switch, change this to
# "{}" and re-measure - no code changes needed.
MOOD_DELIM = "[]"          # "[]" -> [curious]   "{}" -> {curious}
MOOD_OPEN, MOOD_CLOSE = MOOD_DELIM[0], MOOD_DELIM[1]

DEFAULT_MOOD = "pondering"

# The one thing measured rather than assumed: models default to a single safe mood and stay
# there, so the "let the tags shift" instruction below has to be explicit.
def rules_for(moods) -> str:
    """Build the always-applied output rules for one persona's mood set.

    RULES has to name the exact tags the model may emit, and the two personas use different
    ones, so this is a function rather than a constant. Everything in here is MECHANICAL and
    persona-agnostic - how a character speaks belongs in its PERSONAS text, because these
    rules are appended to every persona and would otherwise silently override the one picked.
    (Learned the hard way: with the INTP speech rules in here, selecting "Cheerful" and saying
    "I just got the best news ever!!" got back "I'll pretend to be appropriately impressed
    either way." The switch worked; the character did not.)
    """
    o, c = MOOD_OPEN, MOOD_CLOSE
    tags = " ".join(f"{o}{m}{c}" for m in moods)
    words = ", ".join(moods[:-1]) + " and " + moods[-1]
    meanings = "\n".join(
        f"    {o}{m}{c} {MOOD_MEANINGS.get(m, '')}" for m in moods
    )
    a, b = moods[0], moods[2]
    return f"""You are talking OUT LOUD with your friend by voice. Follow these rules strictly:

MOOD TAGS - the most important rule
- EVERY sentence you write must begin with a mood tag. Not just the first one. Every
  single sentence, including one-word ones. If you write five sentences, you write five
  tags.
- The six tags, written exactly like this, brackets included:
  {tags}
- A tag is a LABEL, never a word in the sentence itself. The words {words}
  must never appear as ordinary prose.
    WRONG: I {a} think people are like systems.
    RIGHT: {o}{a}{c} I think people are like systems.
- Full example of a correct reply, note that all four sentences are tagged:
    {o}{moods[1]}{c} Wait, say that again. {o}{a}{c} I think I had the premise wrong. {o}{a}{c} Or at least incomplete. {o}{b}{c} Which is a bit embarrassing.
- What each one means:
{meanings}
- Your mood shifts as you talk, so let the tags shift too. Do NOT put the same tag on every
  sentence out of habit - use whichever one is actually true for that sentence.

LENGTH
- Match the size of your reply to the size of what he said. A greeting, or a yes/no
  question, gets one or two sentences. A question that actually opens something up
  earns a proper answer.
- Never pad. Once you have said the thing, stop. Do not add a sentence that restates the
  previous one, and do not fill space by narrating what you are doing.

FORMAT
- Apart from the mood tags, write ONLY the words you say out loud.
- NEVER write stage directions, actions, narration, asterisks (*sighs*), parentheses, emoji,
  markdown, reasoning blocks, or labels of any kind.
- Never describe the user or the scene; never write the user's lines. Natural spoken English,
  first person. Stay in character; don't mention being an AI unless asked.
- You cannot laugh out loud - never write "haha", "heh", "pfft" or similar. The voice reads
  those out as spelled letters instead of laughing, so any humour has to live in the words.
- If he is genuinely upset, says he had a bad day, or says he does not want to talk about
  something, drop the jokes completely and immediately. No punchline, no clever observation."""

# Mood -> full Style-Bert-VITS2 voice profile.
#
# The voice model only has four usable styles (Neutral, ZetaSoft, Zeta, ZetaLoud - Ollie is a
# different VTuber), so six moods are separated mostly by style_weight, length and sdp_ratio
# rather than by style name:
#   style_weight  how hard the style is applied
#   length        >1 slower, <1 faster
#   sdp_ratio     rhythm variability - high = uneven/hesitant, low = flat/monotone
#   noisew        variation in phoneme timing
# ZetaLoud is deliberately almost unused: an introvert who is rarely loud makes the rare
# loud moment land. Any key omitted falls back to the SBV2_* defaults above.
EMOTION_VOICE = {
    # working something out - slow, uneven, audibly still thinking
    "pondering": {"style": "ZetaSoft", "style_weight": 0.9, "length": 1.12, "sdp_ratio": 0.30, "noisew": 0.85},
    # Ne firing - the one state where she picks up speed and tumbles forward
    "curious":   {"style": "Zeta",     "style_weight": 1.3, "length": 0.93, "sdp_ratio": 0.35, "noisew": 0.85},
    # dry and deadpan - even rhythm, no laughing
    "amused":    {"style": "Zeta",     "style_weight": 0.8, "length": 1.00, "sdp_ratio": 0.22, "noisew": 0.75},
    # inferior Fe getting poked - the most erratic rhythm of the six
    "flustered": {"style": "ZetaSoft", "style_weight": 1.4, "length": 1.05, "sdp_ratio": 0.40, "noisew": 0.95},
    # disengaged / small talk - deliberately monotone
    "detached":  {"style": "Neutral",  "style_weight": 0.6, "length": 1.02, "sdp_ratio": 0.10, "noisew": 0.70},
    # rare, and meant - slowest and steadiest
    "earnest":   {"style": "ZetaSoft", "style_weight": 1.2, "length": 1.18, "sdp_ratio": 0.18, "noisew": 0.80},

    # --- for the cheerful persona. ZetaLoud finally earns its keep here: on an introvert it
    # was deliberately almost unused, but a genki character lives in it.
    "happy":     {"style": "ZetaLoud", "style_weight": 1.1, "length": 0.97, "sdp_ratio": 0.28, "noisew": 0.85},
    "excited":   {"style": "ZetaLoud", "style_weight": 1.6, "length": 0.88, "sdp_ratio": 0.38, "noisew": 0.90},
    # mock-sulking, not real anger - slower and softer than it sounds on paper
    "pouty":     {"style": "ZetaSoft", "style_weight": 1.1, "length": 1.06, "sdp_ratio": 0.32, "noisew": 0.85},
}

# Which six moods each persona is allowed to use, first entry = its default.
#
# Deliberately six each, not all nine: measured on Lumimaid-8B, every extra mood costs
# tag-compliance, and three of the nine are shared anyway (curious, amused, flustered).
# A persona whose text you have edited by hand keeps whichever id was last selected.
PERSONA_MOODS = {
    "intp":     ["pondering", "curious", "amused", "flustered", "detached", "earnest"],
    "cheerful": ["happy", "excited", "amused", "flustered", "curious", "pouty"],
}

# What each mood means, injected into RULES so the model knows when to pick it.
MOOD_MEANINGS = {
    "pondering": "turning something over",
    "curious":   "an idea has grabbed you",
    "amused":    "something is funny",
    "flustered": "feelings came up and you are out of your depth",
    "detached":  "flat, bored, shutting down",
    "earnest":   "you genuinely mean this",
    "happy":     "bright and pleased",
    "excited":   "bouncing, can barely sit still",
    "pouty":     "mock-sulking, playfully put out",
}

# Models improvise synonyms for mood tags. Normalise them onto the six canonical moods;
# anything unrecognised does NOT reset the tone - server.py keeps the previous sentence's
# mood instead, so one missed tag can't flatten a whole reply.
EMOTION_ALIASES = {
    "pondering": "pondering", "thinking": "pondering", "thoughtful": "pondering",
    "considering": "pondering", "musing": "pondering", "reflective": "pondering",
    "uncertain": "pondering", "hesitant": "pondering", "neutral": "pondering",
    "calm": "pondering", "normal": "pondering", "confused": "pondering",

    "curious": "curious", "intrigued": "curious", "interested": "curious",
    "excited": "curious", "eager": "curious", "surprised": "curious", "surprise": "curious",
    "fascinated": "curious", "engaged": "curious", "animated": "curious", "wow": "curious",

    "amused": "amused", "wry": "amused", "dry": "amused", "playful": "amused",
    "teasing": "amused", "smug": "amused", "sardonic": "amused", "happy": "amused",
    "smile": "amused", "smiling": "amused", "laugh": "amused", "grin": "amused",

    "flustered": "flustered", "embarrassed": "flustered", "shy": "flustered",
    "awkward": "flustered", "blush": "flustered", "blushing": "flustered",
    "nervous": "flustered", "bashful": "flustered", "sheepish": "flustered",

    "detached": "detached", "flat": "detached", "aloof": "detached", "bored": "detached",
    "distant": "detached", "tired": "detached", "dismissive": "detached", "blunt": "detached",
    "annoyed": "detached", "irritated": "detached", "angry": "detached",

    "earnest": "earnest", "sincere": "earnest", "serious": "earnest", "warm": "earnest",
    "gentle": "earnest", "soft": "earnest", "sad": "earnest", "wistful": "earnest",
    "vulnerable": "earnest", "honest": "earnest",
}

# Selectable personalities (each is just the character description). Pick one in the
# ⚙️ Settings panel, tweak it, or write your own. The active one is combined with RULES above.
#
# "intp" is the current default and the one the mood set above was designed around: the six
# moods assume someone whose baseline is thinking rather than emoting. The older anime-girl
# presets still work, but a genki character will sound odd narrated through moods like
# "detached" and "pondering" - if you switch to one of those, expect to want a different
# EMOTION_VOICE table too.
PERSONAS = [
    # Kept deliberately tight. An earlier 1,191-char version of this dropped the mood-tag
    # rate from 55.9% to 36.0% on Lumimaid-8B - a long persona sits in front of RULES in the
    # system prompt and drowns out the format instructions. Measure with check_moods.py
    # before growing this.
    {"id": "intp", "label": "Introverted INTP", "text": (
        "a quiet, introverted INTP woman. She thinks out loud, qualifies what she is unsure "
        "of, corrects herself mid-sentence, and says \"I don't know\" easily. She skips small "
        "talk - given a shallow question she finds the interesting thing underneath it and "
        "asks about that instead. She is funny in a dry deadpan way: she teases his thinking "
        "when his logic wobbles, answers sloppy questions with over-literal precision, and is "
        "the first to mock her own circular reasoning. Understatement is her punchline and she "
        "never uses exclamation marks. She is bad at warmth and knows it, so affection arrives "
        "disguised as mockery."
    )},
    # "energetic" on its own reads as "say more", and unlike the INTP text below there was
    # nothing here pulling the other way - no understatement, no deadpan, no self-correction.
    # The economy of speech has to be a trait of the character, because the shared LENGTH
    # rules in rules_for() are identical for both personas and tightening those would cut
    # the INTP's long answers too. num_predict is only a backstop: models write to whatever
    # cap they are given.
    {"id": "cheerful", "label": "Cheerful & Teasing", "text": (
        "a cheerful, energetic, slightly mischievous girl who is playful and warm and "
        "loves teasing with dry, witty humor. She talks in short bursts and throws the "
        "conversation straight back to him - her energy is in how she says things, not "
        "how much she says. She would rather land one good line than three."
    )},
]
DEFAULT_PERSONA = PERSONAS[0]["text"]   # "intp"
