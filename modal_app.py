"""
Modal deploy layer for Zeta.

Runs the whole stack inside ONE GPU container, so `config.py` can keep pointing at
localhost for both Ollama (:11434) and Style-Bert-VITS2 (:5000) exactly like it does
on the PC:

    Modal HTTPS URL  ->  server.py (FastAPI, this container)
                          |-- ollama serve      :11434   (LLM, GPU)
                          '-- server_fastapi.py :5000    (SBV2 TTS, GPU)

Model weights (~15 GB: Cydonia-24B Q4 plus the SBV2 voice and EN BERT) live on a Modal
Volume, so they are NOT baked into the image and are not re-downloaded on each cold start.

Commands
--------
    modal setup                       # one-time login
    modal run   modal_app.py::warm    # pull the LLM into the Volume (first time only)
    modal serve modal_app.py          # dev: live-reloads, temporary URL
    modal deploy modal_app.py         # production: permanent URL

See SETUP.md for the full first-time walkthrough.
"""

import os
import subprocess
import time
import urllib.request

import modal

APP_NAME = "zeta"
MODELS_DIR = "/models"          # Volume mount point
CODE_DIR = "/app"               # our server.py / config.py / static/
SBV2_DIR = "/sbv2"              # Style-Bert-VITS2 code

# The LLM tag from config.py's CLOUD branch. Kept here too so `warm` can pull it without
# importing config (which would drag in the whole app at build time). Keep these in sync.
LLM_TAG = "hf.co/TheDrummer/Cydonia-24B-v4.3-GGUF:Q4_K_M"

# ---------------------------------------------------------------------------
# Volume: holds the Ollama blobs, the EN BERT, and the SBV2 voice model.
# ---------------------------------------------------------------------------
vol = modal.Volume.from_name("zeta-models", create_if_missing=True)

# ---------------------------------------------------------------------------
# Image
#
# SBV2's requirements.txt is the *training* set (gradio, tensorboard, pyannote,
# umap-learn...), so we install only what inference actually imports and copy the
# library in from the local checkout. torch is pinned <2.4 because SBV2 requires it.
# ---------------------------------------------------------------------------
image = (
    modal.Image.from_registry(
        "nvidia/cuda:12.1.1-cudnn8-runtime-ubuntu22.04", add_python="3.11"
    )
    # zstd is required by the current Ollama installer to unpack its release archive;
    # without it the install script exits 1 and the image build fails.
    .apt_install("curl", "ffmpeg", "git", "libsndfile1", "zstd")
    # Ollama
    .run_commands("curl -fsSL https://ollama.com/install.sh | sh")
    # torch first, from the cu121 index, so nothing else pulls a CPU build
    .pip_install(
        "torch==2.3.1",
        "torchaudio==2.3.1",
        index_url="https://download.pytorch.org/whl/cu121",
    )
    .pip_install(
        # SBV2 inference.
        #
        # NOTE: do NOT `pip install style-bert-vits2`. The local checkout is newer than
        # the PyPI release (it has nlp/onnx_bert_models.py, which the release lacks) and
        # the patched server_fastapi.py imports it. The venv on the PC doesn't install
        # the package either - it runs it straight out of the repo dir. So the local
        # style_bert_vits2/ package is copied in below and found via cwd=/sbv2.
        #
        # Versions are pinned to exactly what the working PC venv has. In particular
        # transformers must be 4.57.6: newer releases require torch>=2.5 and silently
        # disable PyTorch, while SBV2 pins torch<2.4.
        "transformers==4.57.6",
        "numpy==1.26.4",
        "huggingface_hub==0.36.2",
        "safetensors==0.7.0",
        "onnxruntime==1.26.0",
        "accelerate",
        "scipy",
        "loguru",
        "num2words",
        "pypinyin",
        "cn2an",
        "jieba",
        "g2p_en",
        "nltk<=3.8.1",
        "cmudict",
        "pyworld-prebuilt",
        "inflect",
        "numba",
        "pydantic",
        # imported directly by server_fastapi.py
        "GPUtil",
        "psutil",
        # server_fastapi.py imports the Japanese G2P worker at module level even though
        # the patched init skips it - so the package still has to be importable.
        "pyopenjtalk-dict",
        # our web server
        "fastapi",
        "uvicorn[standard]",
        "faster-whisper",
        "requests",
        "python-multipart",
    )
    .env(
        {
            "OLLAMA_MODELS": f"{MODELS_DIR}/ollama",
            "OLLAMA_FLASH_ATTENTION": "1",
            # NOTE: no OLLAMA_KV_CACHE_TYPE here. start.ps1 sets q8_0 to squeeze the
            # model + context into the PC's 6GB card; the A10 has 22GB, so quantizing
            # the KV cache buys nothing and costs a dequantization step per token.
            "OLLAMA_KEEP_ALIVE": "30m",
            "HF_HOME": f"{MODELS_DIR}/hf_cache",
            "NLTK_DATA": f"{MODELS_DIR}/nltk_data",
            "PYTHONUNBUFFERED": "1",
            "ZETA_CLOUD": "1",  # config.py switches to CUDA + no-SSL when set
        }
    )
    # The SBV2 library, straight from the local checkout (11 MB of pure Python) so it
    # matches the patched server_fastapi.py exactly. Found at import time via cwd=/sbv2.
    # Weights are NOT here - they come from the Volume at runtime.
    .add_local_dir(
        "Style-Bert-VITS2/style_bert_vits2", f"{SBV2_DIR}/style_bert_vits2"
    )
    .add_local_file(
        "Style-Bert-VITS2/server_fastapi.py", f"{SBV2_DIR}/server_fastapi.py"
    )
    # server_fastapi.py does `from config import get_config` - that is SBV2's OWN
    # config.py at its repo root, not ours. It reads config.yml next to it.
    .add_local_file("Style-Bert-VITS2/config.py", f"{SBV2_DIR}/config.py")
    .add_local_file("Style-Bert-VITS2/config.yml", f"{SBV2_DIR}/config.yml")
    .add_local_file("Style-Bert-VITS2/default_config.yml", f"{SBV2_DIR}/default_config.yml")
    # get_path_config() copies configs/default_paths.yml on first run; it also sets
    # assets_root: model_assets, which is why the Volume symlink below is named that.
    # dict_data/ is the pyopenjtalk user dictionary - unused in EN-only mode, but tiny
    # and update_dict() reads it, so ship it rather than rely on the try/except.
    .add_local_dir("Style-Bert-VITS2/configs", f"{SBV2_DIR}/configs")
    .add_local_dir("Style-Bert-VITS2/dict_data", f"{SBV2_DIR}/dict_data")
    # our app
    .add_local_file("server.py", f"{CODE_DIR}/server.py")
    .add_local_file("config.py", f"{CODE_DIR}/config.py")
    .add_local_dir("static", f"{CODE_DIR}/static")
)

