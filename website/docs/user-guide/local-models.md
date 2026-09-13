---
sidebar_position: 4
title: Local Models
description: Run models on your own machine by default — no account or API key required. Optional benchmark reports leave only after your review and confirmation.
---

# Local Models

![A local workstation running an AI model inside its own compute enclosure.](/img/docs/local-models/hero.png)

Hermes can run open models entirely on your own machine. It downloads and
manages the inference engine (llama.cpp), picks a curated build for your
hardware, and handles memory on the default path. You pick a model; Hermes
does the rest.

Nothing leaves your computer by default: no account, no API key, and no
network access after a model is downloaded. The only exception is an optional
one-shot benchmark report that you explicitly run, review, and submit; it is
off by default and never runs on its own.

## Getting started

1. Open **Settings → Providers → Local Models** (or choose **Run models
   locally** during onboarding).
2. Click **Install runtime**. Hermes downloads the official llama.cpp
   build for your hardware (a few hundred MB), verifies it, and keeps it
   updated.
3. Pick a model from the catalog and click **Download**.
4. Click **Use**. New chats now run on the local model.

That's the whole flow. The server starts and stops with Hermes, restarts
survive app restarts, and switching back to a cloud provider is one click
in the model picker.

## How Hermes picks what to download

Every model in the catalog is priced against **your machine** before you
download anything. Each row shows:

- **Memory fit** — green (*Fits your GPU*: runs entirely in GPU memory),
  amber (*Uses system RAM*: works, but slower), or red (*Too big for this
  machine*).
- **Context** — the window the model starts with and the maximum it can
  grow to.
- The download size of the build selected for your hardware.

The curated catalog selects one reviewed quantization for each model. To
choose another quantization, use **Find more models** and select the GGUF
file you want; Hermes shows its separate fit estimate before downloading.
The catalog does not offer variants below 4-bit because their quality loss is
usually too severe for the supported path.

Models that don't fit stay visible with the reason, so you always know
what a hardware upgrade would unlock.

## How memory management works

Local models live or die by memory placement, so Hermes manages the default
path end-to-end:

- **Models start at a context window that fully fits your GPU** and grow
  toward their native maximum as your conversation needs more room. You
  may see "Context window grown" in the status feed during long sessions
  — that's the window expanding, not an error.
- **Every recommended model gets at least a 64K context window.** When a
  model is larger than your GPU's memory, Hermes deliberately places the
  overflow in system RAM in the order that hurts least (expert weights
  first, never the attention cache), trading some speed to protect the
  context guarantee.
- **Conversation compression only kicks in at the model's maximum
  window** — growth always comes first.
- Idle models are unloaded after 15 minutes to free GPU memory; they
  reload automatically on the next message.

### Advanced launch settings

The Local Models screen also has an **Advanced local runtime** section for a
staged model. It can preview and apply a per-request context window, inference
slot count, `Q8_0` or `F16` KV cache, and supported MTP speculative decoding. Hermes
prices shared weights once and KV/work buffers per slot before it writes a
setting. A request that does not fit is rejected; it is never quietly reduced.

The server receives aggregate context (`per-request context × slots`) so each
slot retains the context selected in the UI. MTP can only be forced for a model
with a validated Hermes recipe. Applying a changed plan waits for the selected
managed runtime to become idle and restarts it only then. Automatic
window growth remains the default when no explicit context is configured.

## Optional benchmark contribution

If you want to contribute a comparable result for an installed local model,
the **Local Models** screen can run one fixed, short benchmark. This is a
separate feature from shared metrics and is disabled by default. It does not
run after a download, install, activation, chat, or runtime restart.

You must start the benchmark yourself while the local runtime is running.
Hermes warms the selected model, runs a fixed short generation, and discards
both generated responses. It then shows the resulting report in the Local
Models screen. Nothing is sent merely by running the test: you must review the
report, choose **Submit**, and confirm the submission. Even after you have
allowed submissions once, every later report still needs its own manual run,
review, Submit click, and confirmation. Hermes does not collect these results
in the background or queue an automatic upload.

### Exactly what the report contains

The report has a closed allowlist, which Hermes validates again immediately
before it is sent. It contains only:

- The fixed test kind, elapsed time, prompt/completion token counts, and
  prompt/completion tokens per second.
- Total device memory, total system memory, and whether memory is unified.
- The model family (or `sideloaded`), quant, total weight bytes, lookup-table
  bytes, and lookup placement.
