# BJJ App M6b — PDF Export — Design

**Date:** 2026-04-21
**Status:** Design approved, implementation plan pending
**Parent spec:** [2026-04-20-bjj-local-review-app-design.md](./2026-04-20-bjj-local-review-app-design.md)
**Prior milestone:** M6a (summary step) merged at `109e99c` on main.
**Follow-on:** M7 (PWA + mobile polish), M8 (Streamlit retirement).

## Context

M6a added the Finalise step: a single Claude call turns a roll's collected moment analyses + user annotations into a coaching report (scores, summary text, improvements, strengths, three key moments). Finalised rolls render a `ScoresPanel` on the review page and — after Save to Vault — emit six ordered sections in the roll's Obsidian markdown.

M6b adds the last piece the parent spec promised: a **printed match report PDF** suitable for sharing with training partners. One-page, white-paper aesthetic, deterministic render from existing SQLite state (no new Claude call). The PDF file lives in the roll's asset directory alongside its frames; the roll's markdown gains a `## Report` section linking to it.

## Goals

1. **One-page shareable coaching artifact.** All the ScoresPanel data in a printable form: roll header, one-sentence summary, three score boxes, position-flow bar, improvements, strengths, three key moments.
2. **Deterministic render, no Claude call.** Pure HTML-template → PDF pipeline. Idempotent — re-exporting after a re-finalise produces a fresh PDF from the current SQLite state with no staleness tracking.
3. **Vault-first delivery.** PDF writes to `assets/<roll_id>/report.pdf` (same dir as frames), and the roll's markdown gains a `## Report` section with an Obsidian-compatible link. Same one-click export also streams the PDF back for browser download.
4. **Re-use M6a's per-section machinery.** The new `## Report` section plugs into the existing ordered-splice + per-section hash logic — no new vault-write primitives.
5. **White-paper aesthetic.** Georgia serif headings, system sans body, muted category colors (print-friendly). A4 portrait, 20mm margins.

## Non-goals (explicit)

- **No Page 2.** Annotated frames of key moments, full user-annotation transcript, and vault back-links stay deferred. If Page 1 proves insufficient after shipping, carve out M6c.
- **No result badge.** The parent spec envisioned a win/loss/draw badge on the header; the rolls table doesn't store one, and M6b won't add the schema change.
- **No inline hyperlinks in the PDF.** Timestamps are human labels, not links. Printed paper is the primary consumer.
- **No PDF regeneration on Finalise.** The user still clicks Export explicitly. Finalise stays fast (no PDF render wait).
- **No email / share / cloud upload.** Download + vault write only.
- **No theme toggle.** White-paper aesthetic is the only aesthetic. Users who want a dark version screenshot the ScoresPanel.
- **No Page 2 frame extraction pipeline.** Frames already exist on disk from the pose pre-pass, but they aren't embedded in M6b's PDF.
- **No A-vs-B dual report.** Scores are Player A's only (per M6a). Player B is context in the subtitle, not a second report.

## Design decisions (captured from brainstorm)

| Decision | Choice | Rationale |
|---|---|---|
| Page scope | Page 1 only | Delivers the shareable coaching artifact. Page 2 (frames + annotations) is meaningful extra work; carve off if needed. |
| Delivery | Save to vault + browser download on the same click | Matches the vault-first principle; still gives the user an immediate file. |
| PDF library | WeasyPrint | HTML+CSS is the right layout tool for this content shape. ReportLab would double the layout code; wkhtmltopdf was explicitly rejected by parent spec (Chromium dep). |
| Aesthetic | White paper, Georgia serif headings | PDFs are for sharing/printing. Matches parent-spec intent. |
| Button placement | Review page footer, gated on `roll.summary` | Same pattern as Finalise + Save to Vault; disabled until there's something to export. |
| Vault write timing | Export endpoint writes both PDF and `## Report` markdown | Option b (defer markdown to next publish) would require a third click per Finalise. One button → one user-visible result is simpler. |
| Idempotency | Every Export overwrites the PDF + refreshes the hash | No staleness tracking. Current-state export is always "the truth." |
| Conflict handling | Re-use M6a per-section hash for the `## Report` section | Unlikely anyone edits a link in Obsidian, but the same dialog fires if they do — for the markdown only. The PDF file itself is always written + downloaded regardless. |
| Page size | A4 portrait, 20mm margins | A4 is Greig's local default; US-letter printers will crop ~5mm at the bottom of a 20mm margin — acceptable since all essential content sits well above the fold. |