app = modal.App(APP_NAME, image=image)


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _wait_for(url: str, name: str, timeout: int = 300) -> None:
    """Block until an HTTP endpoint answers, or raise."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            urllib.request.urlopen(url, timeout=3)
            print(f"[zeta] {name} is up.")
            return
        except Exception:
            time.sleep(1)
    raise RuntimeError(f"{name} did not come up within {timeout}s ({url})")


def _start_ollama() -> subprocess.Popen:
    print("[zeta] starting ollama serve...")
    p = subprocess.Popen(["ollama", "serve"])
    _wait_for("http://127.0.0.1:11434/api/tags", "ollama")
    return p


def _start_sbv2() -> subprocess.Popen:
    """SBV2 reads weights from the Volume; its own code picks CUDA automatically."""
    # server_fastapi.py resolves bert/ and model_assets/ relative to its cwd, so
    # link the Volume copies into the code dir instead of copying 1 GB around.
    for name in ("bert", "model_assets"):
        link = os.path.join(SBV2_DIR, name)
        target = os.path.join(MODELS_DIR, name)
        if not os.path.exists(link):
            os.symlink(target, link)

    print("[zeta] starting Style-Bert-VITS2...")
    p = subprocess.Popen(["python", "server_fastapi.py"], cwd=SBV2_DIR)
    _wait_for("http://127.0.0.1:5000/docs", "sbv2", timeout=600)
    return p


# ---------------------------------------------------------------------------
# One-off: pull the LLM into the Volume. Run once, before the first serve/deploy.
#   modal run modal_app.py::warm
# ---------------------------------------------------------------------------
@app.function(volumes={MODELS_DIR: vol}, gpu="A10", timeout=3600)
def warm():
    os.makedirs(f"{MODELS_DIR}/ollama", exist_ok=True)
    proc = _start_ollama()
    print(f"[zeta] pulling {LLM_TAG} (~14 GB, one time)...")
    subprocess.run(["ollama", "pull", LLM_TAG], check=True)
    subprocess.run(["ollama", "list"], check=True)
    proc.terminate()
    vol.commit()
    print("[zeta] LLM stored on the Volume.")


# ---------------------------------------------------------------------------
# The web app.
#
# scaledown_window=900 keeps the container alive for 15 min of silence, so a pause
# mid-conversation does NOT trigger a cold start. At ~45 min/month of real use this
# still costs well under $1 - far inside the $30/month free credit.
# ---------------------------------------------------------------------------
@app.cls(
    gpu="A10",
    # No cpu= / memory= request, and that is MEASURED, not assumed (2026-09-04).
    # cpu=8.0 + memory=16384 were added at the same time as dropping the q8_0 KV cache
    # while chasing a 3.7 tok/s stall, so it was never clear which of the two fixed it.
    # An A/B of the two allocations in one session, same model, same volume:
    #     no request : 30.65 tok/s median (30.64-30.71), peak 0.56 of 17 visible cores
    #     cpu=8.0 +
    #     memory=16G : 31.04 tok/s median (30.99-31.09), peak 0.58 of 24 visible cores
    # 1.3% of generation speed - 0.07s on a 180-token reply - for 31.4% of the bill, and
    # the two arms landed on different hosts (17 vs 24 cores), so even that 1.3% is
    # host-to-host noise rather than a CPU effect. llama.cpp reaches for barely half a
    # core, so the request was reserving 8 to use 0.56. The q8_0 KV cache was the whole
    # story. Both arms offloaded 41/41 layers.
    # Note cpu= is a billing/reservation floor, NOT a visibility limit: os.cpu_count()
    # reports the host either way, and Modal bills max(requested, actually used).
    volumes={MODELS_DIR: vol},
    secrets=[modal.Secret.from_name("zeta-auth")],   # provides ZETA_TOKEN
    scaledown_window=900,     # 15 min idle before the container shuts down
    timeout=3600,
    max_containers=1,         # one conversation, one container (history is in-process)
)
@modal.concurrent(max_inputs=10)
class Zeta:
    @modal.enter()
    def start(self):
        print(f"[zeta] cpus={os.cpu_count()}")   # sanity-check the CPU allocation
        os.chdir(CODE_DIR)          # server.py serves static/ by relative path
        self.ollama = _start_ollama()
        self.sbv2 = _start_sbv2()

    @modal.exit()
    def stop(self):
        for p in (getattr(self, "sbv2", None), getattr(self, "ollama", None)):
            if p:
                p.terminate()

    @modal.asgi_app()
    def web(self):
        import sys

        if CODE_DIR not in sys.path:
            sys.path.insert(0, CODE_DIR)
        from server import app as fastapi_app   # noqa: E402  (import after chdir)

        _add_auth(fastapi_app)
        _add_sleep(fastapi_app)
        return fastapi_app


# ---------------------------------------------------------------------------
# Sleep on demand.
#
# Modal bills container WALL-CLOCK, not tokens, so scaledown_window is roughly half the
# monthly bill: measured $1.67/mo, of which $0.73 is the 15-minute idle tail after each of
# 3 sessions. Ending the session explicitly instead of waiting it out takes that to ~$0.95.
#
# Lowering scaledown_window would do the same thing but punishes ordinary pauses mid-
# conversation with a fresh cold start, which is exactly what the 15 minutes is there to
# prevent. A button keeps both: long grace period while you are talking, zero tail when you
# say you are done.
# ---------------------------------------------------------------------------
def _add_sleep(fastapi_app) -> None:
    @fastapi_app.post("/api/sleep")
    def sleep():
        """Stop the idle tail now.

        `stop_fetching_inputs()` makes this container refuse NEW inputs and exit once the
        in-flight ones finish - so the reply to this very request is still delivered, and
        any turn still streaming to another tab finishes rather than being cut off. That
        also means it is not instant: with @modal.concurrent(max_inputs=10) the container
        lives until the last open request closes.

        The next message pays a full cold start (~70 s) instead of landing warm.
        """
        from modal.experimental import stop_fetching_inputs

        stop_fetching_inputs()
        print("[zeta] sleep requested - exiting once in-flight requests finish.")
        return {"ok": True, "cold_start_s": 70}


# ---------------------------------------------------------------------------
# Auth.
#
# A Modal URL is public, and the current app has no login at all. This adds a
# shared-secret gate: open  https://<url>/?k=<token>  once and the token is stored
# in a cookie, so the iPad only needs the link the first time.
#
# Set the token with:
#     modal secret create zeta-auth ZETA_TOKEN=<pick-something-long>
# If the secret is absent the app stays open (fine for `modal serve` while testing).
# ---------------------------------------------------------------------------
def _add_auth(fastapi_app) -> None:
    from fastapi import Request
    from fastapi.responses import JSONResponse, RedirectResponse

    token = os.environ.get("ZETA_TOKEN")
    if not token:
        print("[zeta] ZETA_TOKEN not set - the app is PUBLIC.")
        return

    @fastapi_app.middleware("http")
    async def gate(request: Request, call_next):
        if request.cookies.get("zeta_auth") == token:
            return await call_next(request)
        if request.query_params.get("k") == token:
            resp = RedirectResponse(url=request.url.path or "/")
            resp.set_cookie(
                "zeta_auth", token, max_age=60 * 60 * 24 * 365,
                httponly=True, samesite="lax", secure=True,
            )
            return resp
        return JSONResponse({"detail": "unauthorized"}, status_code=401)


# ---------------------------------------------------------------------------
# The lobby: a second web app with NO GPU, on its own URL.
#
# The chat page is served by the GPU container itself, so merely opening it has already
# triggered a ~89 s cold start - against a blank browser, before any of our JavaScript
# has run. No amount of work inside static/index.html can reach that case.
#
# This function loads no models, so it starts in a couple of seconds, and it can read the
# GPU app's container count WITHOUT starting one:
#
#     Cls.from_name("zeta", "Zeta")().web.get_current_stats().num_total_runners
#
# That is the whole point: state first, then the user chooses to wake her. Bookmark this
# URL on the iPad instead of the chat URL.
# ---------------------------------------------------------------------------
WEB_URL = "https://gun-89398--zeta-zeta-web.modal.run"

# Measured over four cold starts on 2026-09-05; the page draws an elapsed bar against it.
COLD_START_S = 89

lobby_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("fastapi", "uvicorn[standard]")
    .add_local_file("static/lobby.html", "/lobby/lobby.html")
)


@app.function(
    image=lobby_image,
    secrets=[modal.Secret.from_name("zeta-auth")],
    # Long enough to outlive a cold start it kicked off, so the background wake request
    # below is not cut short by this container scaling down under it.
    scaledown_window=300,
    timeout=600,
)
@modal.concurrent(max_inputs=20)
@modal.asgi_app()
def lobby():
    import json
    import threading

    from fastapi import FastAPI
    from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

    web = FastAPI(title="Zeta lobby")
    token = os.environ.get("ZETA_TOKEN", "")

    def _runners() -> int:
        """How many containers the GPU app is running. Reading this does NOT start one."""
        from modal import Cls

        # Function.from_name(APP_NAME, "Zeta.web") raises InvalidError: `web` is a method
        # on the class, so the class is looked up and INSTANTIATED first - note the ().
        return Cls.from_name(APP_NAME, "Zeta")().web.get_current_stats().num_total_runners

    def _health(timeout: float):
        """Ask the GPU app how it is. None means no answer yet - i.e. still starting.

        The timeout is deliberately short when polling: a long one would hold a request
        open against the GPU container, keeping it busy while we merely watch it.
        """
        req = urllib.request.Request(
            f"{WEB_URL}/api/health", headers={"Cookie": f"zeta_auth={token}"}
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode())
        except Exception:
            return None

    @web.get("/api/state")
    def state():
        try:
            runners = _runners()
        except Exception as e:
            # Say so rather than reporting "asleep", which would offer a wake button for
            # a problem no amount of waking fixes.
            return JSONResponse({"error": str(e)}, status_code=502)
        if runners < 1:
            return {"awake": False, "runners": 0}
        # Only probe health once a container exists - probing an asleep app would wake it,
        # which is exactly what this page is here to avoid.
        return {"awake": True, "runners": runners, "health": _health(4)}

    @web.post("/api/wake")
    def wake():
        """Start the GPU container on purpose, without making the browser wait for it.

        The one request that triggers the cold start is held here, in a background thread,
        instead of by the browser - so the page can render progress while it happens. The
        client then polls /api/state, which is cheap and does not touch the GPU app until
        a container exists.
        """
        threading.Thread(target=_health, args=(300.0,), daemon=True).start()
        print("[zeta-lobby] wake requested")
        return {"ok": True, "estimate_s": COLD_START_S}

    @web.get("/go")
    def go():
        """Hand over to the chat page.

        The token rides along because the chat app is a DIFFERENT subdomain, so the cookie
        set on the lobby does not reach it. This is the same `?k=` handoff the README
        already documents, and reaching this route required the token in the first place.
        """
        return RedirectResponse(url=f"{WEB_URL}/?k={token}" if token else WEB_URL,
                                status_code=302)

    @web.get("/")
    def index():
        return FileResponse("/lobby/lobby.html")

    # _add_auth covers the GPU app only - this app is a separate ASGI application on a
    # separate URL and needs its own copy of the gate.
    _add_auth(web)
    return web
