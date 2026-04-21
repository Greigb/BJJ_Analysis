# Audit: Claude CLI subprocess + `--dangerously-skip-permissions`

**Date:** 2026-04-21
**Code reviewed:** `tools/bjj-app/server/analysis/claude_cli.py` @ M3
**Trigger:** spec requires an explicit audit when this flag is used programmatically.

## What the flag does

`claude -p --dangerously-skip-permissions` disables Claude Code's interactive tool-use permission prompts. Without it, Claude would halt mid-session asking "May I read this file?", "May I run this command?" — impossible to answer from a server.

## What threat is being accepted

The Claude process runs with the app user's shell privileges. If we passed it a prompt containing attacker-controlled content, the model could be coaxed into reading arbitrary files or running shell tools against them, and those tool uses would succeed without a human in the loop.

## Mitigations in place

1. **No user input in the prompt.** `prompt.build_prompt()` is a pure function of three inputs: `frame_path` (we control it), `taxonomy_path` (we control it — it's `tools/taxonomy.json` shipped in the repo), `timestamp_s` (a float parsed from SQLite, not user text). The upload endpoint's `title` / `partner` text is **never** concatenated into a prompt. Greg to do in future milestones: keep this invariant.
2. **Frame path is validated.** `analyse_frame` calls `Path.resolve()` and `relative_to(settings.project_root)` — any path that escapes the project root (symlinks, `..`, absolute paths outside the repo) is rejected before the subprocess is spawned.
3. **argv list, never shell.** Subprocess is spawned via `asyncio.create_subprocess_exec(*argv)` with a plain list. No `shell=True`, no string concatenation into a shell command. Paths containing spaces or shell metacharacters (there are none in our frame names, but defence in depth) are not re-interpretable.
4. **Bounded turns.** `--max-turns 1` means the model gets exactly one response; it cannot enter a multi-turn tool-loop.
5. **Limited scope.** Claude sees only the prompt and one image. It has no git repo, no shell history, no MCP tools beyond defaults. `stderr` is `DEVNULL` (we don't surface it), `stdout` is captured and parsed.
6. **Rate limit.** 10 calls / 5-min window caps the blast radius of any pathological behaviour.

## Residual risks accepted

- If a future engineer adds user-controlled text to `build_prompt` (e.g. annotations, partner names), mitigation #1 fails silently. **Mitigation:** add a new test in `test_prompt.py` that asserts `build_prompt` rejects or sanitises any non-validated string.
- If `taxonomy.json` is replaced by an attacker with write access to the repo — they already had arbitrary code execution. No additional risk from this flag.
- A malicious frame file (crafted to exploit Claude's image reader) is theoretically possible. We only accept frames extracted by our own `frames.py` from videos the local user uploaded through `POST /rolls`. The app binds to `0.0.0.0:8000` for LAN access — anyone on the local wifi can upload. Acceptable for a single-user home-use app; revisit if scope expands.

## Conclusion

Passing `--dangerously-skip-permissions` is appropriate in this context. The invariants above must hold; any code change that weakens them (esp. #1 and #2) requires a fresh audit.

## Review trigger

Re-open this audit if any of the following change:
- `build_prompt` gains a parameter not listed above.
- `analyse_frame` is called from a new code path.
- Claude CLI major version bump (currently 2.1.114).
- App is exposed beyond the local LAN.
