#!/usr/bin/env python3
# tg_codex_gateway.py
# Telegram -> Agent CLI gateway (default: Codex CLI)
#
# Behavior:
#   - Echo ALL incoming text messages to the console.
#   - Bot commands (start with /) are handled by this script.
#   - Any non-command text is forwarded to the CURRENT agent (default: "codex").
#
# Agent execution (Codex):
#   Uses Codex CLI non-interactive mode: `codex exec "<prompt>"`
#   (Official docs: "Use `codex exec` to run Codex in scripts and CI".)
#
# Setup:
#   1) Create a bot with @BotFather and get TELEGRAM_BOT_TOKEN
#   2) Discover your chat_id: set ALLOWED_CHAT_ID=0, run script, send /id
#   3) Set env vars:
#        - TELEGRAM_BOT_TOKEN
#        - ALLOWED_CHAT_ID   (your numeric chat_id)
#   4) Ensure Codex CLI is installed and available (try: codex --help)
#
# Run (PowerShell example):
#   $env:TELEGRAM_BOT_TOKEN = "..."
#   $env:ALLOWED_CHAT_ID = "123456789"
#   py tg_codex_gateway.py
#
# Telegram commands:
#   /id                 -> show your chat_id
#   /agent              -> show current agent name
#   /setagent <name>    -> set current agent (default supported: codex)
#   /run <text>         -> explicitly run text via current agent (same as plain text)
#
# SECURITY:
#   Only ALLOWED_CHAT_ID can run agent commands (/run, plain text forwarding, /setagent).
#   /id is allowed for everyone (so you can discover chat_id), but is still echoed to console.

import os
import asyncio
from typing import List

from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, ContextTypes, filters

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT_ID = os.environ.get("ALLOWED_CHAT_ID", "").strip()

if not TOKEN:
  raise SystemExit("Missing TELEGRAM_BOT_TOKEN env var")
if not ALLOWED_CHAT_ID:
  raise SystemExit("Missing ALLOWED_CHAT_ID env var")

try:
  ALLOWED_CHAT_ID_INT = int(ALLOWED_CHAT_ID)
except ValueError:
  raise SystemExit("ALLOWED_CHAT_ID must be an integer")

# --- Agent selection (in-memory). Default is Codex CLI. ---
_CURRENT_AGENT = "codex"

def _is_allowed(update: Update) -> bool:
  chat = update.effective_chat
  return bool(chat) and chat.id == ALLOWED_CHAT_ID_INT

def _clip(s: str, limit: int = 3500) -> str:
  # Telegram message limit is ~4096 chars; keep margin.
  if len(s) <= limit:
    return s
  return s[:limit] + "\n…(truncated)"

def _echo_console(update: Update):
  chat = update.effective_chat
  user = update.effective_user
  chat_id = chat.id if chat else None
  username = (user.username if user else None) or ""
  name = (user.full_name if user else None) or ""
  text = update.message.text if update.message else ""
  print(f"[TG] chat_id={chat_id} user={name} @{username} text={text!r}")

import shutil

def _agent_cmd(agent: str, prompt: str) -> List[str]:
  # Keep this small & explicit. You can extend later (claude, etc.).
  agent = (agent or "").strip().lower()
  if agent == "codex":
    # Official non-interactive mode uses `codex exec`.
    # Try to find codex in PATH, fallback to known npm location
    codex_path = shutil.which("codex") or shutil.which("codex.cmd")
    if not codex_path:
      # Fallback to npm global install location
      npm_path = os.path.expandvars(r"%APPDATA%\npm\codex.cmd")
      if os.path.exists(npm_path):
        codex_path = npm_path
      else:
        codex_path = "codex"  # Let it fail with FileNotFoundError
    return [codex_path, "exec", "--skip-git-repo-check", prompt]
  raise ValueError(f"Unknown agent: {agent}")

async def _run_agent(update: Update, prompt: str):
  global _CURRENT_AGENT

  prompt = (prompt or "").strip()
  if not prompt:
    await update.message.reply_text("Empty prompt.")
    return

  cmd = _agent_cmd(_CURRENT_AGENT, prompt)
  print(f"[RUN] agent={_CURRENT_AGENT} exec={cmd!r}")

  await update.message.reply_text(f"Running on {_CURRENT_AGENT}…")

  try:
    proc = await asyncio.create_subprocess_exec(
      *cmd,
      stdout=asyncio.subprocess.PIPE,
      stderr=asyncio.subprocess.PIPE
    )
  except FileNotFoundError:
    await update.message.reply_text(f"Cannot find '{cmd[0]}' in PATH. Try `{cmd[0]} --help` in terminal.")
    return

  try:
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=300)  # 5 minutes
  except asyncio.TimeoutError:
    proc.kill()
    await update.message.reply_text("Timeout (300s). Killed.")
    print("[RUN] timeout -> killed")
    return

  out = (stdout or b"").decode("utf-8", errors="replace").strip()
  err = (stderr or b"").decode("utf-8", errors="replace").strip()

  print(f"[RUN] exit_code={proc.returncode} stdout_len={len(out)} stderr_len={len(err)}")

  if out:
    await update.message.reply_text(_clip(out))
  if err:
    await update.message.reply_text("stderr:\n" + _clip(err))

  if not out and not err:
    await update.message.reply_text(f"Done. exit_code={proc.returncode}")

# --- Telegram handlers ---

async def cmd_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  chat = update.effective_chat
  if not chat:
    return
  await update.message.reply_text(f"chat_id = {chat.id}")

async def cmd_agent(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)
  await update.message.reply_text(f"current_agent = {_CURRENT_AGENT}")

async def cmd_setagent(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)

  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  name = " ".join(context.args).strip().lower()
  if not name:
    await update.message.reply_text("Usage: /setagent <name>   (supported: codex)")
    return

  # Validate by trying to build a command.
  try:
    _agent_cmd(name, "ping")
  except Exception:
    await update.message.reply_text(f"Unknown agent: {name}. Supported: codex")
    return

  global _CURRENT_AGENT
  _CURRENT_AGENT = name
  await update.message.reply_text(f"OK. current_agent = {_CURRENT_AGENT}")

async def cmd_run(update: Update, context: ContextTypes.DEFAULT_TYPE):
  _echo_console(update)

  if not _is_allowed(update):
    await update.message.reply_text("Access denied.")
    return

  prompt = " ".join(context.args).strip()
  if not prompt:
    await update.message.reply_text("Usage: /run <text>")
    return

  await _run_agent(update, prompt)

async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
  # Any non-command text is treated as a prompt for the current agent.
  _echo_console(update)

  if not _is_allowed(update):
    # Still echo to console, but don't run anything.
    await update.message.reply_text("Access denied.")
    return

  text = update.message.text if update.message else ""
  await _run_agent(update, text)

def main():
  print("[BOOT] Starting Telegram gateway (polling)…")
  print(f"[BOOT] Allowed chat_id = {ALLOWED_CHAT_ID_INT}")
  print(f"[BOOT] Current agent = {_CURRENT_AGENT}")

  app = Application.builder().token(TOKEN).build()

  # Commands
  app.add_handler(CommandHandler("id", cmd_id))
  app.add_handler(CommandHandler("agent", cmd_agent))
  app.add_handler(CommandHandler("setagent", cmd_setagent))
  app.add_handler(CommandHandler("run", cmd_run))

  # Any plain text (non-command) => run agent
  app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

  app.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
  main()
