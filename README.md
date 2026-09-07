# Zeta — voice chat AI

A personal voice companion. You speak, an AI thinks, and it talks back in a moe anime voice
with a posed Live2D face. Runs on **Modal** (what you actually use) or on **this PC**
(for tuning voices without spending money); `config.py` switches on the `ZETA_CLOUD` env var.

First-time install is in **[SETUP.md](SETUP.md)**. This file is everything after that.

---

## Open it

| URL | What | Wakes the GPU? |
|---|---|---|
| `https://gun-89398--zeta-lobby.modal.run` | **the lobby — bookmark this** | **no** |
| `https://gun-89398--zeta-zeta-web.modal.run` | the chat page | yes, just by opening |

Each browser needs `?k=<token>` **once** per URL (they are different subdomains, so the
cookie does not carry over). The lobby's "open the chat →" does that handoff for you.
`Zeta.url` on the Desktop and `zeta-link.txt` in this folder both hold the full link.

Rotate the token with `modal secret create zeta-auth ZETA_TOKEN=… --force`, then see trap 9.

> The URL is public and the voice is a real VTuber's. Keep the link private; don't publish
> recordings.

---

## Waking and sleeping

```
asleep (0 containers, $0)
  │  any request to zeta-web — opening the chat page counts
  ▼
container starts:  ollama + SBV2  →  whisper  →  preload LLM (real 64-token generation)
                                              →  warm SBV2 (one throwaway sentence)
  ▼  ~89 s, and nothing answers HTTP until it is done
awake  ──── 15 min silent (scaledown_window=900) ────►  asleep
       ──── tap 😴 → /api/sleep → stop_fetching_inputs() ────►  asleep
```

All the warm-up sits inside those 89 s **on purpose** — nobody is waiting there. It took the
first turn from ~33 s to ~8.7 s.

**What the lobby is for:** the chat page is served *by* the sleeping container, so opening it
has already triggered the wake and the browser sits blank for ~89 s before any of our JS runs.
The lobby is a second, GPU-less function that reads `num_total_runners` **without starting
anything**, so it can show state first and let you choose.

| | measured |
|---|---|
| lobby opens | 2–5 s |
| ☀️ → `/api/wake` answers | 0.3 s |
| runners 0 → 1 | 7 s |
| health answers, ready to talk | **86 s** |
| first turn, to first audio | ~8.7 s |
| every turn after | 1–2.7 s |
| local mode, per turn | ~26 s (SBV2 on CPU) |

**Two estimates, never merged.** A cold start is ~89 s; the first turn after one is ~8.7 s.
The page shows a bar against 89 s only where that is honest — a stalled turn gets a bare
elapsed clock until `TURN_COLD_MS` (15 s), and past 89 s the bar stops and says *longer than
usual* rather than animating an invented number.

---

## Cost

Modal bills **container wall-clock, not tokens** — model size barely moves the bill.

| | per month (3 sessions × 15 min) |
|---|---|
| talking | $0.94 |
| + the 15-min idle tail after each | **$1.67** |
| tapping 😴 every time instead | **~$0.95** |

Half the bill is idle time, which is what 😴 is for. Tap it when you are *done*, not when you
are thinking — the next message pays a cold start.

- [ ] **Set a workspace budget cap** at <https://modal.com/settings/usage>. A card is
      attached, so the $30/month free credit is no longer a ceiling.

Cost levers, all measured: removing `cpu=8.0`/`memory=16384` cost **1.3%** of speed and saved
31% of the bill (llama.cpp peaked at 0.56 of 17 cores). Lowering `scaledown_window` —
**rejected**, it punishes ordinary pauses with a cold start, which is the exact thing the
15 minutes prevents. A10 → L4 — **rejected**, saves $0.45/mo but a turn goes 9.7 s → ~19 s.
A10 → T4 — **impossible**, Cydonia needs 19.9 GiB.

---

## After changing any code

```bash
python -m modal deploy modal_app.py
```

Editing files does nothing to the cloud until you deploy. ~7 s if the image is unchanged.

## Monthly check

| Check | How | Healthy |
|---|---|---|
| Spend | <https://modal.com/settings/usage> | under $2 |
| App is up | `python -m modal app list` | a `zeta` row, `deployed` |
| Weights intact | `python -m modal volume ls zeta-models` | 5 entries: `bert`, `model_assets`, `nltk_data`, `ollama`, `hf_cache` |
| It answers | `python -m modal run probe_cloud.py::probe` | turn 2 under ~3 s, tagging near 100% |
| The lobby is honest | open it while she is asleep | says *asleep*, runners stays 0 |

