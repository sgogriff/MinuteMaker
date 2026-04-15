# MinuteMaker

A hot-folder automation tool that converts raw meeting notes into formatted LaTeX/PDF documents. Drop a `.txt` file into the input folder and get a polished PDF out.

MinuteMaker supports both **cloud** (Anthropic Claude) and **local** (Ollama, llama-cpp, vLLM, or any OpenAI-compatible endpoint) LLM backends, and uses a configurable template system so any organisation can produce minutes in their own format.

## How it works

1. A file watcher monitors the `input/` folder for `.txt` files
2. When a file arrives, MinuteMaker sends it through the processing route for the configured provider
3. `anthropic` generates complete LaTeX directly, while `openai_compatible` returns structured JSON (sections, items, metadata)
4. For `openai_compatible`, MinuteMaker renders the JSON into LaTeX using the selected template
5. `pdflatex` compiles the `.tex` into a PDF
6. Output files appear in `output/`, one self-contained folder per meeting

## Quick start

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Then run the setup wizard:

```bash
python minutemaker.py --init
```

This walks you through choosing a template, LLM provider, and generates your `config.yaml`.

### Cloud mode (Anthropic)

```bash
export ANTHROPIC_API_KEY=your-key-here
python minutemaker.py
```

### Local mode (Ollama)

```bash
# Install Ollama first, then configure MinuteMaker:
python minutemaker.py --provider openai_compatible --base-url http://localhost:11434/v1 --model gemma2:27b
```

Initial Ollama setup is still required. MinuteMaker assumes:

- Ollama is already installed from [ollama.ai](https://ollama.ai)
- the `ollama` command is available on your `PATH`
- the Ollama API is reachable at your configured `base_url`

After that:

- if `managed_server: true` is set in `config.yaml`, MinuteMaker will start and stop Ollama automatically using `server_command` (by default `ollama serve`)
- if `managed_server: false`, you must start Ollama yourself before running MinuteMaker, for example with `ollama serve`
- the configured model is pulled automatically on first use, so no manual `ollama pull` is needed

To switch models, change the `model` line in `config.yaml`. A menu of recommended models with RAM requirements is included in the config file.

If `managed_server: true` is set in `config.yaml`, MinuteMaker will start and stop the Ollama server automatically, freeing GPU/RAM when not processing.

### Verify local setup before cron

Before you enable cron or any other background startup automation, run:

```bash
python verify_local_llm_setup.py
```

This script is designed for non-experts and runs the local setup checks in order:

- confirms Python dependencies and `pdflatex` are installed
- checks that `config.yaml` is set to local mode and points at a model/base URL
- runs a small live prompt against your configured local model
- starts a temporary watcher, drops in the bundled sample notes file, and confirms that MinuteMaker produces both `.tex` and `.pdf` output

The first run may take a while if Ollama still needs to download the model. If the script finishes with all checks passing, your local setup is in good shape and you can enable cron with much more confidence.

At the end, the verifier prints the absolute paths it found for Python, `pdflatex`, and the Ollama binary. Those are the paths you should prefer in cron jobs and in `server_command`, because cron often has a much smaller `PATH` than your normal terminal.

## Local LLM and data privacy

When using a local LLM provider, all processing happens entirely on your machine. No meeting notes, generated content, or metadata are sent to any external service. This makes the local mode suitable for handling sensitive or confidential meeting content and compatible with GDPR and institutional data protection requirements.

MinuteMaker does not store or log the content of your notes beyond the generated output bundles in `output/`. The local LLM server is started on-demand and shut down after processing, so no model remains resident in memory between jobs.

## Usage

```bash
# Watcher mode — monitors input/ for .txt files
python minutemaker.py

# Process a single file
python minutemaker.py --once path/to/notes.txt

# List available templates
python minutemaker.py --list-templates

# Use a specific template
python minutemaker.py --template liverpool
```

## Requirements

- Python 3.10+
- `pdflatex` on PATH ([TeX Live](https://tug.org/texlive/), [MacTeX](https://tug.org/mactex/), or [MiKTeX](https://miktex.org/))
- An Anthropic API key (cloud mode) **or** a local LLM server (local mode)
- For Ollama local mode: Ollama installed locally, with the `ollama` CLI available if you want MinuteMaker to manage the server for you

## Templates

MinuteMaker ships with two templates:

- **`default`** — generic meeting minutes (Welcome, Updates, Discussion, Action Items, AOB, Next Meeting)
- **`liverpool`** — University of Liverpool Nuclear Physics Group format

To create your own template, see [CREATING_TEMPLATES.md](CREATING_TEMPLATES.md).

## Configuration

All settings live in `config.yaml`:

```yaml
template: default                       # template directory name
provider: anthropic                     # anthropic=direct LaTeX, openai_compatible=JSON pipeline
model: claude-sonnet-4-20250514
max_tokens: 8192
input_dir: ./input
output_dir: ./output
log_level: INFO

# For local LLMs:
# base_url: http://localhost:11434/v1
# managed_server: true
# server_command: "ollama serve"
# server_startup_timeout: 120
```

`provider` now also determines the processing mode: `anthropic` uses the direct single-pass LaTeX route, and `openai_compatible` uses the multi-pass JSON route.

For Ollama specifically:

- `managed_server: true` means MinuteMaker will run `ollama serve` for you
- `managed_server: false` means you must already have Ollama running at `base_url`
- model download is automatic once the Ollama server is reachable
- if you plan to run MinuteMaker from cron, prefer an absolute `server_command`, for example `"/absolute/path/to/ollama serve"`

CLI arguments override config file values. See `python minutemaker.py --help` for all options.

Each successful run creates a self-contained bundle in `output/`, for example:

```text
output/
  minutes_2026_04_15/
    minutes_2026_04_15.tex
    minutes_2026_04_15.pdf
    header/
      title_code.tex
      liverpool-logo.png
```

That folder can be copied to another machine and recompiled directly with `pdflatex`.

## Project structure

```text
verify_local_llm_setup.py  # local LLM preflight + watcher smoke test
minutemaker/          # Python package
  cli.py              # CLI entry point, --init wizard
  config.py           # Configuration loading
  pipeline.py         # Core processing pipeline (Anthropic direct LaTeX, local models via JSON)
  providers.py        # LLM provider abstraction
  server.py           # Local LLM server lifecycle + auto model pull
  renderer.py         # JSON → LaTeX rendering
  schema.py           # JSON schema + validation
templates/
  default/            # Generic template
  liverpool/          # Liverpool Nuclear Physics template
```
