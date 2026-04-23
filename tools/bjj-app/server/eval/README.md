# M11 eval harness

Offline LLM-as-judge evaluation for the section and summary prompts.

## ⚠️ Cost

Each fixture entry × variant triggers **2 real Claude CLI calls** (one
generation, one judgement). A 5-entry × 2-variant run = 20 calls. Start
with 1-2 entries while wiring up, then scale up.

## Section eval

```bash
cd tools/bjj-app
.venv/bin/python -m server.eval section \
    --fixture server/eval/fixtures/sections-smoke.yaml \
    --variants m9b-baseline m10-grounded \
    --output server/eval/reports/$(date +%Y-%m-%d-%H%M)-section-smoke.md \
    --run-name "M9b vs M10 smoke"
```

Fixture shape:

```yaml
sections:
  - roll_id: "<32-hex>"
    section_id: "<uuid>"
    note: "optional — shows up in the report"
```

The `roll_id` and `section_id` must already exist in the local
`bjj-app.db` (and the section's frame files must be on disk under
`assets/<roll_id>/frames/`). Nothing gets re-extracted.

## Summary eval

```bash
.venv/bin/python -m server.eval summary \
    --fixture server/eval/fixtures/summary-smoke.yaml \
    --variants current \
    --output server/eval/reports/$(date +%Y-%m-%d-%H%M)-summary-smoke.md \
    --run-name "baseline summary"
```

Fixture shape:

```yaml
rolls:
  - roll_id: "<32-hex>"
    note: "optional"
```

The summary is regenerated from the roll's **currently-persisted section
narratives** — it does NOT re-run the section prompt. If you want to eval
section + summary jointly, run section eval first (that writes new
narratives into the DB via normal /analyse… no wait, section eval does NOT
mutate the DB — it only generates + judges ephemerally). Summary eval
uses whatever narratives are in the DB from previous /analyse runs.

## Adding a new variant

Edit `server/eval/variants.py`:

```python
def _m10_with_techniques(ctx: SectionEvalContext) -> str:
    # ...assemble a richer prompt...
    return build_section_prompt(...)

SECTION_VARIANTS["m10-techniques"] = _m10_with_techniques
```

Then pass `--variants m10-grounded m10-techniques` on the CLI.

## Reports

Written to `server/eval/reports/*.md` (gitignored). Use the `--run-name`
flag to stamp a helpful title into the header.
