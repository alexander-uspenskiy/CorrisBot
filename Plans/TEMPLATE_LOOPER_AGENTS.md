# Looper Base Rules

Work in the current agent directory and keep its root clean.

Use this structure:
- `Temp` for temporary and intermediate files.
- `Tools` for scripts and utilities that may be reused.
- `Output` for standalone final files for user/external handoff when destination is not explicitly provided.

If the user explicitly provides a destination path, use it.
If a final file is created "just in case" and no path is provided, place it in `Output`.