## Architecture

One new endpoint, one new pure-render module, one new Jinja2 template + CSS, one new frontend action.

### New backend module: `server/export/pdf.py`

Pure helpers, no IO except for the Jinja/WeasyPrint calls:

```python
def build_report_context(
    roll: dict,                        # RollDetailOut-shaped dict
    moments: list[dict],               # with id, frame_idx, timestamp_s, category
    analyses_by_moment: dict[str, list[dict]],
    annotations_by_moment: dict[str, list[dict]],
    categories: list[dict],            # taxonomy for category labels + print colors
) -> ReportContext: ...

def render_report_pdf(context: ReportContext) -> bytes: ...
```

`ReportContext` is a `TypedDict` with every field the template needs — fully pre-computed, no raw DB shapes passed to Jinja. Fields include: `title`, `date_human`, `player_a_name`, `player_b_name`, `duration_human`, `moments_analysed_count`, `summary_sentence`, `scores` (list of three with id/label/value/bar_pct/color_bucket), `distribution_bar` (list of segments with label/width_pct/color), `improvements` (list of strings), `strengths` (list of strings), `key_moments` (list of {timestamp_human, category_label, blurb}), `generated_at_human`, `roll_id_short`.

`render_report_pdf` loads the Jinja environment from `server/export/templates/`, renders `report.html.j2` with the context, and passes the resulting HTML to `weasyprint.HTML(string=...).write_pdf(stylesheets=[CSS("report.css")])`. Returns PDF bytes.

Reasons this is a separate module from `server/analysis/summarise.py`:
- No Claude dependency, no prompt, no parser.
- Tests are snapshot-on-HTML + smoke-on-PDF-bytes, not behaviour tests.
- Keeps `analysis/` focused on "things the model does"; `export/` collects "things we render from what the model produced."

### New template: `server/export/templates/report.html.j2` + `report.css`

HTML structure (top → bottom, inside a single `<body>` with one flow):

```html
<header class="masthead">
  <span class="brand">BJJ Match Report</span>
  <span class="date">{{ date_human }}</span>
</header>

<section class="title-block">
  <h1>{{ title }}</h1>
  <p class="subtitle">{{ player_a_name }} vs {{ player_b_name }}
     &bull; {{ duration_human }}
     &bull; {{ moments_analysed_count }} moments analysed</p>
</section>

<section class="summary">
  <p>{{ summary_sentence }}</p>
</section>

<section class="scores">
  {% for score in scores %}
  <div class="score-box bucket-{{ score.color_bucket }}">
    <div class="score-label">{{ score.label }}</div>
    <div class="score-value">{{ score.value }}<span>/10</span></div>
    <div class="score-bar"><div class="fill" style="width: {{ score.bar_pct }}%"></div></div>
  </div>
  {% endfor %}
</section>

<section class="distribution">
  <h2>Position flow</h2>
  <div class="dist-bar">
    {% for seg in distribution_bar %}
    <div class="dist-seg" style="width: {{ seg.width_pct }}%; background: {{ seg.color }};">
      <span class="dist-label">{{ seg.label }} {{ seg.width_pct }}%</span>
    </div>
    {% endfor %}
  </div>
</section>

<section class="improvements">
  <h2>Top improvements</h2>
  <ol>{% for imp in improvements %}<li>{{ imp }}</li>{% endfor %}</ol>
</section>

<section class="strengths">
  <h2>Strengths observed</h2>
  <ul>{% for s in strengths %}<li>{{ s }}</li>{% endfor %}</ul>
</section>

<section class="key-moments">
  <h2>Key moments</h2>
  <table>
    {% for km in key_moments %}
    <tr>
      <td class="ts">{{ km.timestamp_human }}</td>
      <td class="cat">{{ km.category_label }}</td>
      <td class="blurb">{{ km.blurb }}</td>
    </tr>
    {% endfor %}
  </table>
</section>

<footer class="footer-strip">
  Generated {{ generated_at_human }} &middot; {{ roll_id_short }}
</footer>
```