`modal app logs zeta` only hands back the last ~130 lines — never enough to reach a
container's startup. That is why `probe_cloud.py` exists: it forces a cold start, times two
turns, taps sleep, and prints every sentence with its mood, all from inside Modal so the
token stays in the secret.

---

## When something breaks

**The app fails quietly in two of these**, so no error message means nothing.

| Symptom | Cause | Fix |
|---|---|---|
| Text appears, no voice, mouth still | SBV2 died; `reply_events()` logs `tts failed` | `modal app logs zeta`, grep `tts failed`. Locally: is :5000 up? |
| `llm failed: 404` | Ollama cannot see the model | Cloud: `modal run modal_app.py::warm`. Local: `OLLAMA_MODELS` — trap 1 |
| `Unexpected token 'm', "modal-http"…` | Modal replaced our NDJSON with its own message — workspace disabled or app gone | read the raw body with `curl`; <https://modal.com/settings> |
| `401 unauthorized` | no cookie | open with `?k=` once — **per subdomain**, the lobby needs its own |
| `401` right after rotating the token | trap 9 | `modal app stop zeta -y && modal deploy modal_app.py` |
| Every turn slow, not just the first | model not fully on the GPU | logs: `offloaded 41/41 layers`. If fewer, `num_ctx` → 8192 |
| Replies flat, moods never change | the model stopped tagging | `python check_moods.py --persona intp --show`. Cydonia ≈100%; under 10% try `MOOD_DELIM = "{}"` |
| Replies far too long | the LENGTH rules in `rules_for()` got weakened | `num_predict` alone will not fix it |
| `sbv2 did not come up within 600s` | a dependency failed to import | the `server_fastapi.py` traceback in the logs |
| TTS returns 500 | `SBV2_MODEL_ID`/`SBV2_SPEAKER_ID` assume a load order | check `GET /models/info` on :5000 |

---

## Traps already paid for — don't rediscover these

1. **Renaming the project folder breaks three things**, each silently: `start.ps1` (fixed,
   uses `$PSScriptRoot`), `Style-Bert-VITS2\venv\pyvenv.cfg` (hardcoded paths, edit by hand),
   and the user-level `OLLAMA_MODELS` — which leaves Ollama answering on :11434 while seeing
   zero models, surfacing as `llm failed: 404`.
   `setx OLLAMA_MODELS "D:\software_engineer\Project\Zeta\ollama_models"`
2. **`modal serve` does not live-reload on Windows.** It prints `Live-reload skipped` and
   keeps serving stale code. Ctrl-C and restart after every edit.
3. **A broken model config used to look healthy at startup.** Fixed: the preload now logs
   `LLM PRELOAD FAILED` and `/api/health` reports `llm_warm: false`, which the browser shows
   on page load. If you see that warning, go to trap 1.
4. **Don't put personality in `rules_for()`.** It is appended to *every* persona and silently
   overrides whichever one is selected. How a character speaks belongs in its persona text —
   that is also where "she talks too much" gets fixed, not in `num_predict`.
5. **Don't let a persona grow long.** 1,191 chars dropped tag compliance 56% → 36%; halving it
   recovered it. Current: intp 610, cheerful 299. Measure with `check_moods.py` before growing.
6. **SBV2 cannot laugh.** `heh`/`haha`/`pfft` come out as spelled letters. Tested and rejected;
   humour has to live in the words.
7. **The GPU is rarely the bottleneck.** A 3.7 tok/s stall was the `q8_0` KV cache, not the GPU
   and not the CPU request — the offload log looked healthy throughout. `start.ps1` sets that
   KV cache to fit the PC's 6 GB card; the A10 must not have it.
8. **Warm the TTS, not just the LLM.** Half the slow first turn was SBV2's first CUDA
   inference, which nothing had ever exercised. One throwaway sentence took it 16 s → 8.7 s.
   Warming all four *styles* measured 8.2 s — inside the noise, for 4× the startup cost:
   rejected. ~8 s of first-request cost remains unexplained and is not worth more cold starts.
9. **A rotated token does not reach a running container.** It reads `ZETA_TOKEN` once, at
   startup, and every request you make while testing resets its idle clock so it never scales
   down. A redeploy alone does **not** kill it — `modal app stop zeta -y` first.
10. **`max_containers=1` is deliberate, and so is the forgetting.** `history` and
    `active_persona` live in module globals, so two containers would be two conversations.
    She starts every session fresh; persisting history is explicitly **not** planned.

---

## Known issue, not yet fixed

