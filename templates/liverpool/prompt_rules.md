# Liverpool Nuclear Physics Group — additional prompt rules

These rules are specific to the University of Liverpool Nuclear Physics Group
meeting minutes and supplement the base rules.

## Isotope and chemical notation

Use the `mhchem` package `\ce` command for all isotope and chemical notation.
For example: `\ce{^{192}Pb}`, `\ce{^{40}Ca}`, `\ce{^{Nat}W}`.
Include the LaTeX markup directly in the JSON item strings.

## Convenience macros

Use these macros wherever the corresponding facilities are referenced.
Include them directly in the JSON item strings:
- `\jv` for Jyväskylä
- `\LNL` for Legnaro
- `\GSI` for GSI Helmholtzzentrum für Schwerionenforschung

## Tone and style

- Third person, past tense for reporting what happened.
- Concise but complete — each bullet should be self-contained.
- Congratulatory tone for achievements ("Congratulations to X").
- Deadlines and action items should use `\textbf{}` (include the LaTeX markup in the JSON).
- Professional but approachable register.

## Chair and Secretary

Populate the "chair" and "secretary" fields ONLY if the raw notes explicitly
state who chaired or minuted the meeting. Do NOT infer or guess these names
from agenda content or discussion points. If the information is not directly
stated, use "Check Meeting Schedule" as the placeholder value. The same rule
applies to the Chair and Secretary entries in the Next Meeting section.
