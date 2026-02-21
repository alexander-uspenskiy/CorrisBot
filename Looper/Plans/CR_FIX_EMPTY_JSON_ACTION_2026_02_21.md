# Code Review: Fail-Closed on Empty JSON Agent Output

## 1. Scope
The goal of this patch is to address the issue of silent failures when an underlying CLI agent (e.g., Kimi CLI) exits with a success code (`0`) but fails to produce any actionable JSON output (like `agent_message`, `reasoning`, or tool commands). Under the previous implementation, this condition caused the Looper to report a false "success" without any actual response or indication of failure reaching the Telegram Gateway.

**Component Affected**: `Looper/codex_prompt_fileloop.py`
**Path**: `PromptFileLoop.run_agent()`

## 2. Findings

### Architectural Gap
- Prior to the change, `run_agent` strictly trusted the `exit_code` returned by the subprocess.
- CLI programs that fail early due to configuration or authentication errors (like `LLM not set, send "/login" to login` in `kimi-cli`) can stubbornly exit with code `0`.
- The JSON line parser strictly ignores any plain text completely, leading to an empty event list being emitted from the runner.
- The Gateway parses `Result.md` exclusively for runner-compliant JSON formats. Any plain text error gets completely skipped, leaving the down-stream Orchestrator or human User in absolute silence.

### The Fix
- Replaced the heuristic approach with a strict protocol contract: the agent MUST emit at least one valid JSON action event `{"event": ...}` to be considered successful.
- Introduced a tracking flag `has_valid_json_action = False` per inner shell loop execution.
- In the stdout reading loop, if `ev in ("reasoning", "agent_message", "command_started", "command_completed")`, the flag is set to `True`.
- After process completion, if `return_code == 0` and `not has_valid_json_action`:
    - The turn is marked as failed (`return_code = 1`).
    - The `Result.md` gets forcibly appended with a synthetic valid JSON `agent_message` containing the failure text utilizing `append_gateway_agent_message`. This ensures the Telegram Gateway *will* read and deliver it!
    - It extracts and dumps the non-JSON raw lines (`LLM not set...` or other anomalies) directly into the logs and the synthetic message, ensuring that the Telegram Gateway relays this failure information back to the end user.

## 3. Checks

1. **Does the change break CodexRunner?** 
   - No. Even if Codex were to fail silently and produce no JSON items, the loop will gracefully block and fail instead of progressing on empty content. If Codex runs normally, it outputs `agent_message` or `command_started` objects with `type: item.completed`.

2. **Does it accurately catch the Kimi login failure?**
   - Yes, the non-JSON phrase `LLM not set, send "/login" to login` fails to produce any JSON arrays or dictionaries. Thus, `has_valid_json_action` remains `False`, triggering the fail-closed trap.

3. **Are formatting standards respected?**
   - Yes, the logic mutates `return_code = 1` and utilizes `append_gateway_agent_message`, injecting an artificially crafted `['role': 'assistant']` (for Kimi) or `['type': 'agent_message']` (for Codex) block into the `Result.md` stream. Gateway happily parses this format strictly by its design and faithfully bridges the warning to telegram.

4. **Security and Side-effects**
   - Implements "Fail-Closed" patterns, which are the engineering gold standard for system observability and strict agent contract enforcement.

## 4. Verdict
**APPROVED**. 
The implementation adds strong protocol invariants for agent behavior without relying on fragile stdout text-matching heuristics. It elegantly handles the silent failure condition by strictly enforcing actionable output, successfully resolving observability gaps across all potential CLI runners.
