# Holon — Agent Instructions and Project Guidelines

## 1. Project Overview & Background
- **Project Name**: Holon Sans & Holon Mono
- **Base Typeface**: IBM Plex Sans, IBM Plex Mono & IBM Plex Sans JP (upstream: https://github.com/IBM/plex)
- **Goal**: Create high-quality, comprehensive font families targeting English and Japanese (with room for future multilingual extensions):
  - **Holon Sans**: Dual-scaled proportional sans-serif (Japanese CJK 0.97x, Latin/symbols 1.02x) with contextual half-width spacing (`chws` / `vchw`), authentic Italic + 11.0° oblique CJK, and 2-file Variable Fonts (`wght` 100..700, `GRAD` -100..+100).
  - **Holon Mono**: Strict 2:1 duospace programming monospace font (550 UPM halfwidth / 1100 UPM fullwidth, CJK 0.97x, authentic Italic + 9.0° oblique CJK, box-drawing alignment, and 2-file Variable Fonts (`wght` 100..700, `GRAD` -100..+100)).
- **Compliance**:
  - Font name and internal OpenType table records must strictly exclude `IBM` and `Plex` to avoid trademark conflicts and comply with SIL OFL 1.1 requirements.

## 2. Mandatory Rules & Policies

### A. Strict License Handling Rule
- **NEVER** write, reconstruct, or paraphrase license texts (such as SIL OFL 1.1) from memory or LLM weights.
- All license files and headers **MUST** be fetched/copied verbatim from official, authoritative sources:
  - SPDX: https://spdx.org/licenses/OFL-1.1.html (or canonical raw text)
  - Upstream official repository: https://github.com/IBM/plex
- Verbatim copying from source is mandatory.

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
- All build and test scripts must use Python with **PEP 723 inline script metadata** executed via `uv run` (`uv run build.py`, `uv run test.py`).
- Upstream font data must be pinned to immutable Git commit hashes or release tags with SHA-256 verification.
- Primary libraries: `fonttools`, `chws-tool` (`east_asian_spacing`), `ufo2ft`, `glyphsLib`, `uharfbuzz`, `freetype-py`, `pillow`.

## 3. Communication & Language
- Agent documentation (`AGENTS.md`, `.agents/` rules, etc.) is written in English for the agent's reference.
- Direct responses to the user should be in Japanese, concise, clear, and proactive.

