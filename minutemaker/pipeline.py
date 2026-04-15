"""Core processing pipeline for provider-specific minutes generation flows."""

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from watchdog.events import FileSystemEventHandler

from .config import load_prompt_rules, load_template_spec
from .providers import LLMProvider, get_provider
from .renderer import render_latex
from .schema import parse_and_validate, schema_as_prompt
from .server import ServerManager

logger = logging.getLogger("minutemaker")

MAX_INPUT_BYTES = 50 * 1024  # 50 KB sanity limit
AUX_EXTENSIONS = (".aux", ".log", ".out", ".synctex.gz", ".fls", ".fdb_latexmk", ".toc")

# ---------------------------------------------------------------------------
# System prompt construction
# ---------------------------------------------------------------------------

BASE_JSON_SYSTEM_PROMPT = """\
You are a structured data extractor for meeting minutes. You will be given raw, \
unstructured meeting notes and must produce a JSON object following the schema below.

CRITICAL RULES:

1.  Return ONLY valid JSON. No markdown fences, no explanations, no preamble \
text. Your entire response must be a single JSON object.

2.  Follow the section names from the template specification EXACTLY. Do not \
invent sections or rename them.

3.  All mandatory sections must appear in the "sections" array, in template \
order. If there is no content for a section, use an empty items list [].

4.  Optional sections should ONLY be included in the "optional_sections" array \
if the raw notes contain relevant content. Otherwise omit them entirely.

5.  The raw notes may be poorly organised, use shorthand, have creative or \
non-standard section headings, or be missing section headings entirely. \
You must read and UNDERSTAND the content, then map each item to the \
correct section by its meaning — not by matching heading names from the \
input. If content does not clearly fit any section, place it in the most \
appropriate catch-all section (often "Any Other Business" or similar).

6.  ALWAYS rewrite the content in polished, professional English. Do not copy \
shorthand, typos, or informal phrasing verbatim. The final text must read \
as a formal but friendly record. Fix spelling, complete half-sentences, and \
improve clarity — while preserving the original meaning exactly.

7.  For links: use \\href{URL}{text} markup in the item strings, but make the \
display text descriptive — not a raw URL.

8.  Use \\textbf{} for deadlines and action items in the item strings.

9.  Date format for "meeting_date" must be DD/MM/YYYY.

10. For "chair" and "secretary": populate these ONLY if the raw notes explicitly \
state who chaired or minuted the meeting. Do NOT infer or guess these names. \
If the information is not directly stated, use "Check Meeting Schedule".
"""

JSON_USER_MESSAGE_TEMPLATE = """\
Today's date is {today}. If relative dates appear in the notes (e.g. \
"tomorrow", "next Tuesday", "this Friday"), resolve them using today's date.

Extract the following raw meeting notes into the JSON format specified in your \
system prompt. Apply all rules — including language polishing.

---
{raw_text}
---"""

BASE_LATEX_SYSTEM_PROMPT = """\
You are a LaTeX document generator for meeting minutes. You will be given raw, \
unstructured meeting notes and must produce a complete, compilable .tex file.

CRITICAL RULES:

1.  Return ONLY the .tex source code. No markdown fences, no explanations, \
no preamble text. Your entire response must start with \\documentclass and \
end with \\end{document}.

2.  Follow the template specification EXACTLY. Section names, section order, \
required metadata, and formatting rules are mandatory.

3.  All mandatory sections must appear, in template order. If a mandatory \
section has no content, include:
    \\begin{itemize}
        \\item Nothing to report.
    \\end{itemize}

4.  Optional sections should be included ONLY if the raw notes contain \
relevant content.

5.  The raw notes may be poorly organised, use shorthand, have creative or \
non-standard section headings, or be missing headings entirely. You must read \
and UNDERSTAND the content, then map each item to the correct section by \
meaning rather than matching the raw headings literally.

6.  ALWAYS rewrite the content in polished, professional English. Do not copy \
shorthand, typos, or informal phrasing verbatim. The final minutes must read \
as a formal but friendly record while preserving the original meaning.

7.  Write in third person, past tense unless the template specification \
requires something else.

8.  Use \\textbf{} for deadlines and action items.

9.  For links: use \\href{URL}{descriptive text}, not raw URLs as display text.

10. Escape LaTeX special characters such as &, %, and # unless they are part \
of valid LaTeX markup.

11. Include \\input{header/title_code.tex} in the preamble and place the \
generation comment immediately after it:
    % Generated with MinuteMaker on DD/MM/YYYY

12. Populate \\def\\chair{} and \\def\\secretary{} ONLY if the raw notes \
explicitly state who chaired or minuted the meeting. Otherwise use \
"Check Meeting Schedule". Do not infer or guess.

13. Ensure the document is structurally complete: it must contain \
\\documentclass, \\begin{document}, \\makeminutestitle, and \\end{document}.
"""

