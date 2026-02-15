# Looper Base Rules

Work in the current agent directory and keep its root clean.

## Critical Rules (Mandatory)

- Follow role boundaries from loaded instructions strictly; do not perform actions explicitly prohibited by your role.
- If a prompt asks to pass work to another looper and report back here, treat it as asynchronous by default.
  Submit the handoff and finish the current turn without blocking wait, unless synchronous mode was explicitly requested.
- Use synchronous waiting/relay only when the user or upstream agent explicitly asks to wait for the result and return it in the same turn/message.
- Never invent synchronous mode on your own. Do not add directives like `Mode: synchronous required` unless such mode is explicitly requested in the current prompt chain.
- Do not block a turn by polling another looper state (`*_Result.md`, repeated tail/read loops, sleep+recheck cycles, "still waiting" loops).
- Keep the final answer concise.

Use this structure:
- `Temp` for temporary and intermediate files.
- `Tools` for scripts and utilities that may be reused.
- `Output` for standalone final files for user/external handoff when destination is not explicitly provided.

If the user explicitly provides a destination path, use it.
If a final file is created "just in case" and no path is provided, place it in `Output`.


# Communication channels

- Луперы могут общаться с другими луперами через их каталоги Prompts
Create a normal prompt file in the target sender inbox (`<LooperFolder>/Prompts/Inbox/<SenderID>/Prompt_YYYY_MM_DD_HH_MM_SS_mmm.md`).
То есть, если агент-лупер хочет связаться с другим агентом-лупером - он должен положить файл в каталог.
Если каталога нет - создать его.
- Этот механизм является основным и обязательным каналом межлуперной коммуникации.
- Нельзя вносить прямые изменения в рабочие каталоги другого лупера (`Tools`, `Temp`, `Output`, `Plans` и т.п.), кроме записи prompt-файла в его `Prompts/Inbox/<SenderID>/`.
- Ответ между луперами также передается только новым `Prompt_*.md` в inbox отправителя запроса (по согласованному `Reply-To`).
- `*_Result.md` другого лупера не является межлуперным транспортом. Это внутренний run-log для наблюдения/диагностики.
