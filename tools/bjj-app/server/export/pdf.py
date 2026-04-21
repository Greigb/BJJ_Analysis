"""M6b PDF report rendering — pure helpers + WeasyPrint wrapper.

No IO except inside `render_report_pdf`. Tests hit the helpers directly;
rendering gets a smoke test for PDF-magic-number output.
"""
from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

import jinja2
from weasyprint import CSS, HTML


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


_SCORE_LABEL_BY_ID = {
    "guard_retention": "Guard Retention",
    "positional_awareness": "Positional Awareness",
    "transition_quality": "Transition Quality",
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
            "blurb": km.get("note", ""),
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