LATEX_USER_MESSAGE_TEMPLATE = """\
Today's date is {today}. If relative dates appear in the notes (e.g. \
"tomorrow", "next Tuesday", "this Friday"), resolve them using today's date.

Convert the following raw meeting notes into a complete LaTeX document. \
Apply all rules from your system prompt, including language polishing.

---
{raw_text}
---"""


def _build_section_info(template_config: dict) -> str:
    """Return the template section list for prompt context."""
    mandatory = template_config.get("mandatory_sections", [])
    optional = template_config.get("optional_sections", [])

    section_info = "Mandatory sections (in order):\n"
    for i, sec in enumerate(mandatory, 1):
        section_info += f"  {i}. {sec['name']}\n"

    if optional:
        section_info += "\nOptional sections (include only if content exists):\n"
        for sec in optional:
            section_info += f"  - {sec['name']}\n"

    return section_info


def build_json_system_prompt(config: dict, template_config: dict) -> str:
    """Assemble the structured-JSON prompt from base rules + template context."""
    template_spec = load_template_spec(config)
    prompt_rules = load_prompt_rules(config)
    section_info = _build_section_info(template_config)

    prompt = (
        BASE_JSON_SYSTEM_PROMPT
        + "\n\n--- JSON SCHEMA ---\n\n"
        + schema_as_prompt()
        + "\n\n--- TEMPLATE SPECIFICATION ---\n\n"
        + template_spec
    )

    prompt += "\n\n--- SECTION LIST ---\n\n" + section_info

    if prompt_rules:
        prompt += "\n\n--- ADDITIONAL RULES ---\n\n" + prompt_rules

    return prompt


def build_latex_system_prompt(config: dict, template_config: dict) -> str:
    """Assemble the direct-LaTeX prompt from base rules + template context."""
    template_spec = load_template_spec(config)
    prompt_rules = load_prompt_rules(config)
    section_info = _build_section_info(template_config)

    prompt = (
        BASE_LATEX_SYSTEM_PROMPT
        + "\n\n--- TEMPLATE SPECIFICATION ---\n\n"
        + template_spec
        + "\n\n--- SECTION LIST ---\n\n"
        + section_info
    )

    if prompt_rules:
        prompt += "\n\n--- ADDITIONAL RULES ---\n\n" + prompt_rules

    return prompt


def build_system_prompt(config: dict, template_config: dict) -> str:
    """Backward-compatible alias for the JSON extraction prompt."""
    return build_json_system_prompt(config, template_config)


# ---------------------------------------------------------------------------
# Pass 2: Item polishing
# ---------------------------------------------------------------------------

