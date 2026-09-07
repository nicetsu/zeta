"""
Voice-chat AI web server (streaming).

Per turn:
    browser mic audio -> faster-whisper (STT) -> Ollama/Lumimaid (LLM, streamed)
    -> split into sentences -> Style-Bert-VITS2 (TTS) per sentence -> stream audio
    back so the browser starts speaking the first sentence while the rest is still
    being generated.

Run:  python server.py
Open: https://localhost:8443 (PC)  or  https://<lan-ip>:8443 (iPad)
"""

import base64
import io
import json
import logging
import re
import time
from functools import lru_cache

import requests
import uvicorn
from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import JSONResponse, FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
log = logging.getLogger("voicechat")

app = FastAPI(title="Voice Chat AI")

history: list[dict] = []   # in-memory conversation, reset via /api/reset
active_persona = config.DEFAULT_PERSONA   # changed live from the ⚙️ Settings panel
# Which persona's mood set to use. Tracked separately from the text because the text is
# freely editable in the UI - once you hand-edit it we can no longer tell which character it
# is, so we keep whichever preset was last selected.
active_persona_id = config.PERSONAS[0]["id"]
_whisper = None


def active_moods() -> list:
    """The six moods the current persona is allowed to use."""
    return config.PERSONA_MOODS.get(active_persona_id,
                                    config.PERSONA_MOODS[config.PERSONAS[0]["id"]])


def system_prompt() -> str:
    return f"You are {config.CHARACTER_NAME}, {active_persona}\n\n{config.rules_for(active_moods())}"


# How many tokens the warm-up actually generates. On Modal the weights stream in from a
# network Volume, so this has to be enough real generation to pull the file through; on the
# PC the model is on a local disk and already resident, so a token or two is plenty.
PRELOAD_TOKENS = 64 if config.CLOUD else 4

_llm_warm = False   # reported by /api/health so a failed warm-up is visible, not silent
_tts_warm = False


def _preload_llm() -> None:
    """Page the LLM in before the first real turn, and report honestly whether it worked.

    This replaces two real bugs in the old three-line version:

    * It never checked the HTTP status, so a wrong model tag logged "LLM preloaded and kept
      warm." and only surfaced later as `llm failed: 404` on the first actual turn. Ollama
      also returns some failures as 200 with an {"error": ...} body, so both are checked.
    * It sent a two-token prompt with num_predict=1. That loads the model but does not *page
      it in*: on Modal the first real turn still ran prompt eval at ~32 tok/s while the
      weights streamed off the Volume, costing ~33 s to first audio. Generating a real reply
      against the real system prompt walks every layer enough times to pull the file through.

    The wait moves into container startup, where nobody is sitting in front of a microphone
    waiting for it. Timings are logged so the trade can be re-measured instead of assumed.
    """
    global _llm_warm
    t0 = time.monotonic()
    try:
        r = requests.post(
            f"{config.OLLAMA_URL}/api/chat",
            json={"model": config.OLLAMA_MODEL,
                  # The real system prompt, so prompt eval runs at a realistic length rather
                  # than on two tokens, and with the SAME options as real turns (esp. num_ctx
                  # and num_gpu) so this warm load isn't thrown away and reloaded.
                  "messages": [{"role": "system", "content": system_prompt()},
                               {"role": "user", "content": "Say one short sentence."}],
                  "stream": False,
                  "options": {**config.OLLAMA_OPTIONS, "num_predict": PRELOAD_TOKENS},
                  "keep_alive": config.OLLAMA_KEEP_ALIVE},
            timeout=600,
        )
        r.raise_for_status()
        d = r.json()
        if d.get("error"):
            raise RuntimeError(d["error"])

        def _rate(count, ns):
            return count / (ns / 1e9) if count and ns else 0.0

        log.info("LLM warm: %s in %.1fs (prompt %d tok @ %.0f tok/s, gen %d tok @ %.1f tok/s)",
                 config.OLLAMA_MODEL, time.monotonic() - t0,
                 d.get("prompt_eval_count") or 0,
                 _rate(d.get("prompt_eval_count"), d.get("prompt_eval_duration")),
                 d.get("eval_count") or 0,
                 _rate(d.get("eval_count"), d.get("eval_duration")))
        _llm_warm = True
    except Exception as e:
        # Loud on purpose. The old version's silence here is exactly what made a broken
        # model config look healthy at startup.
        log.error("LLM PRELOAD FAILED after %.1fs (%s) - the first turn will be slow or fail: %s",
                  time.monotonic() - t0, config.OLLAMA_MODEL, e)