- The llama.cpp build and backend; selected context, slots, KV cache, and
  speculative-decoding settings; and whether ordinary model weights spill into
  system RAM.
- A random per-report package ID, timestamp, and schema version.

It does **not** include the prompt or generated text, a model file, repository,
or local path, your hostname or user name, GPU/CPU names or serial numbers, IP
address, account details, credentials, chat history, or a raw copy of your
configuration.

The configured endpoint must use HTTPS (loopback HTTP is accepted only for
local testing), and it is visible in your profile configuration rather than
being supplied through an environment variable.

### Stop or revoke sharing

After a successful first submission, Hermes records profile-local consent so
the screen can show that sharing is enabled. Choose **Stop sharing** in Local
Models, or set the following value to `false`, to revoke that saved consent:

```yaml
telemetry:
  local_model_benchmarks:
    enabled: false
    # endpoint: https://telemetry.nousresearch.com/v1/telemetry
```

Revoking consent stops the enabled state immediately; it does not affect a
report you already chose to send. A later contribution requires a new local
benchmark, a fresh review, and another explicit confirmation. This setting is
independent of `telemetry.shared_metrics`.

### Backend guide for assisting integrations

Trusted local integrations can read `GET /api/local-models/agent-instructions`
for the complete managed path: hardware and catalog inspection, compatible
llama.cpp installation, complete split-GGUF download, PLE/Engram lookup-table
placement, typed launch plans, gateway aliases, and the nested benchmark
contract. It is a read-only guide, not an authorization to change settings or
send data. In particular, an integration must not expose benchmark submission
as a model-callable action; the user-controlled review and confirmation flow
remains the required boundary.

## The status bar

Right-click the status bar and enable **System resources** to see live GPU
utilization, GPU memory, and RAM while local models run. The context meter
always reflects the window the model is actually running with.

## Finding more models

The catalog is a curated starting point, not a boundary. The **Find more
models** section on the same page searches all of Hugging Face:

- Results show download counts and a per-file fit check sized to your
  machine, so you know before downloading whether a build runs fully on
  your GPU.
- Anything you download behaves exactly like a catalog model — Hermes
  reads the model file itself to pick its context window and memory
  placement. The only difference: community models don't carry our
  "validated" testing badge.
- Already have a `.gguf` file on disk? **Add model file** links it into
  your library without copying it (the original stays where it is), and
  it's usable immediately.

## Using your own llama-server

If a llama-server is already running on your machine, Hermes detects it
and uses it instead of starting its own. Point a custom endpoint at any
OpenAI-compatible server for full manual control — the managed runtime is
a default, not a requirement. For manual setups (Ollama, MLX, custom
builds, headless CLI machines), see
[Run Hermes Locally with Ollama](/guides/local-ollama-setup) and
[Run Local LLMs on Mac](/guides/local-llm-on-mac).

## Configuration

The managed runtime is controlled by the `local_runtime` section of
`config.yaml`. The desktop UI writes these values for you; they're
documented for CLI and headless use:

```yaml
local_runtime:
  enabled: false     # true = start the managed server with Hermes.
                     # The desktop "Use" button sets this automatically.
  backend: auto      # auto | cuda | metal | vulkan | hip | cpu
  tag: b10679        # pinned llama.cpp release; Hermes updates it with
                     # each release after re-validation
  launch_overrides:  # optional per-staged-model advanced settings
    My-Local-GGUF:
      context_tokens: 65536
      slots: 2
      kv_cache: q8_0 # q8_0 | f16
      speculation: auto # auto | off | mtp (mtp requires a validated recipe)
```

Models and runtime builds live under the Hermes home directory
(`models/` and `runtimes/llamacpp/`). Selecting a local model as your
main model uses the standard `model.provider: llamacpp` +
`model.default` settings — the same shape as every other provider.

## Requirements and limits

- **Windows and Linux:** NVIDIA GPU (CUDA) or CPU. **macOS:** Apple
  Silicon (Metal). Vulkan builds serve AMD GPUs.
- A GPU with 8 GB+ of memory runs the small catalog models comfortably;
  16 GB+ runs the 27–35B models at high quality.
- Model downloads are byte-size checked against the catalog during the
  transfer; an incomplete download is deleted and reported, never
  half-used. (Only the runtime engine zips are SHA-256 verified.)
- Deleting a model removes every file it staged, including vision
  adapters and speculative-decoding companions.
