# Holon — Guidelines for AI Agents and Contributors

## Project Overview
- **Typefaces**:
  - **Holon Sans**: Proportional sans-serif with dual-scaling (CJK 0.97x, Latin 1.02x), JIS X 4051 spacing (`chws`/`vchw`), Italic + 11° oblique CJK, and Variable Fonts (`wght` 100..700, `GRAD` -100..+100).
  - **Holon Mono**: 2:1 duospace programming font (550 / 1100 UPM), continuous box-drawing glyphs, Italic + 9° oblique CJK, and Variable Fonts (`wght` 100..700, `GRAD` -100..+100).
- **Upstream**: Derived from IBM Plex fonts. Font names and internal OpenType records must strictly exclude `IBM` and `Plex` to comply with SIL OFL 1.1 Reserved Font Name restrictions.

## Development Rules
1. **License Text**: Never generate or paraphrase license texts from AI memory. Always fetch verbatim from official sources (e.g. SPDX).
2. **Build & Test**: Run all scripts with [uv](https://docs.astral.sh/uv/) (`uv run build.py`, `uv run test.py`). Ensure tests pass before completing tasks.
3. **Git Operations**: Only commit or push when explicitly instructed by the maintainer. Keep generated font binaries and `tmp/` out of commits during regular development.