POLISH_SYSTEM_PROMPT = """\
You are a copy-editor. Rewrite the given bullet point in professional English.

RULES:
- Output ONLY the rewritten sentence. Nothing else. No preamble like \
"Here is the rewritten bullet point". Just the sentence itself.
- Third person, past tense.
- Fix spelling, grammar, and incomplete sentences.
- Be concise. One to two sentences maximum.
- Do NOT invent dates, numbers, or facts not present in the original.
- Do NOT change any dates or numbers from the original.
- Do NOT expand acronyms or abbreviations. Keep them exactly as written.
- Do NOT add explanations, definitions, or context not in the original.
- Wrap deadlines in \\textbf{}.
- For raw URLs: use \\href{URL}{descriptive text}.

EXAMPLE:
Input: dept budget came through but admin is slow, funds maybe before 20th april
Output: The department budget has been approved, though administrative processing is slow. Funds are expected to be available before \\textbf{20th April}.

Input: CSD is now network admins, thanks Alex for looking after it
Output: CSD has taken over as network administrators. Thanks were extended to Alex for previous efforts in this role."""

POLISH_USER_TEMPLATE = "Rewrite this bullet point:\n\n{item}"


def polish_items(
    data: dict,
    provider: LLMProvider,
    config: dict,
    prompt_rules: str,
) -> dict:
    """Pass 2: rewrite each item in the parsed JSON for professional tone.

    Sends each item individually to the LLM with a focused rewriting prompt.
    Small models handle this single-task prompt much more reliably than trying
    to do extraction + polishing in one pass.
    """
    system_prompt = POLISH_SYSTEM_PROMPT
    if prompt_rules:
        system_prompt += "\n\nAdditional style rules:\n" + prompt_rules

    today = datetime.now().strftime("%d/%m/%Y")
    total = 0
    polished = 0

    # Polish mandatory sections
    for section in data.get("sections", []):
        for i, item in enumerate(section.get("items", [])):
            total += 1
            rewritten = _polish_one_item(item, today, system_prompt, provider, config)
            if rewritten:
                section["items"][i] = rewritten
                polished += 1

    # Polish optional sections
    for section in data.get("optional_sections", []):
        for i, item in enumerate(section.get("items", [])):
            total += 1
            rewritten = _polish_one_item(item, today, system_prompt, provider, config)
            if rewritten:
                section["items"][i] = rewritten
                polished += 1

    logger.info("Polished %d/%d items", polished, total)
    return data


