<!-- TEMPLATE-ONLY:
`## CRITICAL` is present in the template so the model is forced to expand the
`Read:` chain.
In the final assembled `AGENTS.md`, this block must be removed by the assembler
(`Looper/assemble_agents.py`) so it does not trigger unnecessary read_file actions. -->
## CRITICAL
- Before any action, read this file fully.
- Every `Read:` link in this file is mandatory.
- Follow the full nested `Read:` chain recursively before processing the prompt.

# Looper Base Rules
- Read: `../Looper/ROLE_LOOPER_BASE.md`

# ROLE TALKER
- Read: `./ROLE_TALKER.md`
