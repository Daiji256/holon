---
trigger: always_on
---

# Licensing and Commit Guidelines for Holon

1. **Licenses Must Never Be Hand-Written**:
   - Never generate SIL OFL 1.1 or any license text from AI memory.
   - Always copy/download directly from trusted sources (e.g. SPDX: https://spdx.org/licenses/OFL-1.1.txt or upstream repo https://github.com/IBM/plex).

2. **Commit Restrictions**:
   - Always push immediately after creating a commit (`git push`).
   - Do NOT commit generated font binaries (`*.ttf`, `*.otf`, etc.) until the project is completely ready and finalized.
   - Do NOT commit `OFL.txt` until the fonts are committed together.
   - `tmp/` is ignored by Git and can be freely used for scratch/temporary processing.

3. **Execution with `uv`**:
   - Use Python scripts formatted with PEP 723 inline script metadata runnable via `uv run`.
   - Refer to `/Users/daiji/src/makumi-fonts` and `/Users/daiji/src/yaku-kumi-fonts` for implementation patterns.
