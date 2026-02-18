# System Prompt Token Estimate (All Loopers)

Date: 2026-02-16
Project context: CorrisBot (active project sample: `C:\Temp\CorrisBot_TestProject_4`)

## Method
This is an estimate (no `tiktoken` in environment):
- `tokens_mid ~= chars / 4.0`
- `tokens_min ~= chars / 4.4`
- `tokens_max ~= chars / 3.6`

Loop wrapper from `Looper/codex_prompt_fileloop.py` (`build_loop_prompt`) is counted separately and added to each looper.

## Raw Metrics By Source Block
| Block | Chars | Words | Tokens Min | Tokens Mid | Tokens Max |
|---|---:|---:|---:|---:|---:|
| `Looper/ROLE_LOOPER_BASE.md` | 2212 | 323 | 503 | 553 | 614 |
| `Looper/SKILL_GATEWAY_IO.md` | 1043 | 161 | 237 | 261 | 290 |
| `Looper/SKILL_AGENT_RUNNER.md` | 2440 | 332 | 555 | 610 | 678 |
| `Talker/ROLE_TALKER.md` | 6837 | 864 | 1554 | 1709 | 1899 |
| `Talker/SKILL_TALKER.md` | 1648 | 245 | 375 | 412 | 458 |
| `ProjectFolder_Template/Orchestrator/ROLE_ORCHESTRATOR.md` | 9562 | 1249 | 2173 | 2390 | 2656 |
| `ProjectFolder_Template/Workers/Worker_001/ROLE_WORKER.md` | 1982 | 266 | 450 | 496 | 551 |
| `Talker/AGENTS.md` (assembled) | 12409 | 1672 | 2820 | 3102 | 3447 |
| `C:\Temp\CorrisBot_TestProject_4\Orchestrator\AGENTS.md` (assembled) | 16784 | 2302 | 3815 | 4196 | 4662 |
| `C:\Temp\CorrisBot_TestProject_4\Workers\Worker_001\AGENTS.md` (assembled) | 6835 | 992 | 1553 | 1709 | 1899 |
| Loop wrapper (`build_loop_prompt`, empty user prompt) | 511 | 83 | 116 | 128 | 142 |

## Per-Looper Total (Without User Prompt Text)
| Looper | Assembled AGENTS Mid | Loop Wrapper Mid | Total Mid | Total Range (Min..Max) |
|---|---:|---:|---:|---:|
| Talker | 3102 | 128 | 3230 | 2936..3589 |
| Orchestrator (active project) | 4196 | 128 | 4324 | 3931..4804 |
| Worker (active project) | 1709 | 128 | 1837 | 1669..2041 |

## Composition View (Approx Mid, before dedup in assembler)
- Talker chain approx: `base + talker_role + gateway_io + agent_runner = 553 + 1709 + 261 + 610 = 3133`
- Orchestrator chain approx: `base + talker_skill + gateway_io + orch_role + agent_runner = 553 + 412 + 261 + 2390 + 610 = 4226`
- Worker chain approx: `base + talker_skill + gateway_io + exec_role = 553 + 412 + 261 + 496 = 1722`

Note: assembled `AGENTS.md` totals differ slightly from composition sums because assembler removes duplicate headings and flattens chain content.
