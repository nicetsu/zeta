# Zeta

A voice companion you talk to from your iPad, phone, or computer. You speak, she listens,
thinks, and answers out loud in a soft anime voice, and her Live2D face changes with her mood
sentence by sentence.

She runs on a cloud GPU ([Modal](https://modal.com)) that sleeps when you are not using it,
so she costs about **$1–2 a month**.

---

## How to use it

### 1. Open the lobby

```
https://gun-89398--zeta-lobby.modal.run
```

**Bookmark this one**, not the chat page. The lobby tells you whether she is asleep *without*
waking her, so opening it costs nothing.

**The first time on each device** (and each browser), add your access token to the end of the
link once:

```
https://gun-89398--zeta-lobby.modal.run/?k=<your-token>
```

The token is in `zeta-link.txt` in this folder, or in the `Zeta` shortcut on the PC's desktop.
After that one visit the browser remembers it for a year, and the plain link works.

> **Put it on your home screen.** iPad/iPhone: open the lobby in Safari → Share →
> *Add to Home Screen*. Android: Chrome → ⋮ → *Add to Home screen*. It gets the Zeta
> speech-bubble icon and opens full screen, like an app.

### 2. Wake her up

The lobby shows 💤 *she is asleep*. Tap **☀️ wake her up**.

Waking takes about **90 seconds**. A timer and bar show how long it has been, and when she is
ready the lobby opens the chat page for you. If she is already awake, tap **open the chat →**.

### 3. Talk

| | |
|---|---|
| 🎤 | Tap to start talking, tap again to send |
| ⏹ | Tap while she is thinking or speaking to stop her |
| ⚙️ → *Text mode* | Type instead of talking |
| *clear conversation* | Start the conversation over |

Her first reply after waking up takes about **9 seconds**; after that she answers in **1–3
seconds**. She speaks and understands **English only**.

### 4. Pick her personality

⚙️ → **Introvert** or **Extrovert** → *Save & Apply*. You can switch at any time.

| | |
|---|---|
| **Introvert** (default) | Quiet and thoughtful. Thinks out loud, skips small talk, dry deadpan humour. Short answers to small talk, long ones to real questions. |
| **Extrovert** | Cheerful and teasing. Talks in short bursts and throws the conversation back to you. |

### 5. When you are done: 😴 sleep now

Tap **😴 sleep now** at the bottom of the chat page. She goes to sleep right away and the
billing stops. If you forget, she falls asleep by herself after **15 minutes** of silence —
which works too, but costs a little more.

**She forgets the conversation when she sleeps.** Every session starts fresh.

While she is asleep the page only shows ☀️ — tap it to wake her again.

---

## Good to know

- **Cost.** Modal charges for the time she is awake, not for how much you talk. Tapping 😴
  when you finish roughly halves the bill.
- **Keep the links private.** Your voice and your conversations go to Modal's servers. The
  token keeps others out of the conversation, but anyone who has the *chat page* link can still
  wake the GPU and cost you money, even without the token. A budget cap on Modal is the safety
  net — see below.
- **Where it works.** Safari on iPad/iPhone, Chrome on Android and desktop. Chrome on iPhone
  should work but is untested; if the mic does not, use Safari or Text mode.
- **She can't laugh out loud** — the voice model reads "haha" as letters, so her humour lives
  in the words.
- **The voice belongs to a real VTuber.** Fine for personal use; don't publish recordings.

> **One-time setup still to do:** set a spending cap at
> <https://modal.com/settings/usage> (for example $5). Normal use is under $2 a month.

---

## If something goes wrong

| What you see | What to do |
|---|---|
| `{"detail":"unauthorized"}` | This browser has not seen the token yet. Open the link with `?k=<your-token>` once. |
| Lobby: *she did not start — try again* | Tap ☀️ again. If it keeps happening, check your Modal account at <https://modal.com/settings>. |
| Lobby: *could not read her state* | Check your internet connection and reload. |
| Waking says *longer than usual* | Give it another minute or two. Past about 3 minutes, go back to the lobby and try again. |
| Text appears but there is no voice, and her mouth doesn't move | The voice server stopped. Tap 😴, then ☀️ — waking restarts everything. |
| ⚠️ *the brain is not answering* or *the voice server is not answering* | Same: 😴 then ☀️. If it comes back, see [MAINTENANCE.md](MAINTENANCE.md). |
| `Server: modal-http: …` in the chat | A problem with the Modal account itself, usually billing. Check <https://modal.com/settings>. |
| The mic doesn't work | Allow microphone access when the browser asks. On iPhone, use Safari. Or use Text mode. |

Anything deeper — slow replies, flat moods, logs — is in **[MAINTENANCE.md](MAINTENANCE.md)**.

---

## Changing things

Everything you would want to tune is in [`config.py`](config.py): the personalities
(`PERSONAS`), how each mood sounds (`EMOTION_VOICE`), the models, and the speech recognition.

Edits do nothing to the live app until you deploy:

```bash
python -m modal deploy modal_app.py
```

To try voices and poses **for free** on this PC instead of the cloud, use local mode
(`start.ps1` / `stop.ps1`) — see [MAINTENANCE.md](MAINTENANCE.md#local-mode).

---

## What's in here

```
modal_app.py          Modal deployment: the GPU chat app and the no-GPU lobby
server.py             Chat server: speech-to-text → LLM → text-to-speech, streamed
config.py             Everything tunable: models, voice, personalities
static/index.html     The chat page (Live2D face, mic, settings)
static/lobby.html     The lobby (status and wake button)
static/favicon.svg    The logo
start.ps1, stop.ps1   Run it locally on this PC
probe_cloud.py        Time the deployed app end to end
check_moods.py        Check how well the model follows the mood format
tune_voice.py, tune_lab.py, tune/motion_lab.html   Voice and pose tuning tools

SETUP.md              Install everything from scratch
MAINTENANCE.md        How it works, costs, troubleshooting, and known traps
```

Model weights and the Style-Bert-VITS2 voice engine are not in this repository — they are
tens of gigabytes. [SETUP.md](SETUP.md) covers where they come from.

**Built with** Cydonia-24B (LLM, via Ollama), faster-whisper `large-v3-turbo` (speech
recognition), Style-Bert-VITS2 (voice), the Live2D Shizuku sample model, FastAPI, and Modal.
