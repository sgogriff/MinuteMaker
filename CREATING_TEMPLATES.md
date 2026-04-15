# Creating a Custom Template

MinuteMaker uses templates to control the structure and formatting of your meeting minutes. Each template is a directory under `templates/` containing a few files that define how your minutes look.

## Template directory structure

```
templates/
  your-template/
    template.yaml          # Required — sections, metadata, formatting
    prompt_rules.md        # Optional — extra instructions for the LLM
    TEMPLATE_SPEC.md       # Required — full description of the output format
    header/
      title_code.tex       # Required — LaTeX macros for the title page
      logo.png             # Optional — your organisation's logo
```

## Step-by-step: creating a template

### 1. Copy the default template

```bash
cp -r templates/default templates/my-department
```

### 2. Edit `template.yaml`

This file defines the structure of your minutes. Here's an annotated example:

```yaml
# Display name for your template
name: "Physics Department Weekly Meeting"
short_name: "Physics Dept"

# Date format (Python strftime)
date_format: "%d/%m/%Y"

# Mandatory sections — always present, in this exact order.
# If the meeting notes have nothing for a section, it shows "Nothing to report."
mandatory_sections:
  - name: "Announcements"
  - name: "Research Updates"
  - name: "Teaching & Admin"
  - name: "Equipment & Facilities"
  - name: "Any Other Business"
  - name: "Next Meeting"

# Optional sections — only included when the notes contain relevant content.
# Omit this key (or use []) if you have no optional sections.
optional_sections:
  - name: "Upcoming Seminars"
  - name: "Health & Safety"

# Where optional sections should appear in the document.
# Format: "Optional Section Name": "Insert After This Mandatory Section"
optional_section_positions:
  "Upcoming Seminars": "Research Updates"
  "Health & Safety": "Equipment & Facilities"

# LaTeX convenience macros — shortcuts for frequently used terms.
# These are defined in your header/title_code.tex and the LLM is told to use them.
# Omit or use {} if you don't need any.
convenience_macros:
  dept: "Department of Physics"

# Extra LaTeX packages beyond the standard set.
# The base packages (inputenc, babel, geometry, hyperref, etc.) are always included.
# Omit or use [] if you don't need extra packages.
extra_packages:
  - "\\usepackage[version=4]{mhchem}"   # for chemical notation
```

**Section names:**
- Use the name as you want it to appear in the document heading
- Special characters like `&` are escaped automatically
- For custom LaTeX headings (e.g., superscripts), add a `latex_heading` field:

```yaml
mandatory_sections:
  - name: "2nd Floor Lab"
    latex_heading: "\\texorpdfstring{2\\textsuperscript{nd}}{2nd} Floor Lab"
```

### 3. Edit `TEMPLATE_SPEC.md`

This file is fed to the LLM as context. It should describe what each section is for so the LLM can correctly categorise messy meeting notes. Write it in plain English:

```markdown
# Meeting Minutes Template Specification

## Sections

1. **Announcements** — department-wide news, policy changes, deadlines
2. **Research Updates** — progress on experiments, publications, grants
3. **Teaching & Admin** — course-related items, timetabling, admin tasks
4. **Equipment & Facilities** — lab equipment, building issues, IT
5. **Any Other Business** — anything not covered above
6. **Next Meeting** — date, chair, secretary for the next meeting

## Guidelines
- Write in third person, past tense
- Bold deadlines and action items
- Each bullet should be self-contained
```

### 4. Edit `prompt_rules.md` (optional)

If your domain has specific formatting needs, add them here. These are additional instructions appended to the LLM's system prompt:

```markdown
# Department-specific rules

- Use `\ce{}` notation for chemical formulae (e.g., `\ce{H2O}`)
- Use the `\dept` macro when referring to the department
- Mark overdue action items with `\textbf{OVERDUE:}`
```

If you don't need extra rules, you can leave this file empty or delete it.

### 5. Customise `header/title_code.tex`

This LaTeX file defines the `\makeminutestitle` command and any convenience macros. It's included in every generated document via `\input{header/title_code.tex}`.

**Minimal example (no logo):**

```latex
\newcommand{\makeminutestitle}{
    \center
    \vspace{10pt}
    \textbf{\bfseries \Large Physics Department Meeting Minutes}\\ [0.5cm]
    {\large Meeting Date: \todaydate }
    \noindent\rule{\textwidth}{1pt}
    \begin{flushleft}
    Chair: \chair\newline
    Secretary: \secretary\newline
    \vspace{-4pt}
    \noindent\rule{\textwidth}{1pt}
    \end{flushleft}
    \justify
}

\hypersetup{
    colorlinks=true,
    linkcolor=blue,
    urlcolor=red,
    pdftitle={Physics Dept Minutes},
    pdfpagemode=FullScreen
}
```

**With a logo:**

Add your logo file to `header/` (e.g., `header/logo.png`), then:

```latex
\newcommand{\makeminutestitle}{
    \center
    \includegraphics[width=0.4\textwidth]{header/logo.png}\\
    \vspace{10pt}
    ...
```

**Adding links (schedule, resources, etc.):**

```latex
\href{https://your-schedule-url}{Meeting Schedule}
\hspace{10pt}
\href{https://your-resources-url}{Resources}
```

**Adding convenience macros:**

```latex
\def\dept{Department of Physics }
```

These must match what you declared in `template.yaml` under `convenience_macros`.

### 6. Use your template

Update `config.yaml`:

```yaml
template: my-department
```

Or pass it on the command line:

```bash
python minutemaker.py --template my-department --once notes.txt
```

## Tips

- **Start simple.** The default template works out of the box. Add complexity only as needed.
- **Test with real notes.** Drop an actual meeting notes file in and check the output before deploying.
- **Section names matter.** The LLM uses the `TEMPLATE_SPEC.md` to understand what goes where. Clear, descriptive section names improve accuracy.
- **The generated output bundle includes `header/`.** Keep `\input{header/title_code.tex}` and `header/logo.png` style paths in your LaTeX, because MinuteMaker copies the template header assets into each output folder automatically.
- **OpenAI-compatible models use JSON internally.** You generally don't need to teach the model about full LaTeX formatting in `prompt_rules.md`; use that file for domain-specific content rules (terminology, macros to use in text, etc.).
