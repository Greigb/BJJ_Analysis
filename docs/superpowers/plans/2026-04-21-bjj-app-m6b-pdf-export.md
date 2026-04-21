# BJJ App M6b — PDF Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a one-click "Export PDF" button that generates a printable, white-paper match report from a finalised roll, saves it to `assets/<roll_id>/report.pdf`, links it from a new `## Report` section in the roll's vault markdown, and streams it back to the browser for download.

**Architecture:** New `server/export/` module (pure helpers + Jinja template + WeasyPrint render). New `POST /api/rolls/:id/export-pdf` endpoint that (1) renders PDF bytes, (2) calls the existing `publish()` to guarantee the vault markdown is current, (3) splices in a new `## Report` section using M6a's per-section hash machinery, (4) atomic-writes the PDF and markdown, (5) streams the PDF as the response.

**Tech Stack:** Python 3.12 + FastAPI + WeasyPrint + Jinja2 for render; SvelteKit + TypeScript for the frontend button; SQLite for the per-section hash state (no new columns — re-uses M6a's `vault_summary_hashes`).

---

## Design refinement captured here (not in the spec)

The spec left the "does the vault file need to exist before Export?" question implicit. This plan commits to: **Export runs `publish()` internally before touching the Report section.** This means:

- Export is gated on `roll.finalised_at` only (spec's "disabled when `!roll.summary`" rule).
- One Export click writes: all summary sections (via publish) + the new `## Report` section + the PDF file on disk + the PDF bytes in the response.
- If `publish()` detects a vault-side edit conflict, Export returns 409 (same dialog as M6a); the PDF bytes are still included in the 409 body so the user at least gets the file.
- No staleness between Finalise and Export — every Export refreshes the full summary in the vault.

If you disagree with this refinement, stop here and discuss before proceeding.

---

## File structure

**New files (backend):**

- `tools/bjj-app/server/export/__init__.py` — empty package marker.
- `tools/bjj-app/server/export/pdf.py` — pure helpers: `format_mm_ss`, `slugify_report_filename`, `build_report_context`, `render_report_pdf`.
- `tools/bjj-app/server/export/templates/report.html.j2` — Jinja template for the rendered HTML.
- `tools/bjj-app/server/export/templates/report.css` — print stylesheet.
- `tools/bjj-app/server/api/export_pdf.py` — FastAPI router with `POST /api/rolls/:id/export-pdf`.

**New files (tests):**

- `tools/bjj-app/tests/backend/test_export_pdf.py` — unit tests for the pure helpers.
- `tools/bjj-app/tests/backend/test_export_pdf_template.py` — HTML snapshot test.
- `tools/bjj-app/tests/backend/test_api_export_pdf.py` — endpoint integration tests.
- `tools/bjj-app/web/tests/export-pdf.test.ts` — frontend button + flow tests.

**Modified files:**

- `tools/bjj-app/pyproject.toml` — add `weasyprint`, `jinja2` to `dependencies`.
- `tools/bjj-app/server/analysis/vault_writer.py` — add `update_report_section` top-level function. The Report section is managed independently by the export endpoint; `publish()` continues to handle summary sections + Your Notes only (no change to `_SUMMARY_SECTION_ORDER`).
- `tools/bjj-app/server/main.py` — mount `export_pdf` router.
- `tools/bjj-app/web/src/lib/api.ts` — add `exportRollPdf`.
- `tools/bjj-app/web/src/lib/types.ts` — add `ExportPdfResult` union type.
- `tools/bjj-app/web/src/routes/review/[id]/+page.svelte` — add Export PDF button + handler.
- `tools/bjj-app/web/src/lib/components/PublishConflictDialog.svelte` — generalise conflict copy to mention the Report section.
- `tools/bjj-app/README.md` — add M6b section (local setup + trigger flow).

---

## Task 1: Add WeasyPrint + Jinja2 dependencies

**Files:**
- Modify: `tools/bjj-app/pyproject.toml`

- [ ] **Step 1: Add the new deps to `pyproject.toml`**

Edit `tools/bjj-app/pyproject.toml`. Locate the `dependencies` list (line 6-16) and add two new entries:

```toml
dependencies = [
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.32.0",
    "aiofiles>=24.1.0",
    "python-frontmatter>=1.1.0",
    "python-multipart>=0.0.12",
    "pydantic>=2.9.0",
    "opencv-python-headless>=4.10.0",
    "mediapipe>=0.10.18",
    "Pillow>=10.4.0",
    "weasyprint>=62.0",
    "jinja2>=3.1.0",
]
```

- [ ] **Step 2: Install the new deps**

Run from `tools/bjj-app/`:

```bash
.venv/bin/pip install -e .
```

Expected: installs `weasyprint` and its transitive deps (`cffi`, `cssselect2`, `tinycss2`, `pydyf`, `fonttools`, etc.) plus `jinja2`. If WeasyPrint complains about missing system libs (Cairo/Pango), run `brew install pango` and retry.

- [ ] **Step 3: Smoke-test the import**

```bash
.venv/bin/python -c "import weasyprint; import jinja2; print('OK')"
```

Expected: prints `OK`. Any import error here means `brew install pango` is still needed.

- [ ] **Step 4: Commit**

```bash
git add tools/bjj-app/pyproject.toml
git commit -m "chore(bjj-app): add weasyprint + jinja2 for M6b PDF export"
```

---

## Task 2: Pure helpers — `format_mm_ss` + `slugify_report_filename` (TDD)

**Files:**
- Create: `tools/bjj-app/server/export/__init__.py` (empty)
- Create: `tools/bjj-app/server/export/pdf.py`
- Create: `tools/bjj-app/tests/backend/test_export_pdf.py`

- [ ] **Step 1: Write the failing tests**

Create `tools/bjj-app/tests/backend/test_export_pdf.py`:

```python
"""Unit tests for M6b PDF export pure helpers."""
from __future__ import annotations

import pytest

from server.export.pdf import (
    format_mm_ss,
    slugify_report_filename,
)


class TestFormatMmSs:
    def test_zero(self):
        assert format_mm_ss(0) == "00:00"

    def test_under_one_minute(self):
        assert format_mm_ss(37) == "00:37"

    def test_exactly_one_minute(self):
        assert format_mm_ss(60) == "01:00"

    def test_several_minutes(self):
        assert format_mm_ss(185) == "03:05"

    def test_accepts_floats_and_truncates(self):
        assert format_mm_ss(62.9) == "01:02"


class TestSlugifyReportFilename:
    def test_simple_title(self):
        assert slugify_report_filename("Tuesday Roll", "2026-04-21") == "tuesday-roll-2026-04-21.pdf"

    def test_lowercases(self):
        assert slugify_report_filename("Hard ROLL", "2026-04-21") == "hard-roll-2026-04-21.pdf"

    def test_strips_special_chars(self):
        assert slugify_report_filename("Roll #3 (comp!)", "2026-04-21") == "roll-3-comp-2026-04-21.pdf"

    def test_collapses_repeats(self):
        assert slugify_report_filename("A   B—C", "2026-04-21") == "a-b-c-2026-04-21.pdf"

    def test_trims_leading_and_trailing(self):
        assert slugify_report_filename("  hello  ", "2026-04-21") == "hello-2026-04-21.pdf"

    def test_empty_title_fallback(self):
        assert slugify_report_filename("", "2026-04-21") == "match-report-2026-04-21.pdf"

    def test_whitespace_only_title_fallback(self):
        assert slugify_report_filename("   ", "2026-04-21") == "match-report-2026-04-21.pdf"
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf.py -v
```

Expected: `ModuleNotFoundError: No module named 'server.export'`.

- [ ] **Step 3: Create the package marker**

Create `tools/bjj-app/server/export/__init__.py` — leave it empty.

- [ ] **Step 4: Implement the helpers**

Create `tools/bjj-app/server/export/pdf.py`:

```python
"""M6b PDF report rendering — pure helpers + WeasyPrint wrapper.

No IO except inside `render_report_pdf`. Tests hit the helpers directly;
rendering gets a smoke test for PDF-magic-number output.
"""
from __future__ import annotations

import re


_SLUG_STRIP_RE = re.compile(r"[^a-z0-9]+")


def format_mm_ss(seconds: float | int) -> str:
    """Format a duration in seconds as `mm:ss` (zero-padded, truncated to int)."""
    total = int(seconds)
    m, s = divmod(total, 60)
    return f"{m:02d}:{s:02d}"


def slugify_report_filename(title: str, date: str) -> str:
    """Return a safe filename like `tuesday-roll-2026-04-21.pdf`.

    Lowercases, strips non-alphanumerics, collapses repeats, and trims leading
    and trailing hyphens. Empty / whitespace-only titles fall back to
    `match-report-<date>.pdf`.
    """
    slug = _SLUG_STRIP_RE.sub("-", title.lower()).strip("-")
    if not slug:
        slug = "match-report"
    return f"{slug}-{date}.pdf"
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf.py -v
```

Expected: all 12 tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/server/export/__init__.py tools/bjj-app/server/export/pdf.py tools/bjj-app/tests/backend/test_export_pdf.py
git commit -m "feat(bjj-app): add format_mm_ss + slugify_report_filename for M6b"
```

---

## Task 3: `build_report_context` pure helper (TDD)

**Files:**
- Modify: `tools/bjj-app/server/export/pdf.py`
- Modify: `tools/bjj-app/tests/backend/test_export_pdf.py`

- [ ] **Step 1: Append the failing tests to `test_export_pdf.py`**

Append to `tools/bjj-app/tests/backend/test_export_pdf.py`:

```python
from datetime import datetime, timezone

from server.export.pdf import build_report_context


def _fixture_taxonomy():
    return {
        "categories": [
            {"id": "guard_top", "label": "Guard top"},
            {"id": "guard_bottom", "label": "Guard bottom"},
            {"id": "standing", "label": "Standing"},
            {"id": "scramble", "label": "Scramble"},
        ],
        "positions": [
            {"id": "closed_guard_bottom", "category": "guard_bottom"},
            {"id": "closed_guard_top", "category": "guard_top"},
        ],
    }


def _fixture_roll(**overrides):
    base = {
        "id": "abcdef1234567890abcdef1234567890",
        "title": "Tuesday Roll",
        "date": "2026-04-21",
        "duration_s": 245.0,
        "player_a_name": "Greig",
        "player_b_name": "Partner",
        "finalised_at": 1713700000,
        "scores_json": None,  # unused — caller passes parsed dict separately
    }
    base.update(overrides)
    return base


def _fixture_scores():
    return {
        "summary": "Solid guard retention but limited offence from the bottom.",
        "scores": {
            "position_control": 7,
            "submission_threat": 3,
            "defensive_resilience": 8,
        },
        "top_improvements": [
            "Chain sweeps from closed guard.",
            "Break grips before shrimping.",
        ],
        "strengths": [
            "Strong guard retention.",
            "Calm under pressure.",
        ],
        "key_moments": [
            {"moment_id": "m1", "why": "First sweep attempt."},
            {"moment_id": "m2", "why": "Passed half guard."},
            {"moment_id": "m3", "why": "Back take attempt."},
        ],
    }


def _fixture_moments():
    return [
        {"id": "m1", "frame_idx": 30, "timestamp_s": 12.5, "category": "guard_bottom"},
        {"id": "m2", "frame_idx": 60, "timestamp_s": 45.0, "category": "guard_top"},
        {"id": "m3", "frame_idx": 90, "timestamp_s": 130.0, "category": "scramble"},
    ]


def _fixture_distribution():
    return {
        "timeline": ["guard_bottom", "guard_top", "scramble"],
        "counts": {"guard_bottom": 1, "guard_top": 1, "scramble": 1},
        "percentages": {"guard_bottom": 33, "guard_top": 34, "scramble": 33},
    }


class TestBuildReportContext:
    def test_flattens_header_fields(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["title"] == "Tuesday Roll"
        assert ctx["date_human"] == "21 April 2026"
        assert ctx["player_a_name"] == "Greig"
        assert ctx["player_b_name"] == "Partner"
        assert ctx["duration_human"] == "04:05"
        assert ctx["moments_analysed_count"] == 3
        assert ctx["summary_sentence"] == "Solid guard retention but limited offence from the bottom."
        assert ctx["generated_at_human"] == "2026-04-21 14:32 UTC"
        assert ctx["roll_id_short"] == "abcdef12"

    def test_scores_are_bucketed_and_widthed(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["scores"] == [
            {"id": "position_control", "label": "Position Control", "value": 7, "bar_pct": 70, "color_bucket": "high"},
            {"id": "submission_threat", "label": "Submission Threat", "value": 3, "bar_pct": 30, "color_bucket": "low"},
            {"id": "defensive_resilience", "label": "Defensive Resilience", "value": 8, "bar_pct": 80, "color_bucket": "high"},
        ]

    def test_distribution_bar_uses_human_labels(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        # Every segment maps category id → human label, carries width + a CSS color variable name.
        labels = {seg["label"]: seg["width_pct"] for seg in ctx["distribution_bar"]}
        assert labels == {"Guard bottom": 33, "Guard top": 34, "Scramble": 33}
        for seg in ctx["distribution_bar"]:
            assert seg["color_class"].startswith("cat-")

    def test_key_moments_resolve_to_mm_ss_and_category_labels(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["key_moments"] == [
            {"timestamp_human": "00:12", "category_label": "Guard bottom", "blurb": "First sweep attempt."},
            {"timestamp_human": "00:45", "category_label": "Guard top", "blurb": "Passed half guard."},
            {"timestamp_human": "02:10", "category_label": "Scramble", "blurb": "Back take attempt."},
        ]

    def test_improvements_and_strengths_passthrough(self):
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=_fixture_scores(),
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert ctx["improvements"] == [
            "Chain sweeps from closed guard.",
            "Break grips before shrimping.",
        ]
        assert ctx["strengths"] == [
            "Strong guard retention.",
            "Calm under pressure.",
        ]

    def test_missing_key_moment_id_is_skipped(self):
        scores = _fixture_scores()
        scores["key_moments"].append({"moment_id": "does-not-exist", "why": "should be dropped"})
        ctx = build_report_context(
            roll=_fixture_roll(),
            scores=scores,
            distribution=_fixture_distribution(),
            moments=_fixture_moments(),
            taxonomy=_fixture_taxonomy(),
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        # Only the three valid moments come through.
        assert len(ctx["key_moments"]) == 3

    def test_raises_when_scores_missing(self):
        with pytest.raises(ValueError, match="scores"):
            build_report_context(
                roll=_fixture_roll(),
                scores=None,
                distribution=_fixture_distribution(),
                moments=_fixture_moments(),
                taxonomy=_fixture_taxonomy(),
                generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
            )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf.py::TestBuildReportContext -v
```

Expected: all 7 tests fail with `ImportError: cannot import name 'build_report_context'`.

- [ ] **Step 3: Implement `build_report_context`**

Append to `tools/bjj-app/server/export/pdf.py`:

```python
from datetime import datetime
from typing import TypedDict


_SCORE_LABEL_BY_ID = {
    "position_control": "Position Control",
    "submission_threat": "Submission Threat",
    "defensive_resilience": "Defensive Resilience",
}


def _bucket_for(value: int) -> str:
    if value < 4:
        return "low"
    if value < 7:
        return "mid"
    return "high"


def build_report_context(
    *,
    roll: dict,
    scores: dict | None,
    distribution: dict,
    moments: list[dict],
    taxonomy: dict,
    generated_at: datetime,
) -> dict:
    """Flatten DB / taxonomy state into the exact shape the Jinja template expects."""
    if scores is None:
        raise ValueError("build_report_context requires a non-null `scores` payload")

    category_label_by_id = {c["id"]: c["label"] for c in taxonomy.get("categories", [])}
    moment_by_id = {m["id"]: m for m in moments}

    # Header
    date_human = datetime.strptime(roll["date"], "%Y-%m-%d").strftime("%d %B %Y").lstrip("0")

    # Scores
    score_rows: list[dict] = []
    for score_id, label in _SCORE_LABEL_BY_ID.items():
        value = int(scores["scores"].get(score_id, 0))
        score_rows.append({
            "id": score_id,
            "label": label,
            "value": value,
            "bar_pct": value * 10,
            "color_bucket": _bucket_for(value),
        })

    # Distribution bar
    percentages = distribution.get("percentages", {})
    distribution_bar: list[dict] = []
    for cat_id, pct in percentages.items():
        distribution_bar.append({
            "category_id": cat_id,
            "label": category_label_by_id.get(cat_id, cat_id.replace("_", " ").capitalize()),
            "width_pct": int(pct),
            "color_class": f"cat-{cat_id.replace('_', '-')}",
        })

    # Key moments — resolve moment_id → (timestamp_s, category)
    key_moments: list[dict] = []
    for km in scores.get("key_moments", []):
        mid = km.get("moment_id")
        m = moment_by_id.get(mid)
        if m is None:
            continue
        key_moments.append({
            "timestamp_human": format_mm_ss(m["timestamp_s"]),
            "category_label": category_label_by_id.get(
                m.get("category") or "scramble",
                (m.get("category") or "scramble").replace("_", " ").capitalize(),
            ),
            "blurb": km.get("why", ""),
        })

    return {
        "title": roll["title"],
        "date_human": date_human,
        "player_a_name": roll["player_a_name"],
        "player_b_name": roll["player_b_name"],
        "duration_human": format_mm_ss(roll.get("duration_s") or 0),
        "moments_analysed_count": len(moments),
        "summary_sentence": scores.get("summary", ""),
        "scores": score_rows,
        "distribution_bar": distribution_bar,
        "improvements": list(scores.get("top_improvements", [])),
        "strengths": list(scores.get("strengths", [])),
        "key_moments": key_moments,
        "generated_at_human": generated_at.strftime("%Y-%m-%d %H:%M UTC"),
        "roll_id_short": roll["id"][:8],
    }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf.py -v
```

Expected: all 19 tests pass (12 from Task 2 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/export/pdf.py tools/bjj-app/tests/backend/test_export_pdf.py
git commit -m "feat(bjj-app): add build_report_context for M6b PDF rendering"
```

---

## Task 4: Jinja template + CSS (HTML snapshot test)

**Files:**
- Create: `tools/bjj-app/server/export/templates/report.html.j2`
- Create: `tools/bjj-app/server/export/templates/report.css`
- Create: `tools/bjj-app/tests/backend/test_export_pdf_template.py`

- [ ] **Step 1: Write the failing snapshot test**

Create `tools/bjj-app/tests/backend/test_export_pdf_template.py`:

```python
"""Snapshot test for the M6b Jinja HTML template.

The test passes a known context through the template and asserts on key
markers. If the template changes intentionally, update the asserted strings.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import jinja2


TEMPLATE_DIR = Path(__file__).resolve().parents[2] / "server" / "export" / "templates"


def _render(context: dict) -> str:
    env = jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(TEMPLATE_DIR)),
        autoescape=True,
    )
    return env.get_template("report.html.j2").render(**context)


def _fixture_context():
    return {
        "title": "Tuesday Roll",
        "date_human": "21 April 2026",
        "player_a_name": "Greig",
        "player_b_name": "Partner",
        "duration_human": "04:05",
        "moments_analysed_count": 3,
        "summary_sentence": "Solid guard retention but limited offence.",
        "scores": [
            {"id": "position_control", "label": "Position Control", "value": 7, "bar_pct": 70, "color_bucket": "high"},
            {"id": "submission_threat", "label": "Submission Threat", "value": 3, "bar_pct": 30, "color_bucket": "low"},
            {"id": "defensive_resilience", "label": "Defensive Resilience", "value": 8, "bar_pct": 80, "color_bucket": "high"},
        ],
        "distribution_bar": [
            {"category_id": "guard_bottom", "label": "Guard bottom", "width_pct": 33, "color_class": "cat-guard-bottom"},
            {"category_id": "guard_top", "label": "Guard top", "width_pct": 34, "color_class": "cat-guard-top"},
            {"category_id": "scramble", "label": "Scramble", "width_pct": 33, "color_class": "cat-scramble"},
        ],
        "improvements": ["Chain sweeps.", "Break grips early."],
        "strengths": ["Strong retention.", "Calm under pressure."],
        "key_moments": [
            {"timestamp_human": "00:12", "category_label": "Guard bottom", "blurb": "First sweep attempt."},
            {"timestamp_human": "00:45", "category_label": "Guard top", "blurb": "Passed half guard."},
            {"timestamp_human": "02:10", "category_label": "Scramble", "blurb": "Back take attempt."},
        ],
        "generated_at_human": "2026-04-21 14:32 UTC",
        "roll_id_short": "abcdef12",
    }


def test_template_renders_title_and_subtitle():
    html = _render(_fixture_context())
    assert "Tuesday Roll" in html
    assert "Greig vs Partner" in html
    assert "04:05" in html
    assert "3 moments analysed" in html


def test_template_renders_summary_sentence():
    html = _render(_fixture_context())
    assert "Solid guard retention" in html


def test_template_renders_three_score_boxes_with_buckets():
    html = _render(_fixture_context())
    assert 'class="score-box bucket-high"' in html  # first score
    assert 'class="score-box bucket-low"' in html   # second score
    # Values and labels both appear.
    assert ">7<" in html
    assert "Position Control" in html
    # Bar width is present as inline style.
    assert "width: 70%" in html


def test_template_renders_distribution_segments():
    html = _render(_fixture_context())
    assert 'class="dist-seg cat-guard-bottom"' in html
    assert "width: 33%" in html
    # Segment label appears inline.
    assert "Guard bottom 33%" in html


def test_template_renders_improvements_as_ordered_list():
    html = _render(_fixture_context())
    # Ordered list for improvements, unordered for strengths.
    assert "<ol" in html and "Chain sweeps." in html
    assert "<ul" in html and "Strong retention." in html


def test_template_renders_key_moments_table_rows():
    html = _render(_fixture_context())
    assert "<td" in html
    assert "00:12" in html
    assert "Guard bottom" in html
    assert "First sweep attempt." in html


def test_template_renders_footer():
    html = _render(_fixture_context())
    assert "2026-04-21 14:32 UTC" in html
    assert "abcdef12" in html
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf_template.py -v
```

Expected: all 7 tests fail with `TemplateNotFound: report.html.j2`.

- [ ] **Step 3: Create the template**

Create directory `tools/bjj-app/server/export/templates/` (if not present).

Create `tools/bjj-app/server/export/templates/report.html.j2`:

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>{{ title }} — Match Report</title>
  <link rel="stylesheet" href="report.css">
</head>
<body>

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
    <div class="dist-seg {{ seg.color_class }}" style="width: {{ seg.width_pct }}%;">
      <span class="dist-label">{{ seg.label }} {{ seg.width_pct }}%</span>
    </div>
    {% endfor %}
  </div>
</section>

<section class="improvements">
  <h2>Top improvements</h2>
  <ol>
    {% for imp in improvements %}<li>{{ imp }}</li>{% endfor %}
  </ol>
</section>

<section class="strengths">
  <h2>Strengths observed</h2>
  <ul>
    {% for s in strengths %}<li>{{ s }}</li>{% endfor %}
  </ul>
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

</body>
</html>
```

- [ ] **Step 4: Create the stylesheet**

Create `tools/bjj-app/server/export/templates/report.css`:

```css
@page {
  size: A4 portrait;
  margin: 20mm;
}

* { box-sizing: border-box; }

body {
  font-family: -apple-system, system-ui, "Segoe UI", sans-serif;
  font-size: 11pt;
  line-height: 1.45;
  color: #222;
  margin: 0;
}

h1, h2 {
  font-family: Georgia, "Times New Roman", serif;
  font-weight: 600;
  margin: 0;
}

.masthead {
  display: flex;
  justify-content: space-between;
  align-items: baseline;
  border-bottom: 0.5pt solid #999;
  padding-bottom: 4pt;
  font-family: Georgia, serif;
  font-variant: small-caps;
  letter-spacing: 0.5pt;
  font-size: 9pt;
  color: #555;
}

.title-block { margin-top: 14pt; }
.title-block h1 { font-size: 22pt; letter-spacing: -0.2pt; }
.subtitle { font-size: 10pt; color: #666; margin-top: 2pt; }

.summary { margin-top: 12pt; text-align: center; }
.summary p { font-style: italic; font-size: 12pt; margin: 0; }

.scores {
  display: flex;
  gap: 10pt;
  margin-top: 16pt;
}
.score-box {
  flex: 1;
  border: 0.5pt solid #ccc;
  border-radius: 4pt;
  padding: 10pt;
}
.score-label { font-size: 9pt; color: #666; text-transform: uppercase; letter-spacing: 0.5pt; }
.score-value { font-family: Georgia, serif; font-size: 28pt; font-weight: 600; line-height: 1.1; }
.score-value span { font-size: 12pt; color: #888; font-weight: 400; }
.score-bar { height: 4pt; background: #eee; border-radius: 2pt; margin-top: 6pt; overflow: hidden; }
.score-bar .fill { height: 100%; border-radius: 2pt; }
.bucket-low  .fill { background: #b6413a; }
.bucket-mid  .fill { background: #c18a2b; }
.bucket-high .fill { background: #3f8a4b; }

.distribution { margin-top: 18pt; }
.distribution h2 { font-size: 11pt; margin-bottom: 4pt; }
.dist-bar {
  display: flex;
  height: 22pt;
  border-radius: 3pt;
  overflow: hidden;
  border: 0.5pt solid #ccc;
}
.dist-seg {
  display: flex;
  align-items: center;
  justify-content: flex-start;
  padding: 0 4pt;
  color: #fff;
  font-size: 8pt;
  white-space: nowrap;
  overflow: hidden;
}
/* Muted print-friendly category hues, ~40% saturation drop from the app palette. */
.cat-standing      { background: #8a8aa0; }
.cat-guard-top     { background: #5a7ea0; }
.cat-guard-bottom  { background: #a07a5a; }
.cat-dominant      { background: #5a8a5a; }
.cat-inferior      { background: #a05a5a; }
.cat-leg-ent       { background: #8a6aa0; }
.cat-scramble      { background: #a09a5a; }
.cat-pass          { background: #6a8aa0; }
.cat-submission    { background: #a05a7a; }

.improvements, .strengths, .key-moments { margin-top: 16pt; }
.improvements h2, .strengths h2, .key-moments h2 { font-size: 11pt; margin-bottom: 4pt; }
.improvements ol, .strengths ul { margin: 0; padding-left: 18pt; }
.improvements li, .strengths li { margin-bottom: 3pt; }

.key-moments table { width: 100%; border-collapse: collapse; }
.key-moments td { padding: 4pt 6pt; border-bottom: 0.25pt solid #eee; vertical-align: top; font-size: 10pt; }
.key-moments td.ts { font-family: Georgia, serif; font-weight: 600; white-space: nowrap; width: 48pt; }
.key-moments td.cat { color: #666; white-space: nowrap; width: 90pt; }

.footer-strip {
  margin-top: 20pt;
  padding-top: 4pt;
  border-top: 0.5pt solid #999;
  font-size: 8pt;
  color: #777;
  text-align: right;
}
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf_template.py -v
```

Expected: all 7 tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/server/export/templates/report.html.j2 tools/bjj-app/server/export/templates/report.css tools/bjj-app/tests/backend/test_export_pdf_template.py
git commit -m "feat(bjj-app): add M6b Jinja template + print CSS"
```

---

## Task 5: `render_report_pdf` WeasyPrint wrapper (smoke test)

**Files:**
- Modify: `tools/bjj-app/server/export/pdf.py`
- Modify: `tools/bjj-app/tests/backend/test_export_pdf.py`

- [ ] **Step 1: Append the failing smoke test**

Append to `tools/bjj-app/tests/backend/test_export_pdf.py`:

```python
from datetime import datetime, timezone

from server.export.pdf import render_report_pdf


def _render_fixture_context():
    return {
        "title": "Tuesday Roll",
        "date_human": "21 April 2026",
        "player_a_name": "Greig",
        "player_b_name": "Partner",
        "duration_human": "04:05",
        "moments_analysed_count": 3,
        "summary_sentence": "Solid guard retention but limited offence.",
        "scores": [
            {"id": "position_control", "label": "Position Control", "value": 7, "bar_pct": 70, "color_bucket": "high"},
            {"id": "submission_threat", "label": "Submission Threat", "value": 3, "bar_pct": 30, "color_bucket": "low"},
            {"id": "defensive_resilience", "label": "Defensive Resilience", "value": 8, "bar_pct": 80, "color_bucket": "high"},
        ],
        "distribution_bar": [
            {"category_id": "guard_bottom", "label": "Guard bottom", "width_pct": 50, "color_class": "cat-guard-bottom"},
            {"category_id": "guard_top", "label": "Guard top", "width_pct": 50, "color_class": "cat-guard-top"},
        ],
        "improvements": ["Chain sweeps."],
        "strengths": ["Strong retention."],
        "key_moments": [
            {"timestamp_human": "00:12", "category_label": "Guard bottom", "blurb": "First sweep attempt."},
        ],
        "generated_at_human": "2026-04-21 14:32 UTC",
        "roll_id_short": "abcdef12",
    }


class TestRenderReportPdf:
    def test_produces_pdf_magic_number(self):
        pdf_bytes = render_report_pdf(_render_fixture_context())
        assert pdf_bytes.startswith(b"%PDF-")

    def test_size_is_reasonable(self):
        pdf_bytes = render_report_pdf(_render_fixture_context())
        # Text-only Page 1 PDFs are typically 8-50KB; give a wide bound.
        assert 3_000 < len(pdf_bytes) < 500_000
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf.py::TestRenderReportPdf -v
```

Expected: both tests fail with `ImportError: cannot import name 'render_report_pdf'`.

- [ ] **Step 3: Implement `render_report_pdf`**

Append to `tools/bjj-app/server/export/pdf.py`:

```python
from pathlib import Path

import jinja2
from weasyprint import CSS, HTML


_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"


def _jinja_env() -> jinja2.Environment:
    return jinja2.Environment(
        loader=jinja2.FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )


def render_report_pdf(context: dict) -> bytes:
    """Render the Jinja template to HTML, then to a PDF byte string."""
    env = _jinja_env()
    html = env.get_template("report.html.j2").render(**context)
    css = CSS(filename=str(_TEMPLATE_DIR / "report.css"))
    return HTML(string=html, base_url=str(_TEMPLATE_DIR)).write_pdf(stylesheets=[css])
```

- [ ] **Step 4: Run the smoke tests**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf.py::TestRenderReportPdf -v
```

Expected: both tests pass.

- [ ] **Step 5: Run the full export-pdf test file to confirm no regressions**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf.py tests/backend/test_export_pdf_template.py -v
```

Expected: all tests pass (19 from Tasks 2-3 + 7 from Task 4 + 2 new = 28 total).

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/server/export/pdf.py tools/bjj-app/tests/backend/test_export_pdf.py
git commit -m "feat(bjj-app): add render_report_pdf (WeasyPrint wrapper)"
```

---

## Task 6: Extend `vault_writer` with the `## Report` section (TDD)

**Files:**
- Modify: `tools/bjj-app/server/analysis/vault_writer.py`
- Create: `tools/bjj-app/tests/backend/test_vault_writer_report.py`

The goal: add a top-level `update_report_section(conn, *, roll_id, vault_root, body, force) -> str` that splices the `## Report` section into an existing roll markdown, applies the per-section hash check, writes atomically, and updates `vault_summary_hashes['report']`. Returns the new hash.

- [ ] **Step 1: Write the failing tests**

Create `tools/bjj-app/tests/backend/test_vault_writer_report.py`:

```python
"""Tests for M6b vault_writer.update_report_section."""
from __future__ import annotations

import sqlite3

import pytest

from server.analysis.vault_writer import (
    ConflictError,
    update_report_section,
)
from server.db import (
    connect,
    create_roll,
    init_db,
    set_summary_state,
    set_vault_state,
    set_vault_summary_hashes,
)


def _setup_roll(tmp_path, *, with_vault_file=True):
    db_path = tmp_path / "db.sqlite"
    init_db(db_path)
    conn = connect(db_path)

    roll_id = "abcdef1234567890abcdef1234567890"
    create_roll(
        conn,
        id=roll_id,
        title="Tuesday Roll",
        date="2026-04-21",
        video_path="assets/x/source.mp4",
        duration_s=245.0,
        partner=None,
        result="unknown",
        created_at=1713700000,
        player_a_name="Greig",
        player_b_name="Partner",
    )
    set_summary_state(
        conn,
        roll_id=roll_id,
        scores_payload={
            "summary": "s",
            "scores": {"position_control": 7, "submission_threat": 3, "defensive_resilience": 8},
            "top_improvements": ["a"],
            "strengths": ["b"],
            "key_moments": [],
        },
        finalised_at=1713700100,
    )

    vault_root = tmp_path / "vault"
    (vault_root / "Roll Log").mkdir(parents=True)
    vault_path = f"Roll Log/2026-04-21 - Tuesday Roll.md"

    if with_vault_file:
        (vault_root / vault_path).write_text(
            "---\ntitle: Tuesday Roll\n---\n\n"
            "## Summary\n\nsomething\n\n"
            "## Your Notes\n\n(none)\n",
            encoding="utf-8",
        )
        set_vault_state(
            conn,
            roll_id=roll_id,
            vault_path=vault_path,
            vault_your_notes_hash="abc",
            vault_published_at=1713700200,
        )
        set_vault_summary_hashes(conn, roll_id=roll_id, hashes={"summary": "h1"})

    return conn, roll_id, vault_root


def test_inserts_report_section_when_absent(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path)

    new_hash = update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="[[assets/xxx/report.pdf|Match report PDF]]\n\n*Generated now*",
        force=False,
    )

    assert isinstance(new_hash, str) and len(new_hash) > 0
    text = (vault_root / "Roll Log" / "2026-04-21 - Tuesday Roll.md").read_text()
    # Report section appears after strengths order (or wherever ordered-insert lands it)
    assert "## Report" in text
    assert "Match report PDF" in text


def test_hash_persisted_to_vault_summary_hashes(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path)
    new_hash = update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="[[assets/xxx/report.pdf|Match report PDF]]",
        force=False,
    )
    row = conn.execute(
        "SELECT vault_summary_hashes FROM rolls WHERE id = ?", (roll_id,)
    ).fetchone()
    import json
    stored = json.loads(row["vault_summary_hashes"])
    assert stored["report"] == new_hash


def test_replaces_existing_report_body(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path)
    # First export — inserts.
    update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="first body",
        force=False,
    )
    # Second export — replaces.
    second_hash = update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="second body",
        force=False,
    )
    text = (vault_root / "Roll Log" / "2026-04-21 - Tuesday Roll.md").read_text()
    assert "second body" in text
    assert "first body" not in text


def test_raises_conflict_when_user_edited(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path)
    update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="original",
        force=False,
    )
    vault_file = vault_root / "Roll Log" / "2026-04-21 - Tuesday Roll.md"
    text = vault_file.read_text()
    # Simulate user edit in Obsidian.
    vault_file.write_text(text.replace("original", "user hand edit"), encoding="utf-8")

    with pytest.raises(ConflictError):
        update_report_section(
            conn,
            roll_id=roll_id,
            vault_root=vault_root,
            body="new body",
            force=False,
        )


def test_force_overwrites_conflict(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path)
    update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="original",
        force=False,
    )
    vault_file = vault_root / "Roll Log" / "2026-04-21 - Tuesday Roll.md"
    vault_file.write_text(
        vault_file.read_text().replace("original", "user edit"),
        encoding="utf-8",
    )

    update_report_section(
        conn,
        roll_id=roll_id,
        vault_root=vault_root,
        body="fresh body",
        force=True,
    )
    assert "fresh body" in vault_file.read_text()
    assert "user edit" not in vault_file.read_text()


def test_raises_when_vault_file_missing(tmp_path):
    conn, roll_id, vault_root = _setup_roll(tmp_path, with_vault_file=False)
    with pytest.raises(FileNotFoundError):
        update_report_section(
            conn,
            roll_id=roll_id,
            vault_root=vault_root,
            body="body",
            force=False,
        )
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_vault_writer_report.py -v
```

Expected: all 6 tests fail with `ImportError: cannot import name 'update_report_section'`.

- [ ] **Step 3: Implement `update_report_section`**

The Report section is intentionally **not** added to `_SUMMARY_SECTION_ORDER` — that list is the set of sections managed by `publish()`. The Report section is managed independently by `update_report_section`, which handles its own conflict check and its own positioning (inserted just before `## Your Notes` when absent).



Append to `tools/bjj-app/server/analysis/vault_writer.py` (near the bottom, after `publish`):

```python
def update_report_section(
    conn,
    *,
    roll_id: str,
    vault_root: Path,
    body: str,
    force: bool = False,
) -> str:
    """Splice/insert the `## Report` section into a roll's existing markdown.

    Assumes the roll has been published at least once (vault file exists).
    Raises `FileNotFoundError` if the vault file is missing.
    Raises `ConflictError` if the current `## Report` body hash doesn't match
    `vault_summary_hashes['report']` and `force=False`.
    On success returns the new hash and persists it to `vault_summary_hashes`.
    """
    import json as _json

    roll_row = get_roll(conn, roll_id)
    if roll_row is None:
        raise LookupError(f"Roll not found: {roll_id}")

    vault_state = get_vault_state(conn, roll_id)
    if vault_state is None or not vault_state.get("vault_path"):
        raise FileNotFoundError(
            f"Roll {roll_id} has not been published to the vault — Save to Vault first."
        )

    target = vault_root / vault_state["vault_path"]
    _assert_under_roll_log(target, vault_root)
    if not target.exists():
        raise FileNotFoundError(f"Vault file missing on disk: {target}")

    current_text = target.read_text(encoding="utf-8")

    # Conflict check against stored per-section hash.
    stored_summary_hashes: dict[str, str] = {}
    if roll_row["vault_summary_hashes"]:
        stored_summary_hashes = _json.loads(roll_row["vault_summary_hashes"]) or {}
    current_body = _extract_section_by_heading(current_text, "## Report")
    current_hash = _hash_section(current_body)
    stored_hash = stored_summary_hashes.get("report")
    if stored_hash is not None and current_hash != stored_hash and not force:
        raise ConflictError(current_hash=current_hash, stored_hash=stored_hash)

    # Splice or insert.
    replaced = _replace_section_body_if_present(current_text, "## Report", body)
    if replaced is not None:
        new_text = replaced
    else:
        # Report sits just above Your Notes (after all summary sections).
        new_text = _insert_section_at_ordered_position(
            current_text, "## Report", body, [_YOUR_NOTES_HEADING]
        )

    _atomic_write(target, new_text)

    new_hash = _hash_section(body)
    stored_summary_hashes["report"] = new_hash
    set_vault_summary_hashes(conn, roll_id=roll_id, hashes=stored_summary_hashes)
    return new_hash
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_vault_writer_report.py -v
```

Expected: all 6 tests pass.

- [ ] **Step 5: Run the full vault_writer test suite to confirm no regressions**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_vault_writer_summary.py tests/backend/test_vault_writer_report.py -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/server/analysis/vault_writer.py tools/bjj-app/tests/backend/test_vault_writer_report.py
git commit -m "feat(bjj-app): extend vault_writer with ## Report section (M6b)"
```

---

## Task 7: Render helper — `render_report_section_body` (TDD)

**Files:**
- Modify: `tools/bjj-app/server/export/pdf.py`
- Modify: `tools/bjj-app/tests/backend/test_export_pdf.py`

A small helper that returns the string body for the `## Report` section — extracted so the API endpoint doesn't inline the markdown format.

- [ ] **Step 1: Write failing tests**

Append to `tools/bjj-app/tests/backend/test_export_pdf.py`:

```python
from server.export.pdf import render_report_section_body


class TestRenderReportSectionBody:
    def test_contains_obsidian_link(self):
        body = render_report_section_body(
            roll_id="abcdef1234567890abcdef1234567890",
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert "[[assets/abcdef1234567890abcdef1234567890/report.pdf|Match report PDF]]" in body

    def test_contains_generated_at(self):
        body = render_report_section_body(
            roll_id="abcdef1234567890abcdef1234567890",
            generated_at=datetime(2026, 4, 21, 14, 32, tzinfo=timezone.utc),
        )
        assert "*Generated 2026-04-21 14:32 UTC*" in body
```

- [ ] **Step 2: Run to verify fail**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf.py::TestRenderReportSectionBody -v
```

Expected: both fail with ImportError.

- [ ] **Step 3: Implement**

Append to `tools/bjj-app/server/export/pdf.py`:

```python
def render_report_section_body(*, roll_id: str, generated_at: datetime) -> str:
    """Return the markdown body for the `## Report` section.

    Shape: Obsidian wikilink to the PDF, blank line, italic timestamp.
    """
    stamp = generated_at.strftime("%Y-%m-%d %H:%M UTC")
    return (
        f"[[assets/{roll_id}/report.pdf|Match report PDF]]\n"
        f"\n"
        f"*Generated {stamp}*"
    )
```

- [ ] **Step 4: Run to verify pass**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_export_pdf.py -v
```

Expected: all tests pass (total now 30 in this file: 28 from earlier + 2 new).

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/export/pdf.py tools/bjj-app/tests/backend/test_export_pdf.py
git commit -m "feat(bjj-app): add render_report_section_body helper"
```

---

## Task 8: API endpoint tests (failing — no impl)

**Files:**
- Create: `tools/bjj-app/tests/backend/test_api_export_pdf.py`

- [ ] **Step 1: Write failing endpoint tests**

Create `tools/bjj-app/tests/backend/test_api_export_pdf.py`:

```python
"""Integration tests for POST /api/rolls/:id/export-pdf."""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from server.db import (
    connect,
    create_roll,
    init_db,
    insert_analysis,
    insert_moment,
    set_summary_state,
)
from server.main import create_app


def _finalised_roll(conn, roll_id: str) -> None:
    create_roll(
        conn,
        id=roll_id,
        title="Tuesday Roll",
        date="2026-04-21",
        video_path=f"assets/{roll_id}/source.mp4",
        duration_s=245.0,
        partner=None,
        result="unknown",
        created_at=1713700000,
        player_a_name="Greig",
        player_b_name="Partner",
    )
    m_id = "m-001"
    insert_moment(conn, id=m_id, roll_id=roll_id, frame_idx=30, timestamp_s=12.5, pose_delta=0.1)
    insert_analysis(
        conn,
        id="a-001",
        moment_id=m_id,
        player="a",
        position_id="closed_guard_bottom",
        confidence=0.9,
        description=None,
        coach_tip=None,
    )
    set_summary_state(
        conn,
        roll_id=roll_id,
        scores_payload={
            "summary": "Solid guard retention.",
            "scores": {"position_control": 7, "submission_threat": 3, "defensive_resilience": 8},
            "top_improvements": ["a"],
            "strengths": ["b"],
            "key_moments": [{"moment_id": m_id, "why": "First sweep."}],
        },
        finalised_at=1713700100,
    )


@pytest.fixture
def client(tmp_path, monkeypatch):
    # point env at tmp paths
    monkeypatch.setenv("BJJ_DB_PATH", str(tmp_path / "db.sqlite"))
    monkeypatch.setenv("BJJ_VAULT_ROOT", str(tmp_path / "vault"))
    monkeypatch.setenv("BJJ_PROJECT_ROOT", str(tmp_path))
    (tmp_path / "vault" / "Roll Log").mkdir(parents=True)
    (tmp_path / "assets").mkdir()
    init_db(tmp_path / "db.sqlite")
    app = create_app()
    with TestClient(app) as c:
        yield c, tmp_path


class TestExportPdfEndpoint:
    def test_400_when_not_finalised(self, client):
        c, root = client
        roll_id = "abcdef1234567890abcdef1234567890"
        # Create a roll that is NOT finalised.
        conn = connect(root / "db.sqlite")
        create_roll(
            conn,
            id=roll_id,
            title="t",
            date="2026-04-21",
            video_path=f"assets/{roll_id}/source.mp4",
            duration_s=10.0,
            partner=None,
            result="unknown",
            created_at=1713700000,
            player_a_name="A",
            player_b_name="B",
        )
        conn.close()
        r = c.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r.status_code == 400
        assert "finalised" in r.json()["detail"].lower()

    def test_404_when_roll_missing(self, client):
        c, _ = client
        r = c.post("/api/rolls/does-not-exist/export-pdf")
        assert r.status_code == 404

    def test_happy_path_writes_pdf_and_markdown(self, client):
        c, root = client
        roll_id = "abcdef1234567890abcdef1234567890"
        conn = connect(root / "db.sqlite")
        _finalised_roll(conn, roll_id)
        conn.close()

        r = c.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r.status_code == 200, r.text
        assert r.headers["content-type"] == "application/pdf"
        assert "attachment" in r.headers["content-disposition"]
        assert r.content.startswith(b"%PDF-")

        # PDF file exists on disk
        assert (root / "assets" / roll_id / "report.pdf").exists()

        # Markdown has ## Report section
        md_files = list((root / "vault" / "Roll Log").glob("*.md"))
        assert md_files, "Expected a Roll Log markdown file to be created"
        md = md_files[0].read_text(encoding="utf-8")
        assert "## Report" in md
        assert f"[[assets/{roll_id}/report.pdf|Match report PDF]]" in md

        # Hash persisted
        conn = connect(root / "db.sqlite")
        row = conn.execute(
            "SELECT vault_summary_hashes FROM rolls WHERE id = ?", (roll_id,)
        ).fetchone()
        conn.close()
        hashes = json.loads(row["vault_summary_hashes"])
        assert "report" in hashes

    def test_second_call_is_idempotent(self, client):
        c, root = client
        roll_id = "abcdef1234567890abcdef1234567890"
        conn = connect(root / "db.sqlite")
        _finalised_roll(conn, roll_id)
        conn.close()

        r1 = c.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r1.status_code == 200
        r2 = c.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r2.status_code == 200
        # PDF file rewritten (mtime differs or at minimum exists).
        assert (root / "assets" / roll_id / "report.pdf").exists()

    def test_409_on_user_edited_report_section(self, client):
        c, root = client
        roll_id = "abcdef1234567890abcdef1234567890"
        conn = connect(root / "db.sqlite")
        _finalised_roll(conn, roll_id)
        conn.close()

        r1 = c.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r1.status_code == 200

        # Simulate user hand-edit in Obsidian.
        md_files = list((root / "vault" / "Roll Log").glob("*.md"))
        md_path = md_files[0]
        md_text = md_path.read_text(encoding="utf-8")
        assert "Match report PDF" in md_text
        md_path.write_text(md_text.replace("Match report PDF", "USER HAND EDIT"), encoding="utf-8")

        r2 = c.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r2.status_code == 409
        assert r2.headers.get("x-conflict") == "report"
        # PDF body still returned
        assert r2.content.startswith(b"%PDF-")
        # PDF file still written
        assert (root / "assets" / roll_id / "report.pdf").exists()
        # Markdown NOT overwritten
        assert "USER HAND EDIT" in md_path.read_text(encoding="utf-8")

    def test_overwrite_query_resolves_conflict(self, client):
        c, root = client
        roll_id = "abcdef1234567890abcdef1234567890"
        conn = connect(root / "db.sqlite")
        _finalised_roll(conn, roll_id)
        conn.close()

        c.post(f"/api/rolls/{roll_id}/export-pdf")
        md_files = list((root / "vault" / "Roll Log").glob("*.md"))
        md_path = md_files[0]
        md_path.write_text(
            md_path.read_text(encoding="utf-8").replace("Match report PDF", "USER EDIT"),
            encoding="utf-8",
        )

        r = c.post(f"/api/rolls/{roll_id}/export-pdf?overwrite=1")
        assert r.status_code == 200
        assert "Match report PDF" in md_path.read_text(encoding="utf-8")

    def test_502_when_weasyprint_raises(self, client, monkeypatch):
        c, root = client
        roll_id = "abcdef1234567890abcdef1234567890"
        conn = connect(root / "db.sqlite")
        _finalised_roll(conn, roll_id)
        conn.close()

        def _boom(ctx):  # noqa: ARG001
            raise RuntimeError("synthetic weasyprint failure")

        monkeypatch.setattr("server.api.export_pdf.render_report_pdf", _boom)
        r = c.post(f"/api/rolls/{roll_id}/export-pdf")
        assert r.status_code == 502
        # PDF file NOT written
        assert not (root / "assets" / roll_id / "report.pdf").exists()

    def test_filename_slugified(self, client):
        c, root = client
        roll_id = "abcdef1234567890abcdef1234567890"
        conn = connect(root / "db.sqlite")
        _finalised_roll(conn, roll_id)
        conn.close()

        r = c.post(f"/api/rolls/{roll_id}/export-pdf")
        cd = r.headers["content-disposition"]
        assert "tuesday-roll-2026-04-21.pdf" in cd
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_api_export_pdf.py -v
```

Expected: tests fail on import (endpoint module doesn't exist yet) — `ModuleNotFoundError: No module named 'server.api.export_pdf'` after the app mounts routers, OR a 404 on the endpoint path if the module is imported but not wired. Either way, the 8 tests should fail.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tools/bjj-app/tests/backend/test_api_export_pdf.py
git commit -m "test(bjj-app): add export-pdf API tests (failing — no impl)"
```

---

## Task 9: API endpoint implementation

**Files:**
- Create: `tools/bjj-app/server/api/export_pdf.py`
- Modify: `tools/bjj-app/server/main.py`

- [ ] **Step 1: Write the endpoint**

Create `tools/bjj-app/server/api/export_pdf.py`:

```python
"""POST /api/rolls/:id/export-pdf — render and deliver the match report PDF."""
from __future__ import annotations

import json as _json
import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from server.analysis.summarise import compute_distribution
from server.analysis.vault_writer import (
    ConflictError,
    publish as vault_publish,
    update_report_section,
)
from server.config import Settings, load_settings
from server.db import (
    connect,
    get_analyses,
    get_moments,
    get_roll,
)
from server.export.pdf import (
    build_report_context,
    render_report_pdf,
    render_report_section_body,
    slugify_report_filename,
)

router = APIRouter(prefix="/api", tags=["export_pdf"])


@router.post("/rolls/{roll_id}/export-pdf")
def export_roll_pdf(
    roll_id: str,
    request: Request,
    overwrite: int = 0,
    settings: Settings = Depends(load_settings),
) -> Response:
    force = bool(overwrite)
    taxonomy = getattr(request.app.state, "taxonomy", None) or {"categories": [], "positions": []}

    # ---------- 1. Load roll + validate ----------
    conn = connect(settings.db_path)
    try:
        roll_row = get_roll(conn, roll_id)
        if roll_row is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Roll not found."
            )
        if roll_row["scores_json"] is None or roll_row["finalised_at"] is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Roll must be finalised before export.",
            )

        scores_payload = _json.loads(roll_row["scores_json"])
        moment_rows = [dict(m) for m in get_moments(conn, roll_id)]
        position_to_category = {p["id"]: p["category"] for p in taxonomy.get("positions", [])}
        flat_analyses: list[dict] = []
        for m in moment_rows:
            for a in get_analyses(conn, m["id"]):
                flat_analyses.append({
                    "position_id": a["position_id"],
                    "player": a["player"],
                    "timestamp_s": m["timestamp_s"],
                    "category": position_to_category.get(a["position_id"], "scramble"),
                })
        distribution = compute_distribution(flat_analyses, taxonomy.get("categories", []))

        # Moments with category for key-moment resolution.
        moments_with_cat = [
            {
                "id": m["id"],
                "frame_idx": m["frame_idx"],
                "timestamp_s": m["timestamp_s"],
                # Use the first analysis's category if any.
                "category": next(
                    (
                        position_to_category.get(a["position_id"], "scramble")
                        for a in get_analyses(conn, m["id"])
                    ),
                    "scramble",
                ),
            }
            for m in moment_rows
        ]
    finally:
        conn.close()

    # ---------- 2. Build context + render PDF in memory ----------
    generated_at = datetime.now(timezone.utc)
    context = build_report_context(
        roll=dict(roll_row),
        scores=scores_payload,
        distribution=distribution,
        moments=moments_with_cat,
        taxonomy=taxonomy,
        generated_at=generated_at,
    )

    try:
        pdf_bytes = render_report_pdf(context)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"PDF rendering failed: {exc}",
        )

    # ---------- 3. Ensure vault is up to date (publish), then update Report ----------
    conflict_headers: dict[str, str] = {}
    report_body = render_report_section_body(roll_id=roll_id, generated_at=generated_at)
    conn = connect(settings.db_path)
    try:
        try:
            vault_publish(
                conn,
                roll_id=roll_id,
                vault_root=settings.vault_root,
                force=force,
                taxonomy=taxonomy,
            )
        except ConflictError:
            conflict_headers["X-Conflict"] = "report"

        if "X-Conflict" not in conflict_headers:
            try:
                update_report_section(
                    conn,
                    roll_id=roll_id,
                    vault_root=settings.vault_root,
                    body=report_body,
                    force=force,
                )
            except ConflictError:
                conflict_headers["X-Conflict"] = "report"
    finally:
        conn.close()

    # ---------- 4. Atomic-write the PDF file regardless of conflict state ----------
    pdf_dir: Path = settings.project_root / "assets" / roll_id
    pdf_dir.mkdir(parents=True, exist_ok=True)
    final_path = pdf_dir / "report.pdf"
    tmp_path = pdf_dir / "report.pdf.tmp"
    tmp_path.write_bytes(pdf_bytes)
    os.replace(tmp_path, final_path)

    # ---------- 5. Return PDF bytes ----------
    filename = slugify_report_filename(roll_row["title"], roll_row["date"])
    status_code = status.HTTP_409_CONFLICT if conflict_headers else status.HTTP_200_OK
    headers = {
        "Content-Disposition": f'attachment; filename="{filename}"',
        **conflict_headers,
    }
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        status_code=status_code,
        headers=headers,
    )
```

- [ ] **Step 2: Mount the router in `main.py`**

Edit `tools/bjj-app/server/main.py`:

Add import near the other `api` imports:

```python
from server.api import export_pdf as export_pdf_api
```

Add `app.include_router(export_pdf_api.router)` below the existing `app.include_router(summarise_api.router)` line.

- [ ] **Step 3: Run tests to verify they pass**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend/test_api_export_pdf.py -v
```

Expected: all 8 tests pass.

If a test fails because `settings.project_root` doesn't resolve to the fixture's `tmp_path`, inspect `server/config.py` to confirm it honours the `BJJ_PROJECT_ROOT` env var. If not, set the env var properly or pass the project root via a different mechanism (the existing pattern in `conftest.py` should already handle this — see `tests/backend/conftest.py`).

- [ ] **Step 4: Run the full backend suite to verify no regressions**

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend -q
```

Expected: previous 186 pass + new tests = ~200+ passing, 2 skipped.

- [ ] **Step 5: Commit**

```bash
git add tools/bjj-app/server/api/export_pdf.py tools/bjj-app/server/main.py
git commit -m "feat(bjj-app): add POST /api/rolls/:id/export-pdf endpoint"
```

---

## Task 10: Frontend types + API client

**Files:**
- Modify: `tools/bjj-app/web/src/lib/types.ts`
- Modify: `tools/bjj-app/web/src/lib/api.ts`

- [ ] **Step 1: Add `ExportPdfResult` type**

Edit `tools/bjj-app/web/src/lib/types.ts`. Append:

```typescript
export type ExportPdfResult =
  | { kind: "ok"; blob: Blob; filename: string }
  | { kind: "conflict"; blob: Blob; filename: string };
```

- [ ] **Step 2: Add `exportRollPdf` API client**

Edit `tools/bjj-app/web/src/lib/api.ts`. Append:

```typescript
import type { ExportPdfResult } from "./types";

/** POST /api/rolls/:id/export-pdf — returns PDF blob + conflict flag. */
export async function exportRollPdf(rollId: string, overwrite = false): Promise<ExportPdfResult> {
  const url = `/api/rolls/${encodeURIComponent(rollId)}/export-pdf${overwrite ? "?overwrite=1" : ""}`;
  const response = await fetch(url, { method: "POST" });

  if (response.status === 200 || response.status === 409) {
    const blob = await response.blob();
    const filename = parseFilenameFromContentDisposition(response.headers.get("content-disposition"));
    const kind = response.status === 409 ? "conflict" : "ok";
    return { kind, blob, filename };
  }

  // Error paths return JSON.
  const error = await response.json().catch(() => ({ detail: `HTTP ${response.status}` }));
  throw new Error(error.detail ?? `Export failed (${response.status})`);
}

function parseFilenameFromContentDisposition(header: string | null): string {
  if (!header) return "match-report.pdf";
  const m = header.match(/filename="([^"]+)"/);
  return m?.[1] ?? "match-report.pdf";
}
```

Note: if `api.ts` already has an `ApiError` class or similar, swap `throw new Error(...)` for that class. Check the file's existing error-handling pattern before writing this code — follow whatever's already there.

- [ ] **Step 3: Type-check the frontend**

```bash
cd tools/bjj-app/web && npm run check 2>&1 | tail -20
```

Expected: no new type errors. (There may be pre-existing warnings; those are fine.)

- [ ] **Step 4: Commit**

```bash
git add tools/bjj-app/web/src/lib/types.ts tools/bjj-app/web/src/lib/api.ts
git commit -m "feat(bjj-app): add exportRollPdf API client + ExportPdfResult type"
```

---

## Task 11: Generalise `PublishConflictDialog` copy

**Files:**
- Modify: `tools/bjj-app/web/src/lib/components/PublishConflictDialog.svelte`

- [ ] **Step 1: Update the dialog body copy**

The dialog currently says "Your Notes or a summary section was edited in Obsidian since you last published." Broaden to also mention the Report section.

Edit `tools/bjj-app/web/src/lib/components/PublishConflictDialog.svelte`. Find the `<p>` tag on line 22 and change to:

```svelte
<p class="mt-2 text-sm text-white/70">
  Your Notes, a summary section, or the Report section was edited in Obsidian since you last
  published. If you overwrite, the external edit will be lost (check git if you need to recover).
</p>
```

- [ ] **Step 2: Run the existing conflict-dialog test to verify no break**

```bash
cd tools/bjj-app/web && npx vitest run tests/publish-conflict.test.ts
```

Expected: if the test asserts on the exact old string, one assertion will break. Update the test assertion to match the new copy:

Open `tools/bjj-app/web/tests/publish-conflict.test.ts`. Find any string assertion matching "Your Notes or a summary section" / "Your Notes was" and update it to match the new wording. Re-run:

```bash
cd tools/bjj-app/web && npx vitest run tests/publish-conflict.test.ts
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add tools/bjj-app/web/src/lib/components/PublishConflictDialog.svelte tools/bjj-app/web/tests/publish-conflict.test.ts
git commit -m "feat(bjj-app): broaden conflict dialog copy to include Report section"
```

---

## Task 12: Frontend button tests (failing — no impl)

**Files:**
- Create: `tools/bjj-app/web/tests/export-pdf.test.ts`

- [ ] **Step 1: Write the failing tests**

Create `tools/bjj-app/web/tests/export-pdf.test.ts`. This mirrors the style of `web/tests/review-analyse.test.ts`.

```typescript
import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/svelte";
import userEvent from "@testing-library/user-event";

import ReviewPage from "../src/routes/review/[id]/+page.svelte";

// Helpers mirroring review-analyse.test.ts — load shape of `data` prop.
function makeData(overrides: Partial<any> = {}) {
  return {
    roll: {
      id: "abcdef1234567890abcdef1234567890",
      title: "Tuesday Roll",
      date: "2026-04-21",
      partner: null,
      duration_s: 245,
      result: "unknown",
      video_url: "/assets/abcdef1234567890abcdef1234567890/source.mp4",
      vault_path: "Roll Log/2026-04-21 - Tuesday Roll.md",
      vault_published_at: 1713700200,
      player_a_name: "Greig",
      player_b_name: "Partner",
      finalised_at: null,
      scores: null,
      distribution: null,
      moments: [],
      ...overrides,
    },
  };
}

function makeFinalisedData() {
  return makeData({
    finalised_at: 1713700100,
    scores: {
      summary: "Solid roll.",
      scores: { position_control: 7, submission_threat: 3, defensive_resilience: 8 },
      top_improvements: ["a"],
      strengths: ["b"],
      key_moments: [],
    },
    distribution: {
      timeline: [],
      counts: {},
      percentages: { guard_bottom: 50, guard_top: 50 },
    },
  });
}

describe("Review page — Export PDF", () => {
  let originalCreateObjectURL: any;
  let originalRevokeObjectURL: any;

  beforeEach(() => {
    originalCreateObjectURL = URL.createObjectURL;
    originalRevokeObjectURL = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(() => "blob:fake-url");
    URL.revokeObjectURL = vi.fn();
  });

  afterEach(() => {
    URL.createObjectURL = originalCreateObjectURL;
    URL.revokeObjectURL = originalRevokeObjectURL;
    vi.restoreAllMocks();
  });

  it("hides or disables the Export PDF button when the roll is not finalised", () => {
    render(ReviewPage, { props: { data: makeData() } });
    const btn = screen.queryByRole("button", { name: /export pdf/i });
    // Button may exist but disabled, or be hidden entirely — accept either.
    if (btn) {
      expect(btn).toBeDisabled();
    }
  });

  it("enables the Export PDF button when the roll is finalised", () => {
    render(ReviewPage, { props: { data: makeFinalisedData() } });
    const btn = screen.getByRole("button", { name: /export pdf/i });
    expect(btn).toBeEnabled();
  });

  it("clicks the button → POST /export-pdf → triggers blob download", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])], { type: "application/pdf" }), {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition": 'attachment; filename="tuesday-roll-2026-04-21.pdf"',
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(ReviewPage, { props: { data: makeFinalisedData() } });
    const btn = screen.getByRole("button", { name: /export pdf/i });
    await userEvent.click(btn);

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledWith(
        expect.stringContaining("/api/rolls/abcdef1234567890abcdef1234567890/export-pdf"),
        expect.objectContaining({ method: "POST" }),
      );
      expect(URL.createObjectURL).toHaveBeenCalled();
    });
  });

  it("409 opens the conflict dialog AND still triggers the download", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])], { type: "application/pdf" }), {
        status: 409,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition": 'attachment; filename="tuesday-roll-2026-04-21.pdf"',
          "X-Conflict": "report",
        },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    render(ReviewPage, { props: { data: makeFinalisedData() } });
    const btn = screen.getByRole("button", { name: /export pdf/i });
    await userEvent.click(btn);

    await waitFor(() => {
      // Download happened
      expect(URL.createObjectURL).toHaveBeenCalled();
      // Dialog opened
      expect(screen.getByRole("dialog")).toBeInTheDocument();
      expect(screen.getByText(/Report section/i)).toBeInTheDocument();
    });
  });

  it("clicking Overwrite from the conflict dialog retries with overwrite=1", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        new Response(new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])]), {
          status: 409,
          headers: {
            "Content-Type": "application/pdf",
            "Content-Disposition": 'attachment; filename="tuesday-roll-2026-04-21.pdf"',
            "X-Conflict": "report",
          },
        }),
      )
      .mockResolvedValueOnce(
        new Response(new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])]), {
          status: 200,
          headers: {
            "Content-Type": "application/pdf",
            "Content-Disposition": 'attachment; filename="tuesday-roll-2026-04-21.pdf"',
          },
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    render(ReviewPage, { props: { data: makeFinalisedData() } });
    await userEvent.click(screen.getByRole("button", { name: /export pdf/i }));
    await waitFor(() => expect(screen.getByRole("dialog")).toBeInTheDocument());
    await userEvent.click(screen.getByRole("button", { name: /overwrite/i }));

    await waitFor(() => {
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(fetchMock.mock.calls[1][0]).toContain("overwrite=1");
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    });
  });

  it("shows 'Exporting…' while the request is in flight and disables the button", async () => {
    let resolve: any;
    const pending = new Promise<Response>((r) => { resolve = r; });
    const fetchMock = vi.fn().mockReturnValue(pending);
    vi.stubGlobal("fetch", fetchMock);

    render(ReviewPage, { props: { data: makeFinalisedData() } });
    const btn = screen.getByRole("button", { name: /export pdf/i });
    await userEvent.click(btn);

    await waitFor(() => {
      const busy = screen.getByRole("button", { name: /exporting/i });
      expect(busy).toBeDisabled();
    });

    resolve(
      new Response(new Blob([new Uint8Array([0x25, 0x50, 0x44, 0x46, 0x2d])]), {
        status: 200,
        headers: {
          "Content-Type": "application/pdf",
          "Content-Disposition": 'attachment; filename="x.pdf"',
        },
      }),
    );
  });
});
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
cd tools/bjj-app/web && npx vitest run tests/export-pdf.test.ts
```

Expected: tests fail because the Export PDF button doesn't exist in the review page yet.

- [ ] **Step 3: Commit the failing tests**

```bash
git add tools/bjj-app/web/tests/export-pdf.test.ts
git commit -m "test(bjj-app): add Export PDF review-page tests (failing — no impl)"
```

---

## Task 13: Frontend button + handler (make Task 12 tests pass)

**Files:**
- Modify: `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`

- [ ] **Step 1: Add state + handler**

Open `tools/bjj-app/web/src/routes/review/[id]/+page.svelte`. Near the top of the `<script>` block (with the other reactive state declarations), add:

```typescript
let exporting = $state(false);
let exportConflictOpen = $state(false);
let pendingExport = $state<{ blob: Blob; filename: string } | null>(null);

async function triggerDownload(blob: Blob, filename: string): Promise<void> {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

async function handleExport(overwrite = false): Promise<void> {
  if (exporting) return;
  exporting = true;
  try {
    const result = await exportRollPdf(data.roll.id, overwrite);
    await triggerDownload(result.blob, result.filename);
    if (result.kind === "conflict") {
      pendingExport = { blob: result.blob, filename: result.filename };
      exportConflictOpen = true;
    }
  } catch (err) {
    // Surface via toast or console — use whatever pattern the page already uses.
    console.error("Export PDF failed", err);
  } finally {
    exporting = false;
  }
}

function handleExportConflictOverwrite(): void {
  exportConflictOpen = false;
  pendingExport = null;
  // Retry with overwrite — don't re-trigger download from this call.
  (async () => {
    if (exporting) return;
    exporting = true;
    try {
      const result = await exportRollPdf(data.roll.id, true);
      if (result.kind === "conflict") {
        // Still conflicting — bail; caller can retry manually.
        pendingExport = { blob: result.blob, filename: result.filename };
        exportConflictOpen = true;
      }
    } catch (err) {
      console.error("Export PDF overwrite failed", err);
    } finally {
      exporting = false;
    }
  })();
}

function handleExportConflictCancel(): void {
  exportConflictOpen = false;
  pendingExport = null;
}
```

Also ensure the `import` line near the top includes `exportRollPdf`:

```typescript
import { exportRollPdf /* , existing imports */ } from "$lib/api";
```

- [ ] **Step 2: Add the button in the footer row**

Find the footer row on the review page that already contains Finalise and Save to Vault. Add the Export PDF button between them (or right after Finalise):

```svelte
<button
  type="button"
  onclick={() => handleExport(false)}
  disabled={!data.roll.finalised_at || exporting}
  class="rounded-md border border-white/15 bg-white/[0.04] px-3 py-1.5 text-xs font-medium text-white/75 hover:bg-white/[0.08] transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
>
  {exporting ? "Exporting…" : "Export PDF"}
</button>
```

Re-use the existing button class list from the nearby Finalise / Save to Vault buttons verbatim — the snippet above is a template, not canonical; match whatever's already on the page.

- [ ] **Step 3: Mount the conflict dialog**

Near the other dialog mounts, add:

```svelte
<PublishConflictDialog
  open={exportConflictOpen}
  onOverwrite={handleExportConflictOverwrite}
  onCancel={handleExportConflictCancel}
/>
```

If the page already mounts a `PublishConflictDialog` for the Save-to-Vault flow, consider whether to use the same instance or add a second. Per the test expectations (Task 12 — `getByRole("dialog")` expects one visible dialog at a time), mounting two disjoint instances is fine because only one's `open` is true at any moment.

- [ ] **Step 4: Run the tests**

```bash
cd tools/bjj-app/web && npx vitest run tests/export-pdf.test.ts
```

Expected: all 6 tests pass.

- [ ] **Step 5: Run the full frontend suite to check for regressions**

```bash
cd tools/bjj-app/web && npm test
```

Expected: all passing (75 prior + 6 new ≥ 81).

- [ ] **Step 6: Commit**

```bash
git add tools/bjj-app/web/src/routes/review/[id]/+page.svelte
git commit -m "feat(bjj-app): wire Export PDF button + conflict flow on review page"
```

---

## Task 14: README + docs

**Files:**
- Modify: `tools/bjj-app/README.md`

- [ ] **Step 1: Add the M6b section**

Edit `tools/bjj-app/README.md`. Find the section describing milestones / local setup (probably structured per-milestone — M3, M4, M5, M6a). Add the following new subsection after M6a's:

```markdown
### M6b — PDF export

One-click match-report PDF. After finalising a roll, click **Export PDF** in
the review page footer. The app:

1. Renders a Jinja2 template of the roll's scores + summary + key moments.
2. Converts to PDF via WeasyPrint.
3. Writes the PDF to `assets/<roll_id>/report.pdf`.
4. Ensures the roll's vault markdown is current (invokes Save to Vault
   internally), then adds a `## Report` section linking to the PDF.
5. Streams the PDF back to the browser for download.

Requires a one-time `brew install pango` on macOS for WeasyPrint's Cairo /
Pango backend.

If the vault `## Report`, `## Your Notes`, or any summary section has been
hand-edited in Obsidian since the last export, the endpoint returns 409 and
the UI shows the same conflict dialog as Save to Vault — Overwrite retries
with `?overwrite=1`; Cancel keeps the PDF on disk but leaves the markdown
untouched.
```

- [ ] **Step 2: Commit**

```bash
git add tools/bjj-app/README.md
git commit -m "docs(bjj-app): document M6b (PDF export) in README"
```

---

## Task 15: Manual browser smoke test

**Files:** none — this task documents the smoke protocol, not code.

- [ ] **Step 1: Start the dev server**

```bash
cd tools/bjj-app && .venv/bin/python -m uvicorn server.main:app --reload --port 8001 &
cd tools/bjj-app/web && npm run dev -- --port 5173 &
```

- [ ] **Step 2: Reach a finalised roll**

Open http://127.0.0.1:5173. Either pick an existing finalised roll from the homepage, or create a new roll:

1. Upload a short video.
2. Analyse at least one moment.
3. Click Finalise — confirm scores appear in the ScoresPanel.

- [ ] **Step 3: Test happy-path export**

1. Click **Export PDF**. Expected:
   - Browser downloads a file named `<slug>-<date>.pdf`.
   - Open it in Preview — verify the layout matches the spec (masthead, title, subtitle, one-sentence summary, three score boxes, position-flow bar, improvements, strengths, key moments, footer).
2. Check on disk: `ls assets/<roll_id>/report.pdf` exists.
3. Open the roll's markdown in Obsidian — verify `## Report` section exists with `[[assets/.../report.pdf|Match report PDF]]` link.
4. Click the link in Obsidian — Obsidian opens the PDF.

- [ ] **Step 4: Test conflict path**

1. In Obsidian, edit the `## Report` section body (e.g. change the timestamp text).
2. Click **Export PDF** again. Expected:
   - PDF downloads anyway.
   - Conflict dialog shows "Your Notes, a summary section, or the Report section was edited in Obsidian…".
3. Click **Overwrite**. Expected:
   - Dialog closes.
   - The markdown's `## Report` body is rewritten to the app's version.
   - (No second download — the retry does not re-fire the blob download.)

- [ ] **Step 5: Test re-finalise path**

1. Re-finalise the same roll (click Re-finalise). Scores update.
2. Click **Export PDF**. Expected: a fresh PDF with the new scores, overwriting `assets/<roll_id>/report.pdf`; markdown summary sections also refresh to match the new scores.

- [ ] **Step 6: Test disabled state**

1. Create a new roll (fresh upload, no analyses, no finalise).
2. Navigate to its review page. Expected: the Export PDF button is disabled (or absent).

- [ ] **Step 7: If any smoke step fails, fix and commit before proceeding**

Document any fix commits as `fix(bjj-app): ...` referencing what was broken.

---

## Integration checkpoint (run before declaring M6b done)

- [ ] Full backend suite passes:

```bash
cd tools/bjj-app && .venv/bin/python -m pytest tests/backend -q
```

Expected: 186 prior + ~30 new M6b tests = ~216 passing, 2 skipped.

- [ ] Full frontend suite passes:

```bash
cd tools/bjj-app/web && npm test
```

Expected: 75 prior + 6 new = 81 passing.

- [ ] All three commit types represented: `test(...)`, `feat(...)`, `docs(...)`, `chore(...)`.

- [ ] Manual smoke test (Task 15) completed end-to-end.

- [ ] Invoke `superpowers:finishing-a-development-branch` to complete the merge.