def _polish_one_item(
    item: str,
    today: str,
    system_prompt: str,
    provider: LLMProvider,
    config: dict,
) -> str | None:
    """Send a single item to the LLM for rewriting. Returns the rewritten text,
    or None if the call fails (original item is kept)."""
    # Skip items that are empty or mean "nothing to report"
    stripped = item.strip().rstrip(".").lower()
    if not stripped or stripped in (
        "nothing to report",
        "none",
        "n/a",
        "nil",
        "no updates",
        "no update",
        "no news",
    ):
        return "Nothing to report."

    user_message = POLISH_USER_TEMPLATE.format(today=today, item=item)

    try:
        result = provider.generate(system_prompt, user_message, config)
        result = result.strip().strip('"').strip("'").strip()

        if not result:
            logger.warning("Polish result empty, keeping original")
            return None

        # Strip preamble lines that small models often add
        # e.g. "Here is the rewritten bullet point:\n\nActual content"
        preamble_markers = [
            "here is the rewritten",
            "here's the rewritten",
            "rewritten bullet point:",
            "rewritten version:",
            "revised version:",
            "output:",
        ]
        lines = result.split("\n")
        while lines and any(m in lines[0].lower() for m in preamble_markers):
            lines.pop(0)
        # Also strip blank lines at the top after removing preamble
        while lines and not lines[0].strip():
            lines.pop(0)
        result = "\n".join(lines).strip()

        if not result:
            logger.warning("Polish result empty after stripping preamble, keeping original")
            return None

        # Reject if the model added too much explanation text
        max_len = max(len(item) * 5, 500)
        if len(result) > max_len:
            logger.warning(
                "Polish result rejected (too long: %d chars vs %d original). "
                "First 200 chars: %s",
                len(result), len(item), result[:200],
            )
            return None

        # If the model prefixed with "- " or "* " or a bullet, strip it
        if result.startswith(("- ", "* ", "• ")):
            result = result[2:]
        return result
    except Exception as exc:
        logger.warning("Failed to polish item, keeping original: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Pass 3: Verify completeness — catch dropped content
# ---------------------------------------------------------------------------

VERIFY_SYSTEM_PROMPT = """\
You are a verification assistant. You will be given the original raw meeting \
notes and a JSON summary that was extracted from them. Your job is to find \
any content from the original notes that is MISSING from the JSON.

RULES:
- Output ONLY valid JSON. No markdown fences, no explanations.
- Return a JSON object with a single key "missing_items" containing a list.
- Each item in the list must have "section" (the section name it belongs to) \
and "item" (the text of the missing content, rewritten professionally).
- If nothing is missing, return: {"missing_items": []}
- Only flag genuinely missing content — do not flag minor wording differences.
- Do NOT expand acronyms or abbreviations.
- Do NOT invent information not in the original notes.
- The section name must match one of the sections in the JSON."""

VERIFY_USER_TEMPLATE = """\
ORIGINAL NOTES:
---
{raw_text}
---

EXTRACTED JSON:
---
{extracted_json}
---

List any content from the original notes that is missing from the JSON."""


def verify_completeness(
    data: dict,
    raw_text: str,
    provider: LLMProvider,
    config: dict,
    template_config: dict,
) -> dict:
    """Pass 3: check for content in the raw notes that was dropped during extraction.

    Sends both the raw notes and the extracted JSON to the LLM. If missing
    items are found, they are merged into the appropriate sections.
    """
    extracted_json = json.dumps(data, indent=2)
    user_message = VERIFY_USER_TEMPLATE.format(
        raw_text=raw_text,
        extracted_json=extracted_json,
    )

    try:
        raw_response = provider.generate(VERIFY_SYSTEM_PROMPT, user_message, config)
    except Exception as exc:
        logger.warning("Verification pass failed, skipping: %s", exc)
        return data

    # Parse the response
    from .schema import extract_json
    json_str = extract_json(raw_response)
    try:
        result = json.loads(json_str)
    except json.JSONDecodeError:
        logger.warning("Verification pass returned invalid JSON, skipping")
        return data

    missing = result.get("missing_items", [])
    if not missing:
        logger.info("Verification: no missing content found")
        return data

    # Build lookup of existing sections
    section_lookup = {}
    for sec in data.get("sections", []):
        section_lookup[sec["name"]] = sec
    for sec in data.get("optional_sections", []):
        section_lookup[sec["name"]] = sec

    # Also build a set of known optional section names from the template
    optional_names = {
        s["name"] for s in template_config.get("optional_sections", [])
    }

    added = 0
    for entry in missing:
        if not isinstance(entry, dict):
            continue
        section_name = entry.get("section", "")
        item_text = entry.get("item", "")
        if not section_name or not item_text:
            continue

        if section_name in section_lookup:
            # Append to existing section
            sec = section_lookup[section_name]
            # Don't add if it's a duplicate (fuzzy check)
            existing_lower = [i.lower()[:50] for i in sec["items"]]
            if item_text.lower()[:50] not in existing_lower:
                sec["items"].append(item_text)
                added += 1
        elif section_name in optional_names:
            # Create a new optional section
            new_sec = {"name": section_name, "items": [item_text]}
            data.setdefault("optional_sections", []).append(new_sec)
            section_lookup[section_name] = new_sec
            added += 1
        else:
            # Unknown section — put it in Any Other Business or last catch-all
            for sec in data.get("sections", []):
                if "other business" in sec["name"].lower():
                    sec["items"].append(item_text)
                    added += 1
                    break

    logger.info("Verification: recovered %d missing item(s) from %d flagged", added, len(missing))
    return data


# ---------------------------------------------------------------------------
# Pipeline functions
# ---------------------------------------------------------------------------


def read_input(txt_path: str) -> str:
    """Read and validate the input .txt file."""
    size = os.path.getsize(txt_path)
    if size > MAX_INPUT_BYTES:
        raise ValueError(f"Input file too large ({size} bytes, limit {MAX_INPUT_BYTES})")
    if size == 0:
        raise ValueError("Input file is empty")
    with open(txt_path, encoding="utf-8") as f:
        text = f.read()
    logger.info("Read input file (%d bytes)", size)
    return text


def extract_meeting_date(data: dict) -> str | None:
    """Extract a file-safe date string from parsed JSON data."""
    raw_date = data.get("meeting_date", "")
    if not raw_date:
        return None
    try:
        dt = datetime.strptime(raw_date, "%d/%m/%Y")
        return dt.strftime("%Y_%m_%d")
    except ValueError:
        pass
    return re.sub(r"[^a-zA-Z0-9]+", "_", raw_date).strip("_")


def extract_meeting_date_from_tex(tex: str) -> str | None:
    """Extract a file-safe date string from \\def\\todaydate{...} in LaTeX."""
    match = re.search(r"\\def\\todaydate\{([^}]+)\}", tex)
    if not match:
        return None

    raw_date = match.group(1).strip()
    try:
        dt = datetime.strptime(raw_date, "%d/%m/%Y")
        return dt.strftime("%Y_%m_%d")
    except ValueError:
        pass

    return re.sub(r"[^a-zA-Z0-9]+", "_", raw_date).strip("_")


def strip_markdown_fences(tex: str) -> str:
    """Remove markdown fences if the model wrapped direct-LaTeX output."""
    stripped = tex.strip()
    if stripped.startswith("```"):
        idx = stripped.find("\\documentclass")
        if idx != -1:
            stripped = stripped[idx:]
        if stripped.rstrip().endswith("```"):
            stripped = stripped.rstrip()[:-3].rstrip()
    return stripped


def _escape_latex_heading(text: str) -> str:
    """Escape heading text the same way renderer.py does for section names."""
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "#": r"\#",
    }
    for char, escaped in replacements.items():
        text = text.replace(char, escaped)
    return text


