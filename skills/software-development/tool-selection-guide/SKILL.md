---
name: tool-selection-guide
description: Use when deciding which tool to call for a task. Covers terminal vs execute_code vs computer_use vs work_control vs read/write/patch, with concrete examples and decision criteria.
version: 1.0.0
author: Hermes Agent
license: MIT
metadata:
  hermes:
    tags: [tool-selection, decision-guide, workflow, productivity]
    category: software-development
    related_skills: [plan, systematic-debugging]
---

# Tool Selection Guide

## Overview

When faced with a task, the first decision is **which tool to use**. This guide covers the common tools, when to reach for each, and when to combine them. It is not a replacement for reading individual tool skills — it is the decision layer on top.

## Decision Tree

```
Is the task about automating a GUI (clicking, typing, scrolling in a desktop app)?
  → YES → computer_use
  → NO ↓

Is the task a multi-step procedure with 3+ tool calls, conditional logic, or data processing?
  → YES → execute_code
  → NO ↓

Is the task a single shell command or a short pipeline?
  → YES → terminal
  → NO ↓

Is the task about managing a structured workflow with steps and criteria?
  → YES → work_control
  → NO ↓

Is the task about reading, writing, or editing a file?
  → YES → read_file / write_file / patch
  → NO ↓

Is the task about delegating work to a subagent?
  → YES → delegate_task
  → NO ↓

Is the task about searching past conversations?
  → YES → session_search
  → NO ↓

Default: terminal for anything shell-adjacent.
```

## Tool Comparison

### `terminal` vs `execute_code`

| Aspect | `terminal` | `execute_code` |
|---|---|---|
| **Best for** | Single commands, short pipelines, builds, git ops | 3+ tool calls with logic between them, conditional branching, data processing |
| **Language** | Shell (bash/MSYS on Windows) | Python (stdlib + hermes_tools) |
| **State** | Persists across calls (exported env, cwd) | Fresh process each call (but session-level state like venv persists) |
| **Tool calls inside** | No (shell only) | Yes — can call `terminal`, `read_file`, `search_files`, etc. |
| **Output** | stdout/stderr captured directly | Must `print()` to return results |
| **Timeout** | Default 180s (foreground) | Default 180s |
| **When to pick** | `ls`, `git status`, `npm install`, `grep`, `curl` | "Read these 3 files, merge them, filter by X, write result" |

**Rule of thumb:** If you'd write a `for` loop, an `if/else`, or call a tool more than twice in the same logical unit, use `execute_code`.

### `read_file` / `write_file` / `patch`

| Tool | When to use |
|---|---|
| `read_file` | Reading any file. Supports line numbers, pagination, notebooks, PDFs, Excel. Use instead of `cat`/`head`. |
| `write_file` | Creating or **completely replacing** a file. Creates parent dirs. Auto-runs syntax checks. Use instead of `echo`/`cat` heredoc. |
| `patch` | Targeted find-and-replace edits in a file. Fuzzy matching (9 strategies). Use instead of `sed`/`awk`. |

**Rule of thumb:** `patch` for surgical edits, `write_file` for full rewrites or new files, `read_file` for reading. Never use `terminal` with `cat`/`sed`/`echo` when these exist.

### `computer_use`

Use when the task requires interacting with a **native desktop application** — clicking buttons, typing into forms, scrolling, dragging. Not for:
- Web automation (use browser tools or `terminal` with `curl`)
- File editing (use `read_file`/`write_file`/`patch`)
- Shell commands (use `terminal`)

**Key habits:**
1. Always `capture` first (`mode='som'` by default).
2. Click by element index, not pixel coordinates.
3. Re-capture after state-changing actions.
4. Never `raise_window=True` unless explicitly asked.

### `work_control`

Use for **structured multi-step work** with objectives, steps, and verification criteria. Not for:
- Simple to-do lists (use the `todo` tool)
- One-off tasks with no verification criteria
- Tasks where you don't need step-by-step accountability

**When it shines:** Desktop organization, data reconciliation, any task where you need to prove completion against criteria.

### `delegate_task`

Use when you need **isolated subagents** for reasoning-heavy subtasks that would flood your context window. Not for:
- Simple one-liners
- Tasks requiring user interaction (subagents can't use `clarify`)
- Durable long-running work (use `cronjob` instead)

**Rule of thumb:** If the subtask would require 5+ tool calls and you'd lose track of intermediate results, delegate it.

### `session_search`

Use for **recall from past conversations**. Discovery shape for topic search, scroll shape for reading a session, browse shape for recent activity. Not for:
- Current source state (inspect the original source first)
- External system state (use the relevant tool for that)

## Common Patterns

### Pattern: Read → Decide → Act

```
1. read_file or terminal to gather context
2. Decide which tool to use
3. Execute with the right tool
4. Verify (re-read, re-capture, re-run)
```

### Pattern: Multi-file refactoring

```
1. search_files to find all affected files
2. read_file on each to understand context
3. patch each file with targeted changes
4. terminal to run tests/lint
```

### Pattern: Desktop task

```
1. computer_use(action='capture', mode='som')
2. Identify elements
3. computer_use(action='click', element=N)
4. computer_use(action='capture') to verify
```

### Pattern: Data processing

```
1. execute_code with terminal/read_file calls inside
2. Process data in Python
3. write_file to save results
4. terminal to verify
```

## Pitfalls

1. **Using `terminal` for multi-step logic.** If you need conditionals or loops, use `execute_code`. Shell one-liners are fine; multi-command pipelines with logic are not.
2. **Using `computer_use` for web tasks.** If you can do it via a headless browser or API, don't drive the GUI. GUI automation is fragile.
3. **Using `patch` when `write_file` is better.** If you're changing more than 30% of a file, just rewrite it.
4. **Using `work_control` for simple tasks.** If there's only one step and no verification criteria, just do it.
5. **Forgetting to verify.** Every action should be followed by a check — re-read the file, re-capture the screen, re-run the test.

## Verification Checklist

- [ ] Did I pick the simplest tool that handles the task?
- [ ] If I used `terminal`, would `execute_code` have been better (3+ tool calls, logic)?
- [ ] If I used `computer_use`, did I capture first and click by element?
- [ ] If I edited a file, did I verify the edit?
- [ ] Did I avoid `terminal` for things `read_file`/`write_file`/`patch` handle?