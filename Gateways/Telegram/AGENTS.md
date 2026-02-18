## Project: Agent <-> Gateway Protocol

This repo contains a "gateway" process that connects a chat channel (Telegram today, potentially Discord/WhatsApp/etc. later)
to a Talker looper workflow (file-based prompt/result exchange).

Current runtime model:
- Gateway writes prompt files to Talker inbox: `<TALKER_ROOT>\Prompts\Inbox\<sender_id>\Prompt_<timestamp>.md`
- Looper processes prompts and writes results to `*_Result.md`
- Gateway streams selected looper events back to Telegram
- Gateway saves user-uploaded attachments to `<TALKER_ROOT>\Prompts\Inbox\<sender_id>\Files\`
- After saving an attachment, gateway sends an explicit system event prompt to Talker, so Talker is aware of the new file
- `TALKER_ROOT` is provided by launcher (`$env:TALKER_ROOT` in PowerShell, `%TALKER_ROOT%` in cmd)

The gateway can parse special directives embedded in the agent's natural language replies.

### DELIVER_FILE protocol (parsed by gateway)

Agents may include directive lines in their replies to request file delivery to the user:

DELIVER_FILE: <path>

- `<path>` may be absolute or relative to the agent's WORKDIR.
- The gateway will attempt to send that file back to the user through the current channel.
- Multiple files are supported by repeating the directive.
- File delivery is explicit-only: without `DELIVER_FILE`, gateway will not auto-send files.

Examples:

Here is your audio file:
DELIVER_FILE: C:\Temp\KLF - Last Train to Trancentral.mp3

I generated 2 artifacts:
DELIVER_FILE: exports\report.csv
DELIVER_FILE: exports\plot.png

### What gateway strips from replies
When delivering files to the user (via DELIVER_FILE), the gateway strips SHA256 hashes and other checksums from the accompanying text, as users practically never verify them.

### Notes
- The gateway is transport/orchestration glue; business logic should stay in Talker prompts/instructions.
- The gateway is responsible for delivery (Telegram/Discord/etc.) and file ingestion from users.
- The looper/agent side is responsible for deciding what to do with uploaded files and when to respond.
- Agent-facing rules for file exchange (DELIVER_FILE syntax, incoming files path, response style) are defined in `Looper/SKILL_GATEWAY_IO.md` and loaded through each agent's AGENTS.md Read chain.