def validate_latex(tex: str, template_config: dict) -> tuple[bool, list[str]]:
    """Check direct-LaTeX output for basic structural validity."""
    failures = []

    if not tex.lstrip().startswith("\\documentclass"):
        failures.append("Does not start with \\documentclass")

    for marker in (
        "\\begin{document}",
        "\\makeminutestitle",
        "\\end{document}",
        "\\input{header/title_code.tex}",
    ):
        if marker not in tex:
            failures.append(f"Missing {marker}")

    if "% Generated with MinuteMaker" not in tex:
        failures.append("Missing generation comment")

    for section in template_config.get("mandatory_sections", []):
        heading = section.get("latex_heading") or _escape_latex_heading(section["name"])
        expected = rf"\section{{{heading}}}"
        if expected not in tex:
            failures.append(f"Missing mandatory section heading: {section['name']}")

    if failures:
        for failure in failures:
            logger.warning("Validation: %s", failure)
    else:
        logger.info("Validation passed (all checks OK)")

    return (len(failures) == 0, failures)


def inject_generation_comment(tex: str) -> str:
    """Inject the standard source comment after header/title_code.tex if missing."""
    marker = "\\input{header/title_code.tex}"
    comment = (
        f"\n\n% Generated with MinuteMaker on {datetime.now().strftime('%d/%m/%Y')}"
    )
    if "% Generated with MinuteMaker" not in tex and marker in tex:
        tex = tex.replace(marker, marker + comment, 1)
        logger.info("Injected missing generation comment")
    return tex


