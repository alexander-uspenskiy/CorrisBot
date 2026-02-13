## Project: Agent <-> Gateway Protocol

This repo contains a “gateway” process that connects a chat channel (Telegram today, potentially Discord/WhatsApp/etc. later)
to a Talker looper workflow (file-based prompt/result exchange).

Current runtime model:
- Gateway writes prompt files to Talker inbox: `C:\CorrisBot\Talker\Prompts\Inbox\<sender_id>\Prompt_<timestamp>.md`
- Looper processes prompts and writes results to `*_Result.md`
- Gateway streams selected looper events back to Telegram
- Gateway saves user-uploaded attachments to `C:\CorrisBot\Talker\Prompts\Inbox\<sender_id>\Files\`
- After saving an attachment, gateway sends an explicit system event prompt to Talker, so Talker is aware of the new file

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
- File delivery from agent replies is explicit-only: without `DELIVER_FILE`, gateway will not auto-send files.

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

### Temporary files
For intermediate files, scripts, and other temporary artifacts, use the subdirectory `_Temp\`:
- Create the directory if it does not exist: `mkdir _Temp`
- Place temporary scripts, working files, and intermediate outputs there
- **Important:** `_Temp\` is listed in `.gitignore`, so some agents may automatically ignore files in this directory
- Do not use `_Temp\` for files you intend to deliver to the user; use `DELIVER_FILE:` with a different path instead

### Notes
- The gateway is transport/orchestration glue; business logic should stay in Talker prompts/instructions.
- The gateway is responsible for delivery (Telegram/Discord/etc.) and file ingestion from users.
- The looper/agent side is responsible for deciding what to do with uploaded files and when to respond.
