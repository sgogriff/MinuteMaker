"""Render structured JSON minutes data into a complete LaTeX document."""

import logging
from datetime import datetime

logger = logging.getLogger("minutemaker")

# Characters that must be escaped in LaTeX text (but NOT inside LaTeX commands)
_LATEX_SPECIAL = {
    "&": r"\&",
    "%": r"\%",
    "#": r"\#",
}


def _escape_latex_heading(text: str) -> str:
    """Escape LaTeX special characters in a section heading.

    Only escapes &, %, # — does NOT touch backslashes since the heading
    may legitimately contain LaTeX commands from the template.
    """
    for char, escaped in _LATEX_SPECIAL.items():
        text = text.replace(char, escaped)
    return text


# Base LaTeX packages included in every document
BASE_PACKAGES = [
    r"\usepackage[utf8]{inputenc}",
    r"\usepackage[english]{babel}",
    r"\usepackage[document]{ragged2e}",
    r"\usepackage[a4paper,top=2cm,bottom=2cm,left=2cm,right=2cm,marginparwidth=1.5cm]{geometry}",
    r"\usepackage{placeins}",
    r"\usepackage{pdfpages}",
    r"\usepackage{multirow}",
    r"\usepackage[export]{adjustbox}",
    r"\usepackage{hyperref}",
]


def _build_preamble(template_config: dict) -> str:
    """Build the LaTeX preamble from template config."""
    lines = [r"\documentclass[11pt]{article}"]
    lines.extend(BASE_PACKAGES)

    # Extra packages from template
    for pkg in template_config.get("extra_packages", []):
        lines.append(pkg)

    lines.append("")
    lines.append(r"\input{header/title_code.tex}")
    lines.append("")

    date_str = datetime.now().strftime("%d/%m/%Y")
    lines.append(f"% Generated with MinuteMaker on {date_str}")

    return "\n".join(lines)


def _build_metadata(data: dict) -> str:
    """Build the \\def metadata block."""
    lines = [
        "",
        rf"\def\todaydate{{{data['meeting_date']}}}",
        rf"\def\chair{{{data['chair']}}}",
        rf"\def\secretary{{{data['secretary']}}}",
    ]
    return "\n".join(lines)


def _section_heading(section_name: str, template_config: dict) -> str:
    """Return the LaTeX \\section{} line for a section, using latex_heading override if defined."""
    # Check mandatory and optional sections for a latex_heading override
    all_sections = template_config.get("mandatory_sections", []) + template_config.get(
        "optional_sections", []
    )
    for sec_def in all_sections:
        if sec_def["name"] == section_name and "latex_heading" in sec_def:
            return rf"\section{{{sec_def['latex_heading']}}}"

    return rf"\section{{{_escape_latex_heading(section_name)}}}"


def _render_section(section: dict, template_config: dict) -> str:
    """Render a single section as LaTeX."""
    lines = []
    lines.append(_section_heading(section["name"], template_config))
    lines.append("")
    lines.append(r"\begin{itemize}")

    items = section.get("items", [])
    if not items:
        lines.append(r"    \item Nothing to report.")
    else:
        for item in items:
            lines.append(rf"    \item {item}")

    lines.append(r"\end{itemize}")
    return "\n".join(lines)


def _get_section_order(template_config: dict) -> list[str]:
    """Get the ordered list of all section names (mandatory + optional insertion points)."""
    mandatory = [s["name"] for s in template_config.get("mandatory_sections", [])]
    optional = [s["name"] for s in template_config.get("optional_sections", [])]

    # Build the section order from the template's section_order if provided,
    # otherwise mandatory sections in order
    return mandatory, optional


def render_latex(data: dict, template_config: dict) -> str:
    """Render a complete LaTeX document from parsed JSON data and template config.

    Args:
        data: Parsed and validated JSON from the LLM (see schema.py)
        template_config: Loaded template.yaml configuration

    Returns:
        Complete LaTeX document as a string
    """
    parts = []

    # Preamble
    parts.append(_build_preamble(template_config))

    # Metadata
    parts.append(_build_metadata(data))

    # Document opening
    parts.append("")
    parts.append(r"\begin{document}")
    parts.append(r"\makeminutestitle")

    # Build section lookup from LLM data
    section_lookup = {}
    for sec in data.get("sections", []):
        section_lookup[sec["name"]] = sec
    for sec in data.get("optional_sections", []):
        section_lookup[sec["name"]] = sec

    mandatory_names, optional_names = _get_section_order(template_config)

    # Figure out where optional sections should be inserted.
    # The template's section_order field defines the full order including
    # optional sections. If not present, we use the order from template.yaml
    # where optional sections are listed separately and inserted after the
    # last mandatory section before them.
    section_order = template_config.get("section_order", None)

    if section_order:
        # Explicit full ordering provided
        ordered_names = section_order
    else:
        # Default: mandatory sections in order, optional sections not inserted
        # unless they appear in the LLM output. We insert them in their
        # defined order after the mandatory sections but before the last few.
        # For Liverpool: optional sections go between specific mandatory ones.
        # We handle this by using the template's insertion_points if defined,
        # otherwise appending optional sections at the end before the last section.
        ordered_names = list(mandatory_names)

    # Render mandatory sections
    rendered_sections = []
    for name in ordered_names:
        sec_data = section_lookup.get(name)
        if sec_data:
            rendered_sections.append(_render_section(sec_data, template_config))
        else:
            # Mandatory section not in LLM output — render with "Nothing to report"
            rendered_sections.append(
                _render_section({"name": name, "items": []}, template_config)
            )

    # Insert optional sections if they have content
    # Determine insertion points from template config
    insertion_points = template_config.get("optional_section_positions", {})
    optional_to_insert = []
    for opt_name in optional_names:
        if opt_name in section_lookup:
            optional_to_insert.append((opt_name, section_lookup[opt_name]))

    if optional_to_insert and not section_order:
        # Insert optional sections at their specified positions
        for opt_name, opt_data in reversed(optional_to_insert):
            after = insertion_points.get(opt_name)
            if after:
                # Find the index of the section to insert after
                try:
                    idx = ordered_names.index(after)
                    rendered_sections.insert(
                        idx + 1,
                        _render_section(opt_data, template_config),
                    )
                    ordered_names.insert(idx + 1, opt_name)
                except ValueError:
                    # Fallback: append before last section
                    rendered_sections.insert(
                        -1, _render_section(opt_data, template_config)
                    )
            else:
                # No position specified — append before last section
                rendered_sections.insert(
                    -1, _render_section(opt_data, template_config)
                )

    parts.append("")
    parts.append("\n\n".join(rendered_sections))

    # Document closing
    parts.append("")
    parts.append(r"\end{document}")

    tex = "\n".join(parts)
    logger.info("Rendered LaTeX document (%d chars)", len(tex))
    return tex