def create_output_bundle(output_dir: str, template_dir: str, date_str: str) -> tuple[str, str]:
    """Create a self-contained output bundle and copy template header assets into it."""
    bundle_name = f"minutes_{date_str}"
    bundle_dir = Path(output_dir) / bundle_name
    bundle_dir.mkdir(parents=True, exist_ok=True)

    header_src = Path(template_dir) / "header"
    if not header_src.exists():
        logger.error("Template header not found at %s", header_src)
        sys.exit(1)

    header_dst = bundle_dir / "header"
    if header_dst.is_symlink() or header_dst.exists():
        if header_dst.is_dir() and not header_dst.is_symlink():
            shutil.rmtree(header_dst)
        else:
            header_dst.unlink()

    shutil.copytree(header_src, header_dst)
    logger.info("Prepared output bundle: %s", bundle_dir)
    return (str(bundle_dir), bundle_name)


def write_tex(tex: str, output_dir: str, date_str: str) -> str:
    """Write .tex into a document bundle directory with atomic rename."""
    filename = f"minutes_{date_str}.tex"
    final_path = os.path.join(output_dir, filename)
    tmp_path = final_path + ".tmp"

    with open(tmp_path, "w", encoding="utf-8") as f:
        f.write(tex)
    os.rename(tmp_path, final_path)

    logger.info("Written: %s", final_path)
    return final_path


def compile_pdf(tex_path: str, output_dir: str) -> bool:
    """Run pdflatex twice (for cross-references). Returns True on success."""
    basename = os.path.basename(tex_path)
    cmd = ["pdflatex", "-interaction=nonstopmode", "-halt-on-error", basename]

    for pass_num in (1, 2):
        try:
            result = subprocess.run(
                cmd, cwd=output_dir, capture_output=True, text=True, timeout=120
            )
        except subprocess.TimeoutExpired:
            logger.error("pdflatex pass %d timed out", pass_num)
            return False

        if result.returncode != 0:
            lines = result.stdout.splitlines()
            tail = "\n".join(lines[-50:])
            logger.error("pdflatex pass %d failed:\n%s", pass_num, tail)
            log_file = tex_path.replace(".tex", ".log")
            logger.error("Full log at: %s", log_file)
            return False

        logger.info("pdflatex pass %d/%d complete", pass_num, 2)

    pdf_path = tex_path.replace(".tex", ".pdf")
    logger.info("Written: %s", pdf_path)
    return True


def cleanup_aux_files(tex_path: str) -> None:
    """Remove auxiliary files after successful compilation."""
    base = tex_path.rsplit(".", 1)[0]
    count = 0
    for ext in AUX_EXTENSIONS:
        path = base + ext
        if os.path.exists(path):
            os.remove(path)
            count += 1
    if count:
        logger.info("Cleaned up %d auxiliary file(s)", count)


def _process_via_direct_latex(
    raw_text: str,
    config: dict,
    template_config: dict,
    provider: LLMProvider,
    system_prompt: str,
) -> None:
    """Anthropic route: generate complete LaTeX directly in one pass."""
    logger.info("Single-pass LaTeX generation (Anthropic)")

    user_message = LATEX_USER_MESSAGE_TEMPLATE.format(
        today=datetime.now().strftime("%d/%m/%Y"),
        raw_text=raw_text,
    )
    tex = provider.generate(system_prompt, user_message, config)
    tex = strip_markdown_fences(tex)
    validate_latex(tex, template_config)
    tex = inject_generation_comment(tex)

    date_str = extract_meeting_date_from_tex(tex) or datetime.now().strftime("%Y_%m_%d")
    bundle_dir, _ = create_output_bundle(config["output_dir"], config["template_dir"], date_str)
    tex_path = write_tex(tex, bundle_dir, date_str)

    if compile_pdf(tex_path, bundle_dir):
        cleanup_aux_files(tex_path)
    else:
        logger.warning("PDF compilation failed — .tex file retained for manual review")