`report.css`:
- Page rule: `@page { size: A4 portrait; margin: 20mm; }`.
- Headings: `Georgia, "Times New Roman", serif`. Body: `-apple-system, system-ui, sans-serif`.
- Muted score buckets: `.bucket-low` → `#b6413a` (soft red), `.bucket-mid` → `#c18a2b`, `.bucket-high` → `#3f8a4b` (soft greens/ambers tuned for paper).
- `.dist-seg` uses muted print colors (same hues as the app's categories, toned down ~40% saturation; exact hex values live in CSS, not in Python).
- Labels inside distribution segments narrower than ~50px get `visibility: hidden` via `@media print` trick — the legend below picks them up. (Simpler alternative: always show labels inside segments, accept overlap for tiny segments; spec chooses the legend fallback.)

### Extended `vault_writer`

Add `report` to the canonical section order (last position, after `strengths`). Render function signature:

```python
def render_report_section(roll_id: str, generated_at: datetime) -> str: ...
```

Returns a body like:

```markdown
[[assets/<roll_id>/report.pdf|Match report PDF]]

*Generated 2026-04-21 14:32*
```

The function is called from within the new PDF export endpoint, not from `publish`. The export endpoint uses the existing `_replace_section_body_if_present` + `_insert_section_at_ordered_position` helpers to update the markdown file directly, updates the `vault_summary_hashes` column for the `report` key, and returns the PDF bytes to the caller.

If the existing markdown's `## Report` body hash doesn't match what's in `vault_summary_hashes` (i.e. the user edited it in Obsidian), the endpoint returns `409 Conflict` **but still writes `assets/<roll_id>/report.pdf` to disk and includes the PDF bytes in the 409 body**. The frontend on 409 offers Overwrite (retry with `?overwrite=1`) or Cancel (keeps the new PDF but skips the markdown update).

### New endpoint: `POST /api/rolls/:id/export-pdf`

**Query params:** `overwrite=1` (optional). When set, skips the conflict check.

**Request body:** none.

**Success response:** `200 OK`, `Content-Type: application/pdf`, `Content-Disposition: attachment; filename="<slug>-<date>.pdf"`, body = PDF bytes.

Filename slug: lowercase the roll title, replace non-alphanumerics with `-`, collapse repeats, trim — so "Tuesday Roll" at date 2026-04-21 becomes `tuesday-roll-2026-04-21.pdf`. Empty titles fall back to `match-report-<date>.pdf`.

**Error responses:**
- `400 Bad Request` — roll not finalised (no `summary` field). Body: `{"error": "Roll must be finalised before export."}`.
- `404 Not Found` — roll id unknown. Body: `{"error": "Roll not found."}`.
- `409 Conflict` — `## Report` markdown body modified since last export. Body: `application/pdf` with a `X-Conflict: report` header. Frontend detects the header and shows `PublishConflictDialog`.
- `502 Bad Gateway` — WeasyPrint raised. Body: `{"error": "PDF rendering failed", "detail": "<safe error str>"}`. No partial file written (render happens fully in memory, then atomic write).

**Order of operations (happy path, no overwrite needed):**
1. Load roll. 404 if missing. 400 if `summary IS NULL`.
2. Load moments, annotations, taxonomy (same shape M6a already assembles for the publish endpoint).
3. Build `ReportContext`.
4. Call `render_report_pdf(context)` → PDF bytes in memory. 502 on exception.
5. Read current markdown from disk (via `vault_writer.read`). Compute hash of the existing `## Report` body (if present). Compare to `vault_summary_hashes['report']`.
   - If the existing hash column has no `report` key → first export; no conflict possible.
   - If set but mismatches current body → 409 (with bytes + header), unless `overwrite=1`.
6. Atomic write: PDF bytes → `assets/<roll_id>/report.pdf.tmp`, then `os.replace` to `report.pdf`.
7. Splice `## Report` section into markdown (ordered insert if absent, in-place replace if present). Atomic write back to vault.
8. Update `vault_summary_hashes['report'] = <hash of new body>` in SQLite.
9. Return 200 with PDF bytes.

Steps 6-8 share the atomic-write discipline already proven in M4/M6a. Step 6 happens *before* 7 so the markdown's `[[...report.pdf]]` link never points at a missing file.

## Frontend contract

### New API client: `web/src/lib/api.ts`

```typescript
export async function exportRollPdf(rollId: string, overwrite = false): Promise<{
  kind: "ok" | "conflict";
  blob: Blob;
  filename: string;
}> { ... }
```

- Posts to `POST /api/rolls/<id>/export-pdf${overwrite ? "?overwrite=1" : ""}`.
- 200 → `{ kind: "ok", blob, filename }`. Parse filename from `Content-Disposition`.
- 409 → `{ kind: "conflict", blob, filename }`. Caller shows dialog but may still save the PDF immediately.
- 4xx/5xx JSON errors → throw `ApiError`.

### Review page button

New button in the footer row, between Finalise and Save to Vault:

```svelte
<button
  type="button"
  disabled={!roll.summary || exporting}
  onclick={handleExport}
>
  {exporting ? "Exporting…" : "Export PDF"}
</button>
```

`handleExport` flow:
1. Set `exporting = true`.
2. Call `exportRollPdf(roll.id)`.
3. If `kind === "ok"`: trigger browser download via object URL + anchor click, show toast "Report downloaded".
4. If `kind === "conflict"`: **trigger the download immediately** (the PDF bytes are valid; the conflict is only over the markdown), then show `PublishConflictDialog` (re-using the M6a component with generalised copy; see below). On "Overwrite" retry with `overwrite=true` — the retry does **not** re-trigger download (the user already has the file). On "Cancel" close the dialog and leave markdown unchanged.
5. Set `exporting = false` in `finally`.

### Copy change

`PublishConflictDialog.svelte` body currently says "Your Notes or a summary section was edited in Obsidian…". Generalise to "Your Notes, a summary section, or the Report section was edited in Obsidian…". One-line change; no new prop.

### No new component

No ScoresPanel-parallel component is needed. PDF export is a side effect, not a new piece of rendered UI on the page.

## Testing

### Backend

`tests/backend/test_export_pdf.py` — unit tests on `build_report_context`:
- Maps a fixture roll + moments + annotations + taxonomy into the expected dict shape.
- Slugifies titles correctly (spaces → `-`, special chars stripped, empty title falls back).
- Buckets scores into low/mid/high by value.
- Converts distribution counts into `{label, width_pct, color}` segments summing to 100%.
- Formats timestamps as `mm:ss`.
- Converts `duration_s` into `mm:ss`.
- Rejects rolls with no summary (raises `ValueError`).

`tests/backend/test_export_pdf.py::test_render_report_pdf_bytes`:
- Happy-path render produces bytes starting with `b"%PDF-"`.
- Sanity check on size: non-trivially large (>5KB) but bounded (<500KB for text-only content).

`tests/backend/test_export_pdf_template.py` — snapshot test on the Jinja-rendered HTML (before PDF conversion):
- Fixture input produces a known HTML string containing key markers (roll title, score values, category labels).
- Uses a stable snapshot file committed to the repo, easy to diff on intentional template changes.

`tests/backend/test_api_export_pdf.py`:
- `POST /export-pdf` on un-finalised roll → 400.
- `POST /export-pdf` on missing roll → 404.
- Happy path → 200, `application/pdf` content type, `Content-Disposition` filename, PDF file exists on disk, markdown has `## Report` section, `vault_summary_hashes['report']` is set.
- Second call with same state → 200 (idempotent), PDF file rewritten (mtime advances; byte-identity isn't guaranteed because the footer embeds a generation timestamp).
- User-edit-then-export → 409, `X-Conflict: report` header, PDF bytes in body, PDF file written to disk, markdown **unchanged**, hash column **unchanged**.
- `?overwrite=1` after 409 → 200, markdown updated to new body, hash column refreshed.
- WeasyPrint failure (monkeypatched to raise) → 502, no partial file on disk.

### Frontend

`web/tests/export-pdf.test.ts`:
- Export button disabled when `roll.summary` is null.
- Export button enabled when `roll.summary` is present.
- Click triggers POST + object URL download (mock `URL.createObjectURL`, assert anchor click fires with expected `download` attribute).
- 409 response opens the conflict dialog and still fires the download.
- "Overwrite" from the dialog retries with `?overwrite=1` and then closes.
- During export, button shows "Exporting…" and is disabled.

### Manual smoke

After implementation:
1. Finalise an existing roll from the M6a smoke set.
2. Click Export PDF → file downloads with expected name, opens in Preview with expected layout.
3. Check `assets/<roll_id>/report.pdf` exists on disk.
4. Check the roll's markdown gained a `## Report` section with the link.
5. Open the markdown in Obsidian; click the link → Obsidian opens the PDF.
6. In Obsidian, edit the `## Report` section's body. Click Export PDF again → conflict dialog fires, Cancel → dialog closes but PDF was downloaded; Overwrite → markdown rewritten.
7. Re-finalise the roll (different Claude output). Click Export PDF → fresh PDF with new scores/summary, same filename, overwritten on disk.

## Dependencies

- `weasyprint` pinned in `pyproject.toml` (latest stable minor at dev time).
- `jinja2` — already a transitive dep of Starlette; pin explicitly to avoid surprise upgrades.
- System: `brew install pango` (macOS) for WeasyPrint's Cairo/Pango backend. Document in README under "Local setup — M6b."

No new npm packages.

## File structure impact

**New files:**

- `tools/bjj-app/server/export/__init__.py` (empty).
- `tools/bjj-app/server/export/pdf.py` (pure helpers).
- `tools/bjj-app/server/export/templates/report.html.j2`.
- `tools/bjj-app/server/export/templates/report.css`.
- `tools/bjj-app/server/api/export_pdf.py` (endpoint — mirrors `api/summarise.py` shape).
- `tools/bjj-app/tests/backend/test_export_pdf.py`.
- `tools/bjj-app/tests/backend/test_export_pdf_template.py`.
- `tools/bjj-app/tests/backend/test_api_export_pdf.py`.
- `tools/bjj-app/web/tests/export-pdf.test.ts`.

**Modified files:**

- `tools/bjj-app/server/analysis/vault_writer.py` — add `"report"` to `_SUMMARY_SECTION_ORDER` and a `render_report_section` helper.
- `tools/bjj-app/server/main.py` — mount the new router.
- `tools/bjj-app/server/db.py` — no schema change. `vault_summary_hashes` already stores arbitrary keys; `"report"` slots in.
- `tools/bjj-app/web/src/lib/api.ts` — new `exportRollPdf` export.
- `tools/bjj-app/web/src/lib/types.ts` — no new top-level type, but add a small `ExportPdfResult` union.
- `tools/bjj-app/web/src/routes/review/[id]/+page.svelte` — new button + handler.
- `tools/bjj-app/web/src/lib/components/PublishConflictDialog.svelte` — copy update to include "Report section."
- `tools/bjj-app/pyproject.toml` — add `weasyprint` dep.
- `tools/bjj-app/README.md` — M6b section (local setup, trigger flow).

## Out of scope (explicitly deferred)

| Deliverable | Why deferred |
|---|---|
| Page 2 (annotated key-moment frames, full annotation transcript, vault back-links) | M6c if Page 1 proves insufficient. Frame extraction at exact key-moment timestamps and embedding them in HTML is its own implementation chunk. |
| Result badge (win/loss/draw) on the masthead | No schema support for it; adding a column is outside M6b's scope. |
| Re-export on Finalise (auto) | User might finalise and then decide not to publish. Keeping the Export step explicit avoids surprise files. |
| Email / share / cloud upload of the PDF | Explicitly out of parent-spec scope. Local-first principle. |
| Dark-theme PDF variant | Single aesthetic keeps the milestone tight. |
| Bulk export (all rolls → one PDF / zip) | No use case. Sharing is per-roll. |
| PDF viewer inline in the app | Obsidian already renders PDFs; so does macOS Preview. No reason to reimplement in the browser. |
