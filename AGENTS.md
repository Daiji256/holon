# Holon — Guidelines for AI Agents

- **Reserved Font Names**: Never include `IBM` or `Plex` in font names or OpenType records, per SIL OFL 1.1 restrictions on upstream IBM Plex fonts.
- **License Text**: Never generate or paraphrase license texts from AI memory. Always fetch verbatim from official sources (e.g. SPDX).
- **Build & Test**: Run all scripts with [uv](https://docs.astral.sh/uv/) (`uv run build.py`, `uv run test.py`). Ensure tests pass before completing tasks.
- **Lint & Format**: Run `uvx ruff check .` and `uvx ruff format .` after modifying Python files.