def _process_via_structured_json(
    raw_text: str,
    config: dict,
    template_config: dict,
    provider: LLMProvider,
    system_prompt: str,
) -> None:
    """OpenAI-compatible route: extract JSON, verify, polish, render, compile."""
    prompt_rules = load_prompt_rules(config)
    user_message = JSON_USER_MESSAGE_TEMPLATE.format(
        today=datetime.now().strftime("%d/%m/%Y"),
        raw_text=raw_text,
    )

    logger.info("Pass 1: extracting structured content")
    raw_response = provider.generate(system_prompt, user_message, config)

    try:
        data = parse_and_validate(raw_response)
    except ValueError as exc:
        logger.error("LLM output validation failed: %s", exc)
        debug_path = os.path.join(
            config["output_dir"],
            f"debug_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt",
        )
        with open(debug_path, "w", encoding="utf-8") as f:
            f.write(raw_response)
        logger.error("Raw LLM response saved to: %s", debug_path)
        raise

    logger.info("Pass 2: verifying completeness")
    data = verify_completeness(data, raw_text, provider, config, template_config)

    logger.info("Pass 3: polishing items")
    data = polish_items(data, provider, config, prompt_rules)

    tex = render_latex(data, template_config)
    date_str = extract_meeting_date(data) or datetime.now().strftime("%Y_%m_%d")
    bundle_dir, _ = create_output_bundle(config["output_dir"], config["template_dir"], date_str)
    tex_path = write_tex(tex, bundle_dir, date_str)

    if compile_pdf(tex_path, bundle_dir):
        cleanup_aux_files(tex_path)
    else:
        logger.warning("PDF compilation failed — .tex file retained for manual review")


def process_file(
    txt_path: str,
    config: dict,
    template_config: dict,
    system_prompts: dict[str, str],
) -> None:
    """Full pipeline dispatcher for provider-specific processing routes."""
    logger.info("Processing: %s", txt_path)

    raw = read_input(txt_path)
    provider_type = config.get("provider", "anthropic")
    provider = get_provider(config)

    # All LLM passes happen inside the server context so the local LLM
    # stays up for the full job, then shuts down when done.
    with ServerManager(config):
        if provider_type == "anthropic":
            _process_via_direct_latex(
                raw,
                config,
                template_config,
                provider,
                system_prompts["latex"],
            )
        elif provider_type == "openai_compatible":
            _process_via_structured_json(
                raw,
                config,
                template_config,
                provider,
                system_prompts["json"],
            )
        else:
            raise ValueError(f"Unsupported provider for processing route: {provider_type!r}")


# ---------------------------------------------------------------------------
# File watcher
# ---------------------------------------------------------------------------


class MinutesHandler(FileSystemEventHandler):
    """Watchdog handler that processes .txt files as they appear."""

    def __init__(self, config: dict, template_config: dict, system_prompts: dict[str, str]):
        super().__init__()
        self.config = config
        self.template_config = template_config
        self.system_prompts = system_prompts
        self._processed: dict[str, float] = {}

    def on_created(self, event):
        if event.is_directory:
            return
        if not event.src_path.endswith(".txt"):
            return

        path = event.src_path

        # Duplicate suppression (60s window)
        now = time.time()
        if path in self._processed and (now - self._processed[path]) < 60:
            logger.debug("Skipping duplicate event for %s", path)
            return

        logger.info("File detected: %s", os.path.basename(path))

        if not self._wait_for_stable(path):
            logger.warning("File never stabilised, skipping: %s", path)
            return

        self._processed[path] = time.time()

        try:
            process_file(path, self.config, self.template_config, self.system_prompts)
        except Exception:
            logger.exception("Failed to process %s", path)

    @staticmethod
    def _wait_for_stable(path: str, timeout: int = 30, interval: float = 1.0) -> bool:
        """Poll until the file size stops changing and is non-zero."""
        deadline = time.time() + timeout
        prev_size = -1
        while time.time() < deadline:
            try:
                size = os.path.getsize(path)
            except OSError:
                return False
            if size > 0 and size == prev_size:
                return True
            prev_size = size
            time.sleep(interval)
        return False