def _warm_tts() -> None:
    """Synthesise one throwaway sentence so the first real one is not the slow one.

    Measured on 2026-09-05: with only the LLM warmed, the first turn after a cold start
    still took 16.1 s to first audio while the second took 1.5 s. The LLM was not the
    culprit - it had already generated 64 tokens during its own warm-up. The remaining
    cost was SBV2's first CUDA inference (kernel autotune and lazy device transfer),
    which nothing had exercised. One sentence here took the first turn 16.1 s -> 9.1 s.

    ONE sentence, not one per style. Warming all four style vectors was tried on the same
    day and measured 8.2 s - inside the run-to-run spread of the single-sentence version,
    for four times the startup cost. Rejected, same as the cpu=8.0 request in modal_app.py.

    Non-fatal by design: locally SBV2 may not be listening on :5000 yet when this runs,
    and that should be a warning rather than a dead web server. /api/health reports it.
    """
    global _tts_warm
    t0 = time.monotonic()
    try:
        wav = speak("Ready.", profile=voice_profile(config.DEFAULT_MOOD))
        log.info("TTS warm: %d bytes in %.1fs", len(wav), time.monotonic() - t0)
        _tts_warm = True
    except Exception as e:
        log.warning("TTS warm-up failed after %.1fs - the first sentence will be slow "
                    "and, if SBV2 is really down, silent: %s", time.monotonic() - t0, e)


@app.on_event("startup")
def _load_whisper():
    global _whisper
    from faster_whisper import WhisperModel
    log.info("Loading faster-whisper '%s' (%s/%s)...",
             config.WHISPER_MODEL, config.WHISPER_DEVICE, config.WHISPER_COMPUTE_TYPE)
    _whisper = WhisperModel(config.WHISPER_MODEL, device=config.WHISPER_DEVICE,
                            compute_type=config.WHISPER_COMPUTE_TYPE)
    log.info("Whisper ready.")

    _preload_llm()
    _warm_tts()


# ---------------------------------------------------------------- helpers

def transcribe(audio_bytes: bytes) -> str:
    segments, _ = _whisper.transcribe(io.BytesIO(audio_bytes),
                                      language=config.WHISPER_LANGUAGE, vad_filter=True)
    return "".join(s.text for s in segments).strip()


def clean_for_speech(text: str) -> str:
    """Strip roleplay stage directions so the TTS only speaks real words."""
    # Reasoning blocks first, CONTENT INCLUDED. Cydonia-24B's card says "<thinking>
    # </thinking> works", so it may emit them unprompted - and without this the model
    # would literally read its own private reasoning out loud in Zeta's voice.
    cleaned = re.sub(r"<thinking>.*?</thinking>", " ", text, flags=re.S | re.I)
    cleaned = re.sub(r"</?\w[^>]*>", " ", cleaned)  # any other stray <tag>
    cleaned = re.sub(r"\*[^*]*\*", " ", cleaned)   # *waves*
    cleaned = re.sub(r"\([^)]*\)", " ", cleaned)   # (softly)
    cleaned = re.sub(r"\[[^\]]*\]", " ", cleaned)  # [A/N: ...] and any mood tag
    cleaned = re.sub(r"\{[^}]*\}", " ", cleaned)   # {mood} when MOOD_DELIM is "{}"
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def build_messages(user_text: str) -> list[dict]:
    msgs = [{"role": "system", "content": system_prompt()}]
    msgs += history[-config.HISTORY_TURNS * 2:]
    msgs.append({"role": "user", "content": user_text})
    return msgs


def ollama_chat_stream(messages):
    """Yield text deltas from Ollama as they are generated."""
    with requests.post(
        f"{config.OLLAMA_URL}/api/chat",
        json={"model": config.OLLAMA_MODEL, "messages": messages, "stream": True,
              "options": config.OLLAMA_OPTIONS, "keep_alive": config.OLLAMA_KEEP_ALIVE},
        stream=True, timeout=300,
    ) as r:
        r.raise_for_status()
        for line in r.iter_lines(decode_unicode=True):
            if not line:
                continue
            d = json.loads(line)
            piece = d.get("message", {}).get("content")
            if piece:
                yield piece
            if d.get("done"):
                break


_SENT = re.compile(r'^(.*?[.!?…]+["\')\]”’]*)(\s)(.*)$', re.S)

