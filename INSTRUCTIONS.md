# MinuteMaker — User Guide

A tool that turns rough meeting notes into a formatted LaTeX PDF automatically. Works with cloud AI (Anthropic Claude) or local LLMs (Ollama, etc.).

---

## How it works (the short version)

1. You drop a `.txt` file into the `input/` folder
2. The script detects it, reads it, and sends it to the configured LLM
3. If you are using Anthropic, the model generates the full LaTeX document directly; if you are using a local/OpenAI-compatible model, it first extracts structured JSON
4. For local/OpenAI-compatible mode, MinuteMaker renders that JSON into a LaTeX document using your template
5. `pdflatex` compiles it into a PDF inside a self-contained folder under `output/`
6. You check it, fix anything that needs fixing, and you're done

Under the hood: a Python watchdog process monitors the input folder, the LLM does the heavy lifting of understanding messy notes, and pdflatex handles compilation. Anthropic generates LaTeX directly; local/OpenAI-compatible models use a JSON extraction route first. The template (section structure, header, logo, etc.) is all configurable.

---

## Setup

You'll need:

- Python 3.10+
- A LaTeX installation — [MacTeX](https://www.tug.org/mactex/) (macOS) or [TeX Live](https://www.tug.org/texlive/) (Linux)
- **Either** an Anthropic API key ([console.anthropic.com](https://console.anthropic.com)) **or** a local LLM server (e.g. [Ollama](https://ollama.ai))

```bash
# 1. Clone the repo and navigate into it
cd MinuteMaker

# 2. Create and activate a virtual environment
python3 -m venv .venv
source .venv/bin/activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run the setup wizard
python minutemaker.py --init
```

The setup wizard walks you through choosing a template, LLM provider, and generates your `config.yaml`.

### Cloud setup (Anthropic)

```bash
cp .env.example .env
# Edit .env and add your Anthropic API key
```

### Local setup (Ollama)

```bash
# Install Ollama from https://ollama.ai
```

MinuteMaker does not install Ollama for you. It assumes:

- Ollama is installed locally
- the `ollama` command is available on your `PATH`
- the Ollama API is reachable at the `base_url` in `config.yaml`

If `managed_server: true` is set in `config.yaml`, MinuteMaker can start and stop Ollama automatically using `ollama serve`.

If `managed_server: false`, you must start Ollama yourself before running MinuteMaker.

The selected model is pulled automatically on first use, so you do not need to run `ollama pull` manually.

### Before you enable cron or any other background startup task

Run:

```bash
python verify_local_llm_setup.py
```

This is the easiest way to check that local mode is really ready. The script will:

- check that Python dependencies are installed
- check that `pdflatex` is available
- check that `config.yaml` is set to local mode
- send a small test prompt to your configured local model
- start a temporary watcher, drop in the bundled sample notes file, and confirm that MinuteMaker creates both a `.tex` file and a `.pdf`

If that script passes, your local setup is working end-to-end. Only then should you enable cron.

Important for cron:

- use absolute paths for the Python interpreter in the cron job
- use an absolute path in `server_command` if cron cannot find `ollama`
- the verifier prints the paths it found at the end, so you can copy those into your cron setup

If you just want a quick preflight check without the full watcher test, run:

```bash
python verify_local_llm_setup.py --quick
```

---

## Running the script

### Normal use (hot-folder / watchdog mode)

```bash
python minutemaker.py
```

This starts the watcher. It sits quietly in the background and processes any `.txt` file you drop into `input/`. Compiled output appears in `output/`, one folder per meeting. Stop it with `Ctrl+C`.

### One-shot mode (process a single file)

```bash
python minutemaker.py --once path/to/notes.txt
```

Useful for testing or one-off processing.

### Other options

| Flag | What it does |
|---|---|
| `--config path/to/config.yaml` | Use a different config file |
| `--template name` | Use a specific template |
| `--provider anthropic\|openai_compatible` | Override the LLM provider |
| `--base-url http://...` | Set the local LLM server URL |
| `--input-dir /path` | Override the watched directory |
| `--output-dir /path` | Override the output directory |
| `--list-templates` | Show available templates |
| `--init` | Run the setup wizard |
| `--log-level DEBUG` | More verbose logging |

Most people won't need anything beyond the defaults in `config.yaml`.

---

## Good practices

### Treat the input folder as a one-way drop box

The input folder (`input/`) is a **fire and forget** system. Drop your notes file in once and leave it. Do not:

- Drop a file in, then rename or move it
- Drop multiple revised versions of the same meeting's notes
- Edit a file after it's been dropped in

The watchdog triggers the moment a file appears. If you start moving things around, you risk triggering duplicate processing.

*Drop it in, walk away*.

### This is a drafting tool, not a finished product

The AI is very capable, but it will occasionally misplace a bullet point, mangle a name, or miss a nuance. **Always review the output before distributing the PDF.** The `.tex` file is there specifically so you can open it, fix any errors, and recompile yourself — don't re-run the MinuteMaker script for corrections.

### Cloud API calls cost money

Each time a file is processed via the Anthropic API, it makes a paid API call. The cost per file is very small (usually a penny or two), but that is not an invitation to test repeatedly. Local LLMs have no per-call cost.

---

## Writing a good input file

The AI will do its best to make sense of whatever you give it, but: **garbage in, garbage out**. A well-written input file produces a polished first draft.

### The input file must be `.txt`

Plain text only. Not `.docx`, not `.md`, not `.rtf`. Anything other than `.txt` is ignored.

### More detail is better

Don't just write:

```txt
Fraser — IOP conference.
```

Write:

```txt
Fraser will coordinate IOP conference logistics. He will be in touch with details. Deadline for abstract submissions March 6
```

The AI can only work with what you give it.

### Use section headers

You don't need to match the exact template section names, but giving the AI something to work with makes categorisation much more reliable:

```txt
Dept updates:
nothing to report

Exp and conf:
Alex, Cameron, and Noor at JYFL next week for the Calcium experiment
Taylor got a poster at INPC in South Korea, May 25-30

Group successes:
Tony submitted his thesis, congrats!
```

### Include web links

If you want a link in the minutes, put the full URL in the notes. If you only write "see the IOP website", no link will appear.

### Name the chair and secretary explicitly

Write something like:

```text
Chair: Emily
Secretary: Fraser
```

somewhere in the notes. Otherwise the output will use "Check Meeting Schedule" as a placeholder.

---

## Where do the output files go?

Each processed meeting gets its own folder in `output/`, named from the meeting date:

```text
output/
  minutes_YYYY_MM_DD/
    minutes_YYYY_MM_DD.tex
    minutes_YYYY_MM_DD.pdf
    header/
```

That folder contains the files needed to recompile the document elsewhere.

If compilation fails (usually a LaTeX error), the `.tex` file is still written so you can inspect and fix it manually.

---

## Custom templates

MinuteMaker supports multiple templates. To create your own, see [CREATING_TEMPLATES.md](CREATING_TEMPLATES.md).

To switch templates, change the `template` field in `config.yaml` or use `--template name` on the command line.

---

## Something went wrong

Check `minutemaker.log` in the project root. It records every step of the pipeline including any error output from pdflatex.
