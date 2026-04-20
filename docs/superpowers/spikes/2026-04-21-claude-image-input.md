# Spike: Claude CLI image input (M3)

**Date:** 2026-04-21
**CLI version:** claude 2.1.114
**Model:** claude-opus-4-7

## Question

How does `claude -p` accept a frame image in non-interactive mode?

## Candidates tested

### 1. `@path` inline reference

Command:
```bash
FRAME="/Users/greigbradley/Desktop/BJJ_Analysis/assets/greig_1s/f_001_0s.jpg"

claude -p \
  --model claude-opus-4-7 \
  --output-format stream-json \
  --include-partial-messages \
  --max-turns 1 \
  --dangerously-skip-permissions \
  --verbose \
  "Read the image at @$FRAME and describe what you see in one sentence."
```

Exit: 0
Stream parseable: yes
Image actually read: yes — evidence: "A bearded man in a red patterned rashguard stands in the foreground of a BJJ gym while other practitioners sit on the mats or stand talking in the background."

### 2. `--add-dir` + path reference

Command:
```bash
not tried — Step 2 succeeded
```

Result: not tried

### 3. Markdown wrapper with `![...](path)`

Command:
```bash
not tried — Step 2 succeeded
```

Result: not tried

## NDJSON stream shape observed

First 2 meaningful NDJSON lines (lines 1 and 12 of the 17-line output; lines 2–11 are hook/init/status/stream_event noise):

**Line 1** (session hook):
```json
{"type":"system","subtype":"hook_started","hook_id":"3f11651d-dfd2-4487-b957-00a595f4d8e3","hook_name":"SessionStart:startup","hook_event":"SessionStart","uuid":"fa7d9969-5dc3-4427-9587-442e0e49e2b2","session_id":"88b33e53-25f2-41de-ac37-0f5140455340"}
```

**Line 12** (assistant message):
```json
{"type":"assistant","message":{"model":"claude-opus-4-7","id":"msg_01CGuYodFSAepTGigNFKsv33","type":"message","role":"assistant","content":[{"type":"text","text":"A bearded man in a red patterned rashguard stands in the foreground of a BJJ gym while other practitioners sit on the mats or stand talking in the background."}],"stop_reason":null,"stop_sequence":null,"stop_details":null,"usage":{"input_tokens":6,"cache_creation_input_tokens":11515,"cache_read_input_tokens":16508,"cache_creation":{"ephemeral_5m_input_tokens":0,"ephemeral_1h_input_tokens":11515},"output_tokens":1,"service_tier":"standard","inference_geo":"not_available"},"context_management":null},"parent_tool_use_id":null,"session_id":"88b33e53-25f2-41de-ac37-0f5140455340","uuid":"e41a1038-345e-405c-bfcf-a13229460d36"}
```

**Last line** (result):
```json
{"type":"result","subtype":"success","is_error":false,"api_error_status":null,"duration_ms":6648,"duration_api_ms":4560,"num_turns":1,"result":"A bearded man in a red patterned rashguard stands in the foreground of a BJJ gym while other practitioners sit on the mats or stand talking in the background.","stop_reason":"end_turn","session_id":"88b33e53-25f2-41de-ac37-0f5140455340","total_cost_usd":0.08162775,"usage":{...}}
```

**Comparison to plan's assumed shape:**

The plan assumed:
- `{"type":"assistant","message":{"content":[{"type":"text","text":"..."}]}}` ✓ — matches exactly (with additional fields like `model`, `id`, `usage`, `context_management`, `parent_tool_use_id` also present)
- `{"type":"result","result":"...","is_error":false}` ✓ — matches exactly (with additional fields: `subtype`, `api_error_status`, `duration_ms`, `duration_api_ms`, `num_turns`, `stop_reason`, `total_cost_usd`, `usage`, `modelUsage`, etc.)

**Notable difference:** The result event has a `"subtype":"success"` field not mentioned in the plan. When `is_error` is true, `subtype` would likely be `"error"`. Tasks 11/12 should check `is_error` (boolean) not `subtype` for error detection.

**Event type sequence observed** (17 lines total):
`system` (hook_started) → `system` (hook_response) → `system` (init) → `system` (status) → `stream_event` × 7 → `assistant` → `stream_event` × 3 → `rate_limit_event` → `result`

The `--include-partial-messages` flag causes additional `stream_event` lines wrapping the raw Anthropic streaming events (e.g., `message_start`, `content_block_start`, `content_block_delta`, `content_block_stop`, `message_delta`, `message_stop`). Parsers for Tasks 11/12 should filter to `type == "assistant"` and `type == "result"` and ignore the rest.

## Decision

The adapter (`server/analysis/claude_cli.py`) will use **`@path` inline reference** for image input, formatted as:

```python
prompt = f"Read the image at @{frame_path} and {task_instruction}"
```

Or equivalently in the subprocess call:

```python
f"...@/absolute/path/to/frame.jpg..."
```

The `@` prefix causes the CLI to read the file from disk and pass it to the model as a vision input. The path must be absolute.

## Fallback

If the chosen mechanism breaks in a future CLI version: try Candidate 3 (markdown wrapper `![frame](absolute_path)`) as the next-best approach, since it uses standard markdown image syntax that the CLI may also honour.

## Notes

- **Rate limit warning observed:** The `rate_limit_event` line showed `"utilization":0.9` and `"rateLimitType":"five_hour"` — 90% of the five-hour rate limit was already consumed at the time of the spike. This is a concern for long analysis sessions with many frames; the adapter should handle `rate_limit_event` gracefully (log/warn but don't treat as fatal).
- **Cost:** $0.082 USD per frame for claude-opus-4-7 with ~28k cache tokens. Production runs should use a cheaper/faster model (claude-haiku-4-5 or claude-sonnet-4-5) once the mechanism is confirmed.
- **`--verbose` flag** causes the hook system and `stream_event` wrappers to appear in stdout. Without `--verbose`, the output may be cleaner (fewer lines). Worth re-testing without it if NDJSON parsing complexity is a concern.
- **Zero stderr output** — the command ran cleanly with no warnings to stderr.
- **input_tokens reported as 6** in the usage block even though the image was passed — this is likely because the image tokens are counted separately or are reported in `cache_creation_input_tokens` (11515 tokens). The adapter should not rely on `input_tokens` for image cost estimation.
- **`--include-partial-messages`** is needed to get the `assistant` event mid-stream; without it, only the final `result` event may appear (unconfirmed — test if partial streaming is not needed).
