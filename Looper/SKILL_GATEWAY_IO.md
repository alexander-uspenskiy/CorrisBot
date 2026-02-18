# SKILL GATEWAY IO

Rules for agent communication with users through Gateway (file exchange and response formatting).

## VALID REPLY-TO BLOCK SIGNATURE (ANTI-FALSE-ROUTING)

Treat `Reply-To` as an active routing contract only when ALL conditions are true:
- There is a standalone line exactly `Reply-To:` (not inline text, not quoted example).
- In the same Reply-To block, there is at least one list item with key `- InboxPath:` (field order is not fixed).
- `InboxPath` value is concrete (not placeholders like `<...>`).
- The block is operational prompt content, not markdown code-fence example.

If any condition fails, treat `Reply-To` as non-operational text/example and do not reroute output.

## MANDATORY REPLY-TO HANDLING - STEPS TO FOLLOW

When a prompt contains a valid `Reply-To:` block, execute the following steps in order:

### STEP 1: Extract Reply-To data exactly
- `InboxPath`: copy exactly as provided.
- `SenderID`: copy exactly as provided (if present).
- `FilePattern`: supported value is only `Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md` (optional alnum suffix in marker). If missing, use this default.
- If `FilePattern` is present and differs from supported value, report `unsupported FilePattern` and stop.

### STEP 2: Prepare destination
- Verify directory exists: `<InboxPath>`.
- If directory does not exist: create it immediately.
- If creation fails: report delivery error in current turn and stop.

### STEP 3: Create response file
- Save response/report text to a local temporary file first.
- Create destination prompt via helper script (do not handcraft filename):
  - PowerShell: `py "$env:LOOPER_ROOT\create_prompt_file.py" create --inbox "<InboxPath>" --from-file "<LocalReportFile.md>"`
  - cmd: `py "%LOOPER_ROOT%\create_prompt_file.py" create --inbox "<InboxPath>" --from-file "<LocalReportFile.md>"`
- Script output path is the final `<InboxPath>\<Filename>` in standard supported pattern.

### STEP 4: Verify delivery
- Confirm the file exists after writing.
- If verification fails: retry once, then report error.

### STEP 5: Do not duplicate full response in current chat/result
- When `Reply-To` is present, delivery target is the file in `InboxPath`.
- In the current turn output, keep only a short confirmation/status (or explicit delivery error).
- Do not repeat the full delivered payload in current chat/result text.
- Exception: Talker relay YAML flow (`type: relay`) may keep verbatim relay payload in Result as required by `ROLE_TALKER`.

## REPLY-TO PERSISTENCE CONTRACT (MANDATORY)

- The first valid `Reply-To` block in a project/session establishes the active delivery contract for this peer.
- Active contract fields are: `InboxPath`, `SenderID` (if provided), and `FilePattern`.
- This contract remains in force for all subsequent prompts in the same peer/project context until a newer valid `Reply-To` block explicitly updates it.
- If a later prompt has no `Reply-To` block but an active contract exists, deliver using the active contract; do not switch to result-only replies.
- If a later prompt has no `Reply-To` block and no active contract is known, report explicit routing error and request a valid route instead of silent fallback.
- `Reply-To` persistence is mandatory for both reports and clarification questions sent back to the upstream looper.

## CRITICAL CONSTRAINTS

- `Reply-To` handling has no optional mode: if it is present, it is mandatory.
- Do not use `*_Result.md` as межлуперный транспорт вместо prompt-файла.
- Do not handcraft `Prompt_*.md` filenames in tool calls (`WriteFile`, `echo > ...`, etc.); use `create_prompt_file.py`.
- Do not include `@user`/mentions in files sent through `Reply-To` unless explicitly requested.
- Keep sender isolation: each sender must use its own isolated inbox subdirectory/context.

## Talker Relay Routing (Single-User Mode)

- This section applies to Talker looper runtime only.
- Relay destination source of truth is `Talker/Prompts/Inbox/routing_state.json` field `user_sender_id`.
- Talker relay delivery is allowed only when both conditions are true:
  - `user_sender_id` is set.
  - relay YAML `target` equals `user_sender_id`.
- If `user_sender_id` is unset or `target` mismatches:
  - log explicit protocol error;
  - do not deliver relay.
- Do not use heuristic routing, fallback targets, or auto-switch behavior.
- Operator control commands:
  - `/routing show`
  - `/routing set-user <SenderID>`
  - `/routing clear`

## Incoming User Files
- Gateway saves user-uploaded files into:
  - `Prompts/Inbox/<sender_id>/Files/`
- Current sender identity is provided in prompt context (for example, `Sender ID: ...`).
- Keep sender contexts isolated. Do not mix files or assumptions between different senders.
- While this agent is active context, it must support the same incoming-file flow as Talker.

## Sending Files Back Through Gateway
- When the user says "send it here", "upload", "share", "give me the file", etc., deliver the file via `DELIVER_FILE:`, not by copying into the working directory.
- To send a file back to the user, include explicit directive line(s):
  - `DELIVER_FILE: <path>`
- `<path>` may be absolute or relative to this agent working directory.
- For multiple files, include multiple `DELIVER_FILE:` lines.
- Do not rely on implicit path mentions in plain text.
- Do not include checksums unless explicitly requested.

