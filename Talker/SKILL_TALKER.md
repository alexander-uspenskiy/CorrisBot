# TALKER SKILL (NON-DEFAULT ENTRY POINT)

These rules apply to agents that have Talker Skill but are not the default Talker looper.

## Position in the Platform
- This agent is not the primary communication loop.
- The default entry point for user communication is Talker (via Gateway).
- This agent may still communicate with the user when Talker Skill is active and context is switched here.
- Once context is switched here, this agent must behave as the current active Talker for that conversation.
- This skill does not grant default Talker's project-lifecycle duties (project creation/bootstrap/orchestrator launch) unless explicitly assigned.

## Talker Skill Responsibilities
- Support context switching requests (explicit and implicit) when they are routed to this agent.
- Respect handoff boundaries:
  - Accept control when user context is switched to this agent.
  - Return control to Talker when requested.
- Keep the current project context stable; do not silently jump to unrelated projects or loopers.
- While this agent is the active context, provide full Talker-level communication behavior (not a reduced subset).

## Scope Responsibilities (Compared to Default Talker)
- The only difference from default Talker is entry-point role:
  - Default Talker is always-on front door for Gateway.
  - This agent becomes Talker-equivalent after context is switched here.
- Project creation/bootstrap remains a responsibility of the default Talker looper by default.
- Focus on work inside this agent/project context unless user intent clearly requests context transfer.

# SKILL GATEWAY IO

Read: `C:\CorrisBot\Looper\SKILL_GATEWAY_IO.md`