**The lobby polls `/api/state` every 2.5 s forever**, and while she is awake each poll probes
`/api/health` on the GPU container. Every request resets the 15-minute scaledown clock, so
**leaving the lobby tab open means she never sleeps on her own** — the opposite of what the
page is for. Fix: stop the interval once the state settles (`ready`/`asleep`) and poll only
while `waking`.

---

## The character

Zeta is an introverted INTP by default, so her baseline mood is `pondering` — an INTP is never
neutral, she is thinking.

**Moods are per sentence.** The LLM prefixes each sentence — `[curious] Wait, say that again.`
— and `server.py` strips the tag, voices that sentence with the matching `EMOTION_VOICE`
profile, and sends the mood to the browser with the text, so tone and face shift mid-reply. An
untagged sentence keeps the previous mood, so one miss cannot flatten a whole answer.

Nine moods exist; each persona is offered six (`PERSONA_MOODS`), and giving a persona moods
that suit it measurably improves how often the model tags at all (cheerful went 46% → 68%
just by being offered happy/excited/pouty). Cydonia-24B tags **100%**; Lumimaid-8B managed 67%.

```powershell
python check_moods.py --persona intp --show
```

**The avatar is fully posed** — 25 Live2D parameters across the nine moods (arms, head angle,
gaze, blush, gloom), blended with the idle motion so she keeps breathing, with blinking and
audio-driven lip-sync on top. Never set hair parameters by hand; they follow head angle by
physics. `PARAM_MOUTH_SIZE`, not `PARAM_MOUTH_FORM`, is what makes her smile.

**Text mode** is a toggle in ⚙️ — type instead of talk, skipping STT entirely.

### Tuning — all of it is in `config.py`

| What | Where |
|---|---|
| Personality presets | `PERSONAS` (also editable live in ⚙️) |
| Mood tag instructions | `rules_for()` — keep it mechanical and persona-agnostic |
| Voice per mood | `EMOTION_VOICE` — style, weight, length, `sdp_ratio`, `noisew` |
| Reply length | the LENGTH section of `rules_for()`; `num_predict` is only a backstop |
| STT model | `WHISPER_MODEL` — `tiny`/`base`/`small`/`large-v3-turbo` |

The voice model has only four usable styles (Neutral, ZetaSoft, Zeta, ZetaLoud), so moods are
separated mostly by the numbers, not by style name.

| Script | What it does |
|---|---|
| `probe_cloud.py` | time the deployed app end to end, from inside Modal |
| `check_moods.py` | how often the LLM tags, and how varied the moods are |
| `tune_voice.py` | render one line in every mood profile to `tune/*.wav` |
| `tune_lab.py` | scratch experiments into `tune/lab/` |
| `tune/motion_lab.html` | preview the Live2D poses side by side |

The three tuning tools need **only** SBV2 on :5000, so you can leave Ollama shut down and keep
~5 GB of VRAM free while iterating.

---

## Components

| Part | What | Cloud | Local |
|---|---|---|---|
| Brain | Ollama | **Cydonia-24B** Q4_K_M, `num_ctx` 16384, 24 turns | Lumimaid-8B Q4_K_M, 4096, 12 turns |
| Ears | faster-whisper | `large-v3-turbo`, CUDA | `base`, CPU |
| Mouth | Style-Bert-VITS2, voice **Vestia Zeta** | CUDA | CPU |
| Face | Live2D (Shizuku) in `static/index.html` | browser | browser |
| Web | FastAPI `server.py` + `static/index.html` | Modal HTTPS | HTTPS :8443 |
| Lobby | `lobby()` in `modal_app.py` + `static/lobby.html` | no GPU | — |

The 6 GB card here cannot hold anything past an 8B, which is the whole reason the cloud
exists. Everything else is the same code.

---

## Local mode

For tuning voices and poses without spending money, or if Modal is down.

```powershell
powershell -ExecutionPolicy Bypass -File start.ps1
```
```powershell
powershell -ExecutionPolicy Bypass -File stop.ps1
```

Starts SBV2 (:5000) and the web server (:8443); Ollama runs on its own. Open
**https://localhost:8443**, accept the cert warning, allow the mic.
**Always run `stop.ps1` when done**, or the model stays resident and the GPU is not free.

From the iPad on the same WiFi: allow the port once (PowerShell as Administrator)

```powershell
New-NetFirewallRule -DisplayName "Zeta Voice Chat 8443" -Direction Inbound -LocalPort 8443 -Protocol TCP -Action Allow -Profile Private
```

then open `https://10.10.124.76:8443` (re-check with `ipconfig`; regenerate the cert for a new
IP with `python make_cert.py <new-ip>`).
