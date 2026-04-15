# Minutes Template Specification

This document describes the structure and formatting conventions for the University of Liverpool Nuclear Physics Group meeting minutes. It is intended as the authoritative reference for any script or API call that generates LaTeX minutes from raw text input.

## Document Structure

Every minutes document follows a fixed structure. The LaTeX preamble and header are always the same; only the metadata and section content change between meetings.

### Preamble (fixed)

```latex
\documentclass[11pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[english]{babel}
\usepackage[document]{ragged2e}
\usepackage[a4paper,top=2cm,bottom=2cm,left=2cm,right=2cm,marginparwidth=1.5cm]{geometry}
\usepackage{placeins}
\usepackage{pdfpages}
\usepackage{multirow}
\usepackage[export]{adjustbox}
\usepackage{hyperref}
\usepackage[version=4]{mhchem}

\input{header/title_code.tex}

% Generated with MinuteMaker on DATE
```

The `\input{header/title_code.tex}` file reference assumes the generated `.tex` file is in the same directory as the header folder. The header file defines `\makeminutestitle`, hyperlink styling, and convenience macros. It must not be modified per-meeting.

**Important**: The first comment after `\input{header/title_code.tex}` must include the generation date. The date should be in the same format as `\todaydate` (e.g., `17/5/2025`). This comment appears only in the `.tex` source and will not be visible in the compiled PDF.

**Note on paths**: When generating minutes, the output `.tex` file should be placed in a location where `header/title_code.tex` is accessible via the relative path `header/title_code.tex`. This is typically in the same directory where the header subfolder exists.

### Per-Meeting Metadata

Three `\def` commands set the meeting-specific metadata. These appear before `\begin{document}`:

```latex
\def\todaydate{DD/MM/YYYY}
\def\chair{Name}
\def\secretary{Name}
```

Date format has varied historically (e.g. `28th January 2025`, `24 Jan 2023`, `17/5/2025`, `18/06/2024`). The preferred format going forward is `DD/MM/YYYY`.

**Chair and Secretary fields**: Populate `\def\chair{}` and `\def\secretary{}` only if the raw notes explicitly state who chaired or minuted the meeting. If no such information is present in the notes, use the placeholder value `Check Meeting Schedule`. Do not infer or guess these names from the content of agenda items or discussion points — they must be directly stated. The same rule applies to the Chair and Secretary entries in the **Next Meeting** section.

### Document Opening

```latex
\begin{document}
\makeminutestitle
```

## Sections (in order)

The minutes use a fixed sequence of `\section{}` headings. Every section **must** appear, even if the content is just "Nothing to report." The sections, in order, are:

1. **Department Updates**
2. **Postgraduate Issues**
3. **Computing Issues \& Online Resources**
4. **2nd Floor Lab News** — uses special markup: `\section{\texorpdfstring{2\textsuperscript{nd}}{2nd} Floor Lab News}`
5. **Experiments \& Conferences**
6. **Upcoming Vivas** — *optional, newer addition (appears from late 2024 onward); omit if no viva news*
7. **Group Successes (Papers/Prizes/Projects)**
8. **Journal Club**
9. **Outreach \& Community Engagement** — *optional, newer addition; omit if no outreach news*
10. **Any Other Business**
11. **Talks**
12. **Next Meeting**

### Section Content Format

Each section's content should be wrapped in an `itemize` environment:

```latex
\section{Department Updates}

\begin{itemize}
    \item First point here.
    \item Second point here.
\end{itemize}
```

If a section has nothing to report:

```latex
\begin{itemize}
    \item Nothing to report.
\end{itemize}
```

### Next Meeting Section

This section always has exactly three items:

```latex
\section{Next Meeting}
\begin{itemize}
    \item Date: DD/MM/YYYY
    \item Chair: Name
    \item Secretary: Name
\end{itemize}
```

## LaTeX Formatting Conventions

### Isotopes and Chemical Notation

Use the `mhchem` package `\ce` command:

```latex
\ce{^{192}Pb}
\ce{^{40}Ca}
\ce{^{Nat}W}
```

### Hyperlinks

```latex
\href{https://example.com}{Display text}
\url{https://example.com}
```

### Bold / Emphasis

Use `\textbf{text}` for important deadlines or emphasis.

### Special Characters

- Ampersands: `\&`
- Percent: `\%`
- Hash: `\#`

### Convenience Macros (defined in title_code.tex)

| Macro | Expands to |
|-------|-----------|
| `\jv` | Jyväskylä |
| `\LNL` | Legnaro |
| `\GSI` | GSI Helmholtzzentrum für Schwerionenforschung |

### Line Breaks

Prefer `\item` inside `itemize` environments over `\newline \\` for separating points. Older minutes sometimes used bare dashes (`-`) and `\newline` instead of `\begin{itemize}` — this is the old style and should not be used.

### Verbatim Code

For terminal commands or code snippets, use `\begin{verbatim}...\end{verbatim}` inside an `\item`.

## Tone and Style

- Third person, past tense for reporting what happened ("Cameron gave a talk", not "I gave a talk").
- Concise but complete — each bullet should be self-contained.
- Congratulatory tone for achievements ("Congratulations to X").
- Deadlines and action items should be in **bold**.
- Professional but approachable register — occasional humour is fine (e.g. "Please ensure appropriate participation" for Pancake Day).

## Document Closing

```latex
\end{document}
```

No content should appear after `\end{document}`.
