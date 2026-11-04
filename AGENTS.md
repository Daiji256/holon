# Holon Sans — Agent Instructions and Project Guidelines

## 1. Project Overview & Background
- **Project Name**: Holon Sans
- **Base Typeface**: IBM Plex Sans & IBM Plex Sans JP (upstream: https://github.com/IBM/plex)
- **Goal**: Create a high-quality, comprehensive font targeting English and Japanese (with room for future multilingual extensions).
- **Architecture**:
  - Independent custom font build (Approach C).
  - Selected glyph merging between IBM Plex Sans (Latin/symbols) and IBM Plex Sans JP (Japanese kana, kanji, etc.).
  - Glyph scaling and visual balance adjustment.
  - Contextual half-width spacing (`chws` / East Asian spacing) support for Japanese punctuation.
  - Italic and Variable font support.
  - Font name and internal OpenType table records must strictly exclude `IBM` and `Plex` to avoid trademark conflicts and comply with SIL OFL 1.1 requirements.
- **Background Context**: See discussion in conversation `03788c3e-e954-436e-b19a-ba96f69bc65f`.

## 2. Mandatory Rules & Policies

### A. Strict License Handling Rule
- **NEVER** write, reconstruct, or paraphrase license texts (such as SIL OFL 1.1) from memory or LLM weights.
- All license files and headers **MUST** be fetched/copied verbatim from official, authoritative sources:
  - SPDX: https://spdx.org/licenses/OFL-1.1.html (or canonical raw text)
  - Upstream official repository: https://github.com/IBM/plex
- In the past, AI handwriting caused discrepancies in license texts. Verbatim copying from source is mandatory.

### B. Commit & File Management Policy
- **Git Operations**:
  - Whenever a commit is made, push to the remote repository immediately (`git push`).
- **Temporary directory (`tmp/`)**:
  - Ignored in Git (`.gitignore`).
  - Freely used for intermediate downloads, font inspection dumps, and scratch files.
- **Generated font binaries (`*.ttf`, `*.otf`, `*.woff2`)**:
  - Must **NOT** be committed until the font is completely finished and validated.
  - Ignored in Git during development.
- **`OFL.txt`**:
  - Must **NOT** be committed standalone during development.
  - It will be committed simultaneously with the finalized font files.

### C. Build System & Scripting
- All build scripts must use Python with **PEP 723 inline script metadata** executed via `uv run` (e.g. `uv run build.py`).
- Reference user's existing font projects for patterns and structure:
  - `https://github.com/Daiji256/yaku-kumi-fonts` (local: `/Users/daiji/src/yaku-kumi-fonts`)
  - `https://github.com/Daiji256/makumi-fonts` (local: `/Users/daiji/src/makumi-fonts`)
- Primary libraries: `fonttools`, `chws-tool` (`east_asian_spacing`), etc.

## 3. Communication & Language
- Agent documentation (`AGENTS.md`, `.agents/` rules, etc.) is written in English for the agent's reference.
- Direct responses to the user should be in Japanese, concise, clear, and proactive.