def sentences_from(token_iter):
    """Group streamed tokens into whole sentences (flush on sentence end or if long)."""
    buf = ""
    for tok in token_iter:
        buf += tok
        while True:
            m = _SENT.match(buf)
            if not m:
                break
            sent, buf = m.group(1).strip(), m.group(3)
            if sent:
                yield sent
        if len(buf) > 180:            # avoid waiting forever on run-on text
            yield buf.strip()
            buf = ""
    if buf.strip():
        yield buf.strip()


def voice_profile(mood: str) -> dict:
    """Full SBV2 parameter set for a mood, falling back to the SBV2_* defaults per key."""
    p = config.EMOTION_VOICE.get(mood, {})
    return {
        "style":        p.get("style", config.SBV2_STYLE),
        "style_weight": p.get("style_weight", config.SBV2_STYLE_WEIGHT),
        "sdp_ratio":    p.get("sdp_ratio", config.SBV2_SDP_RATIO),
        "noise":        p.get("noise", config.SBV2_NOISE),
        "noisew":       p.get("noisew", config.SBV2_NOISEW),
        "length":       p.get("length", config.SBV2_LENGTH),
    }


def speak(text: str, profile: dict = None) -> bytes:
    """One sentence -> WAV bytes via Style-Bert-VITS2, voiced with that sentence's mood."""
    prof = profile or voice_profile(config.DEFAULT_MOOD)
    r = requests.get(f"{config.SBV2_URL}/voice", params={
        "text": text, "model_id": config.SBV2_MODEL_ID, "speaker_id": config.SBV2_SPEAKER_ID,
        "language": config.SBV2_LANGUAGE, **prof,
    }, timeout=120)
    r.raise_for_status()
    return r.content


def _nd(obj) -> str:
    return json.dumps(obj, ensure_ascii=False) + "\n"


# ---------------------------------------------------------------- routes

# A mood tag at the start of a sentence, in whichever delimiter config picked.
_TAG = re.compile(
    r"^\s*%s\s*(\w+)\s*%s\s*" % (re.escape(config.MOOD_OPEN), re.escape(config.MOOD_CLOSE))
)

# Fallback for when the model writes the mood but forgets the delimiters - measured on
# Lumimaid, which produced bare "pondering"/"curious" openers. Restricted to canonical mood
# names (not the whole alias table) because those are unlikely sentence openers in ordinary
# speech, so the risk of eating a real word is small.
#
# Built from the ACTIVE persona's six moods, not all nine in EMOTION_VOICE. The difference is
# real: while the INTP persona is selected she can never emit [happy] or [excited], yet the
# nine-mood pattern still ate the first word of "Happy birthday" and "Excited to hear it".
# It cannot help where the word genuinely is one of her own moods - a bare "Curious." is
# ambiguous to a human too - it just stops the other persona's vocabulary doing damage.
@lru_cache(maxsize=8)   # one compiled pattern per persona, not one per sentence
def _bare_re(moods: tuple) -> re.Pattern:
    return re.compile(
        r"^\s*(%s)\b[\s,:.-]*" % "|".join(sorted(moods)), re.I
    )


def take_mood(sentence: str, previous: str) -> tuple[str, str]:
    """Pull a leading mood tag off one sentence.

    Returns (mood, sentence-without-the-tag). An untagged sentence KEEPS the previous
    mood rather than resetting to the default - models drop the tag now and then, and a
    single miss shouldn't flatten the rest of a reply.
    """
    m = _TAG.match(sentence)
    if m:
        return config.EMOTION_ALIASES.get(m.group(1).lower(), previous), sentence[m.end():]
    m = _bare_re(tuple(active_moods())).match(sentence)
    if m:
        return config.EMOTION_ALIASES.get(m.group(1).lower(), previous), sentence[m.end():]
    return previous, sentence


