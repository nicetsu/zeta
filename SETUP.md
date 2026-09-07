# Setting Zeta up from scratch

Only needed once. Day-to-day use, costs and troubleshooting are in [README.md](README.md).

**Do this first on a Thai Windows console:** `setx PYTHONUTF8 1`. The `modal` CLI prints `✓`,
which cp874 cannot encode, and the command dies before doing any work.

---

## Cloud (Modal)

```bash
pip install modal
python -m modal setup
```

**1. Access token.** A Modal URL is public and the app has no login of its own:

```bash
python -m modal secret create zeta-auth ZETA_TOKEN=something-long-and-random
```

**2. Voice + BERT weights (~1.1 GB) onto the Volume:**

```powershell
powershell -ExecutionPolicy Bypass -File prepare_upload.ps1
```

**3. The LLM (~14 GB, downloaded by Modal, not by you):**

```bash
python -m modal run modal_app.py::warm
```

**4. Try it on a temporary URL.** Watch this terminal — the first container start pulls the
image and loads both models, so give it a few minutes. Note trap 2 in README: no live reload
on Windows, so Ctrl-C and restart after every edit.

```bash
python -m modal serve modal_app.py
```

**5. Deploy.** Gives the two permanent URLs listed in README:

```bash
python -m modal deploy modal_app.py
```

Then set a budget cap at <https://modal.com/settings/usage>.

### Why the image is built the way it is

- Weights (~15 GB) live on a **Volume**, not in the image, so they are not re-downloaded on
  each cold start.
- **Do not `pip install style-bert-vits2`.** The local checkout is newer than the PyPI release
  (it has `nlp/onnx_bert_models.py`, which the patched `server_fastapi.py` imports), so the
  local package is copied in and found via `cwd=/sbv2`. Versions are pinned to exactly what
  the working PC venv has — in particular `transformers==4.57.6`, because newer releases need
  torch≥2.5 while SBV2 pins torch<2.4.
- `zstd` is an apt dependency: the Ollama installer needs it to unpack its release archive.
- **No `OLLAMA_KV_CACHE_TYPE` in the cloud** — see trap 7 in README.

---

## This PC

- Models and caches live on **D:** (C: was nearly full): `OLLAMA_MODELS`, `HF_HOME`,
  `NLTK_DATA`. `start.ps1` derives all of them from `$PSScriptRoot`, so moving the project
  folder keeps working — but see trap 1 in README for the two things that don't.
- SBV2 runs in its **own Python 3.11 venv** (`Style-Bert-VITS2\venv`), torch `2.3.1+cu121`,
  CUDA available. It still runs on CPU locally because `config.yml` says `device: cpu` — and
  that is deliberate: the 6 GB card cannot hold Lumimaid and SBV2 at the same time.
- Lumimaid's default tag is Q8 (~8.5 GB) — too big for 6 GB, CUDA crashes on partial offload.
  Use the **Q4_K_M** GGUF.
- SBV2 `config.yml`: `device: cpu`, `limit: 1000`. `server_fastapi.py` is patched to skip the
  Japanese `pyopenjtalk` worker and preload the **EN** BERT.
- deberta-v3-large weights converted to `model.safetensors` (transformers blocks `.bin` on
  torch<2.6); `nltk` pinned to 3.8.1 (3.4.5 breaks on Python 3.11); EN g2p data downloaded.

---

## Considered and not done: GPU memory snapshots

Modal can snapshot GPU memory and restore it instead of reloading weights — their benchmark
restores a 9 GiB checkpoint in ~2.25 s versus ~50 s cold, which is the only change that would
actually remove the ~89 s.

```python
@app.cls(gpu="A10", enable_memory_snapshot=True,
         experimental_options={"enable_gpu_snapshot": True}, ...)
```

**Not enabled on purpose.** The feature is designed around an in-process Python inference
server; here the LLM lives in a separate `ollama serve` process, and snapshotting another
process's CUDA state is exactly the case Modal flags as unreliable. The fallback would be
serving the GGUF from `llama-cpp-python` in-process, losing Ollama's model management.

Note the user has said the ~89 s itself is fine — what was missing was being *told* what is
happening, which the lobby and the progress display now do.
