# CorrisBot

**CorrisBot** is a portable asynchronous multi-agent orchestration platform based on looping LLM agents.

It allows you to build more complex projects than with conventional agent systems such as Codex or Claude Code.

The platform helps partially address:

- orchestration automation;
- context window length limits;
- token costs.

By delegating tasks to other agents, the orchestrator saves context, while tasks themselves can run in parallel. This makes it possible to solve problems several times more complex than what a single agent's context window allows.

You can communicate with the orchestrator asynchronously: your request will be processed in between its interactions with other agents. In other words, iterative refinement on the fly is a viable workflow.

## Agent Types

The platform includes three types of specialized agents with different skill sets:

- `Talker` — for communication with the user;
- `Orchestrator` — for platform orchestration;
- `Worker` — any other agents.

### Recommended `Worker` specializations (optional)

- `Seeker` — Low/Med reasoning;
- `Planner` — High reasoning;
- `Worker` — Med/High reasoning;
- `CodeReviewer` — High reasoning;
- `QA` — High reasoning;
- `Heartbeat/AlarmClock` — Low reasoning.

`Worker` specializations are assigned by the orchestrator based on your requirements.

The orchestrator decides on its own how many agents are needed and what kinds they should be to complete a task. However, you can also provide direct instructions.

## Configuration

You can change the `Talker` agent configuration in:

- `Talker\agent_runner.json`

Supported runners:

- `Codex`
- `Kimi`

Model-specific settings are configured in:

- `Talker\codex_profile.json`
- `Talker\kimi_profile.json`

The orchestrator configures all other agents. You can explicitly tell it what you want, or let it decide autonomously.

## Current Version Limitations

The platform is still in an early development stage and currently works only with ChatGPT and Kimi Code subscriptions.

The platform does not yet support API tokens.

## Prerequisites

Required software:

- Windows
- Telegram
- Python 3.13 recommended
- Python launcher `py`
- `pip`
- Git
- Windows Terminal
- Python package `python-telegram-bot`
- At least one supported agent CLI:
  - Codex CLI
  - Kimi Code CLI
- At least one subscription:
  - ChatGPT
  - Kimi Code

Notes:

- The platform can run entirely on Codex or entirely on Kimi.
- Installing both CLIs is optional.

## Setup

Task handoff to the orchestrator happens through a Telegram bot.

For installation, add the following environment variables:

- `TELEGRAM_BOT_TOKEN`
- `ALLOWED_CHAT_ID`

Available LLM models are listed in:

- `Talker\AgentRunner\model_registry.json`

When new models appear, add them there.

## Launch

To launch, use:

```bat
CorrisBot.bat
```

The looping agent `Talker` will handle communication with the user.

It acts as a standard chatbot that can create new projects.

## Telegram Bot Commands

```text
/help                  - show chatbot commands
/id                    - get chat ID (`ALLOWED_CHAT_ID`), required for platform operation
/reset                 - reset current LLM model sessions
/agent                 - show current agent <tg_userid>
/routing show          - show current routing settings
/routing set-user <tg_userid> - configure information forwarding
```

## Usage Example

A command to create a project and start the orchestrator can be given in free form, for example:

```text
Create a new project.
In directory c:\Temp\CorrisBot_TestProject_13
Orchestrator should be Codex reasoning High
```

After that, `Talker` may ask clarifying questions, create the project, and launch the orchestrator.

It's useful to agree in advance with `Talker` that it should pass data to the orchestrator verbatim. You can phrase it freely, for example:

```text
When I ask you to pass something to the orchestrator, forward the data verbatim.
For brevity, I may write `Orc: <do something>`.
```

### Example of assigning a task to the orchestrator

```text
Orc:

Your task is to orchestrate a test project.
In directory c:\Temp\TestProject create a Python script that computes parabola values for X in the range from -1 to 1.
The script must write the result to an .md file next to the script itself.
In addition, you must create an AlarmClock Worker with Codex reasoning Low, whose task is to ping you once every three minutes.
That is, this AlarmClock should send you a task through Windows Task Scheduler.
After you report to me that you received the reminder, I will ask you to stop this clock.
This is also part of the test: to verify that this heartbeat works and that we can stop it.
Example scripts for registration and launch are in these two files:
<Corrisbot>\AlarmClock\Tools\register_alarmclock_task.ps1
<Corrisbot>\AlarmClock\Tools\alarmclock_tick.ps1
```

## Known Platform Issues

- Automatic context compression can lead to orchestrator "narcolepsy." As a result, especially large projects are not yet feasible.
  Temporary workaround: ask the orchestrator to periodically monitor its context, and when automatic compression approaches, make a handoff to an `.md` file and require reading that file immediately after compression.
  `TBD`: ability to restart the orchestrator with a preliminary handoff and subsequent context restoration.
- At some point, the orchestrator may "forget" the next step. This can happen after context compression.
  Workaround: create a `Heartbeat` agent that pings the orchestrator once per hour to remind it of the project's final goal. You can ask the orchestrator to create such an agent.
- The `Talker` agent can also suffer from "narcolepsy." This is usually fixed by restarting the `Talker` session (there is no standard way yet). After that, you will need to remind it again where the orchestrator is located.
- When routing orchestrator messages through `Talker`, it tends to paraphrase messages instead of relaying them directly. This can be mitigated by persistently asking it to forward text verbatim.
- There is no built-in system restart. Once launched, a project keeps running until terminals are closed.
- The orchestrator tends to repeatedly reuse the same agents, despite approaching context limits. This can be mitigated by instructing it to force agent rotation after `N` tasks.