def reply_events(user_text: str):
    """Shared generator: LLM (streamed) -> per-sentence mood -> TTS -> NDJSON events.

    The mood is re-read for EVERY sentence, so tone can shift mid-reply and the avatar's
    face can follow along. Each 'text' event carries its own mood so the client can hold
    the expression back until that sentence's audio actually plays.
    """
    parts = []
    mood = config.DEFAULT_MOOD
    tts_failed = False   # report a dead TTS once per turn, not once per sentence
    try:
        for raw in sentences_from(ollama_chat_stream(build_messages(user_text))):
            mood, body = take_mood(raw, mood)
            sent = clean_for_speech(body)
            if not sent:
                continue
            parts.append(sent)
            yield _nd({"type": "text", "text": sent, "mood": mood})
            try:
                wav = speak(sent, profile=voice_profile(mood))
                yield _nd({"type": "audio", "b64": base64.b64encode(wav).decode("ascii")})
            except Exception as e:
                # Used to be log-only, which is why "text appears but there is no voice and
                # the mouth doesn't move" was a silent failure you had to read the container
                # logs to diagnose. Tell the browser, once, and keep streaming the text.
                log.warning("tts failed: %s", e)
                if not tts_failed:
                    tts_failed = True
                    yield _nd({"type": "error",
                               "text": "no voice - the TTS server is not answering"})
    except Exception as e:
        log.exception("llm failed")
        yield _nd({"type": "error", "text": f"llm failed: {e}"})
    reply = " ".join(parts).strip()
    if reply:
        log.info("AI  : %s", reply)
        history.append({"role": "user", "content": user_text})
        history.append({"role": "assistant", "content": reply})
    yield _nd({"type": "done"})


@app.post("/api/talk")
def talk(audio: UploadFile = File(...)):
    """Voice mode: audio -> STT -> reply."""
    audio_bytes = audio.file.read()

    def gen():
        try:
            user_text = transcribe(audio_bytes)
        except Exception as e:
            log.exception("stt failed")
            yield _nd({"type": "error", "text": f"stt failed: {e}"}); yield _nd({"type": "done"}); return
        log.info("USER: %s", user_text)
        yield _nd({"type": "user", "text": user_text})
        if not user_text:
            yield _nd({"type": "error", "text": "didn't catch that"}); yield _nd({"type": "done"}); return
        yield from reply_events(user_text)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/say")
async def say(request: Request):
    """Text mode: typed text -> reply (skips STT). Client shows the user's text itself."""
    data = await request.json()
    text = (data.get("text") or "").strip()

    def gen():
        if not text:
            yield _nd({"type": "done"}); return
        log.info("USER (text): %s", text)
        yield from reply_events(text)

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/api/reset")
def reset():
    history.clear()
    return {"ok": True}


@app.get("/api/personas")
def get_personas():
    return {"name": config.CHARACTER_NAME, "presets": config.PERSONAS,
            "current": active_persona, "current_id": active_persona_id,
            "moods": active_moods()}


@app.post("/api/persona")
async def set_persona(request: Request):
    global active_persona, active_persona_id
    data = await request.json()
    text = (data.get("text") or "").strip()
    active_persona = text or config.DEFAULT_PERSONA
    # The client sends the preset id when one was clicked. Editing the text by hand sends no
    # id, and we keep the previous one rather than guessing a mood set from free-form prose.
    pid = data.get("id")
    if pid in config.PERSONA_MOODS:
        active_persona_id = pid
    log.info("Persona set to [%s]: %s", active_persona_id, active_persona[:70])
    return {"ok": True, "current": active_persona,
            "current_id": active_persona_id, "moods": active_moods()}


@app.get("/api/health")
def health():
    """Checked by the browser on page load.

    A dead dependency should warn up front rather than surface as a mute reply halfway
    through a conversation. `cloud` also tells the client whether to offer the sleep
    button, which only means anything on Modal.
    """
    out = {"ollama": False, "sbv2": False, "cloud": config.CLOUD,
           "llm_warm": _llm_warm, "tts_warm": _tts_warm}
    try:
        requests.get(f"{config.OLLAMA_URL}/api/tags", timeout=5).raise_for_status(); out["ollama"] = True
    except Exception:
        pass
    try:
        requests.get(f"{config.SBV2_URL}/docs", timeout=5).raise_for_status(); out["sbv2"] = True
    except Exception:
        pass
    return out


@app.get("/")
def index():
    return FileResponse("static/index.html")


app.mount("/static", StaticFiles(directory="static"), name="static")


if __name__ == "__main__":
    kwargs = {"host": config.HOST, "port": config.PORT}
    if config.USE_SSL:
        kwargs["ssl_certfile"] = config.SSL_CERTFILE
        kwargs["ssl_keyfile"] = config.SSL_KEYFILE
        log.info("Serving HTTPS on https://%s:%s", config.HOST, config.PORT)
    else:
        log.info("Serving HTTP on http://localhost:%s", config.PORT)
    uvicorn.run(app, **kwargs)
