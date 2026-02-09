## Project: Agent <-> Gateway Protocol

This repo contains a “gateway” process that connects a chat channel (Telegram today, potentially Discord/WhatsApp/etc. later)
to a local CLI agent (Codex by default). The agent runs on the local machine and can create/read files locally.

Important: When the user says “send it here”, “upload”, “share”, “give me the file”, etc. they mean:
**deliver the file back to the user via the gateway channel**, not “copy into the working directory”.

The gateway can parse special directives embedded in the agent’s natural language replies.

### Delivery directives (parsed by gateway)

You may write any normal explanation text.  
To request the gateway to deliver a file to the user, include a directive line in the message:

DELIVER_FILE: <path>

- `<path>` may be absolute or relative to the current WORKDIR.
- The gateway will attempt to send that file back to the user through the current channel.
- You can include multiple files by repeating the directive multiple times.

Examples:

Here is your audio file:
DELIVER_FILE: C:\CorrisBot\KLF - Last Train to Trancentral.mp3

I generated 2 artifacts:
DELIVER_FILE: exports\report.csv
DELIVER_FILE: exports\plot.png

### Optional helpful info (not required, but nice)
If relevant, you may also include:
- file size
- short note about what the file is

### What NOT to include
When delivering files to the user (via DELIVER_FILE), **do not** include SHA256 hashes or other checksums in the accompanying text. Users practically never verify them, and it clutters the message.

### Notes
- The agent is allowed to use full local capabilities (read/write/run) unless otherwise restricted by config.
- The gateway is responsible for the actual delivery (Telegram/Discord/etc.) and for any later restrictions/guardrails.
