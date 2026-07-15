"""Altair chart builders for the Run-diversity page.

Kept out of the page module so the chart specs are readable and reusable. Altair
ships with Streamlit (no extra dependency).

Theme split: **data marks** carry hardcoded colours from the validated design
palette — categorical hues in fixed order (never cycled), reserved status hues for
verdicts, one primary hue for plain magnitude — all chosen to read on both the light
and dark chart surface. Everything else (axis/legend/title text, grid, frame) is
left to Streamlit's Altair theme so it adapts to the viewer's light/dark mode;
direct-label text uses a neutral grey that clears 3:1 on either surface. Marks are
thin with 4px rounded data-ends and a surface ring on points; PCA tick *labels* are
hidden (the coordinates are meaningless) but the grid and frame stay for context.
"""

from __future__ import annotations

import altair as alt
import pandas as pd

# validated reference palette — data marks only (readable on light & dark surfaces)
CATEGORICAL = ["#2a78d6", "#1baf7a", "#eda100", "#008300",
               "#4a3aa7", "#e34948", "#e87ba4", "#eb6834"]
PRIMARY = "#2a78d6"
STATUS = {"GOOD": "#0ca30c", "OK": "#fab219", "BAD": "#d03b3b", "NA": "#9aa0a6"}
_LABEL = "#8a8a8a"   # neutral direct-label ink — clears 3:1 on both surfaces
_RING = "#ffffff"    # surface ring on points — pops on dark, harmless on light
# single-hue sequential ramp, light→vivid, monotonic in lightness — for magnitude
# heatmaps; reads on both surfaces (pale end pops on dark, vivid end on light)
_SEQ_BLUE = ["#eaf1fb", "#7fb0e8", "#2a78d6"]
_EMPTY = "#c9ccd1"   # low-salience "absent cell" fill; a stroke keeps it legible
_GRIDLINE = "#9aa0a6"  # per-cell stroke — reads on both surfaces


def diversity_map(projection: list[dict]) -> alt.Chart | None:
    """#1 — 2D PCA scatter of the corpus in meaning-space, coloured by topic cluster.
    A tight blob = semantic collapse; a wide spread = diverse. Cluster colour is used
    only when there are 2..8 clusters (categorical hues are never cycled); past that
    the points are one hue and position alone carries the signal. Tick labels are
    hidden (PCA coordinates are unitless) but the grid/frame stay so it reads as a
    plot, not a void."""
    if not projection:
        return None
    df = pd.DataFrame(projection)
    if len(df) < 2 or {"x", "y"} - set(df.columns):
        return None
    n_clusters = df["cluster"].nunique() if "cluster" in df else 0
    axis = alt.Axis(labels=False, ticks=False, title=None, grid=True)
    enc = dict(
        x=alt.X("x:Q", axis=axis, scale=alt.Scale(nice=True, padding=24)),
        y=alt.Y("y:Q", axis=axis, scale=alt.Scale(nice=True, padding=24)),
        tooltip=[alt.Tooltip("id:N", title="record"), alt.Tooltip("cluster:N", title="cluster")],
    )
    if 2 <= n_clusters <= len(CATEGORICAL):
        enc["color"] = alt.Color(
            "cluster:N", scale=alt.Scale(range=CATEGORICAL[:n_clusters]),
            legend=alt.Legend(title="topic cluster", orient="right"))
        mark = dict(size=140, opacity=0.85)
    else:
        mark = dict(size=140, opacity=0.75, color=PRIMARY)
    return (
        alt.Chart(df)
        .mark_circle(stroke=_RING, strokeWidth=1.5, **mark)
        .encode(**enc)
        .properties(height=320)
    )


def axis_distribution(axis: str, counts: dict) -> alt.Chart | None:
    """#4 — value counts for one categorical axis as horizontal bars, biggest first,
    with the count direct-labelled. One hue: this is plain magnitude, not identity."""
    rows = [{"value": str(k), "records": int(v)} for k, v in (counts or {}).items()]
    if not rows:
        return None
    df = pd.DataFrame(rows).sort_values("records", ascending=False)
    y = alt.Y("value:N", sort="-x", title=None)
    bars = alt.Chart(df).mark_bar(
        cornerRadiusEnd=4, color=PRIMARY, height=alt.RelativeBandSize(0.7)).encode(
        y=y,
        x=alt.X("records:Q", title="records", axis=alt.Axis(tickMinStep=1)),
        tooltip=[alt.Tooltip("value:N", title=axis), alt.Tooltip("records:Q")],
    )
    labels = alt.Chart(df).mark_text(align="left", dx=4, color=_LABEL).encode(
        y=y, x="records:Q", text="records:Q")
    return (bars + labels).properties(height=min(360, 36 * len(df) + 24))


def evenness_health(evenness: dict) -> alt.Chart | None:
    """#5 — Pielou evenness per axis, worst first, bars coloured by the GOOD/OK/BAD
    verdict (reserved status hues) and the value direct-labelled. One-glance read of
    which axes are balanced and which have collapsed onto a dominant value."""
    rows = [{"axis": ax, "evenness": m.get("evenness"), "verdict": m.get("verdict") or "NA",
             "richness": m.get("richness")}
            for ax, m in (evenness or {}).items() if m.get("evenness") is not None]
    if not rows:
        return None
    df = pd.DataFrame(rows).sort_values("evenness")
    order = ["GOOD", "OK", "BAD", "NA"]
    present = [v for v in order if v in set(df["verdict"])]
    y = alt.Y("axis:N", sort=alt.SortField("evenness", order="ascending"), title=None,
              axis=alt.Axis(labelOverlap=False))
    bars = alt.Chart(df).mark_bar(
        cornerRadiusEnd=4, height=alt.RelativeBandSize(0.7)).encode(
        y=y,
        x=alt.X("evenness:Q", scale=alt.Scale(domain=[0, 1]),
                title="Pielou evenness (1 = balanced, 0 = collapsed)"),
        color=alt.Color("verdict:N", scale=alt.Scale(domain=present, range=[STATUS[v] for v in present]),
                        legend=alt.Legend(title="verdict", orient="top")),
        tooltip=["axis:N", alt.Tooltip("evenness:Q", format=".2f"), "verdict:N",
                 alt.Tooltip("richness:Q", title="distinct values")],
    )
    labels = alt.Chart(df).mark_text(align="left", dx=4, color=_LABEL).encode(
        y=y, x="evenness:Q", text=alt.Text("evenness:Q", format=".2f"))
    return (bars + labels).properties(height=max(160, 30 * len(df) + 30))


def correlation_heatmap(correlation: dict) -> alt.Chart | None:
    """#6 — axis×axis Cramér's V as a heatmap. Each computed pair is placed at both
    (a,b) and (b,a) so the matrix is symmetric (Cramér's V is); the diagonal stays
    blank. Sequential single hue by magnitude — pale = independent (healthy), vivid =
    one axis predicts the other (the sycophancy tell for attitude × direction). Cell
    values are direct-labelled with a contrast-flipped ink so the number reads on any
    cell; NA pairs (undefined V) are omitted and the table below carries them."""
    rows = []
    for pair, m in (correlation or {}).items():
        v = m.get("cramers_v")
        if v is None or " x " not in pair:
            continue
        a, b = (s.strip() for s in pair.split(" x ", 1))
        rows.append({"a": a, "b": b, "v": v})
        rows.append({"a": b, "b": a, "v": v})   # symmetric mirror
    if not rows:
        return None
    df = pd.DataFrame(rows)
    axes = sorted(set(df["a"]) | set(df["b"]))
    base = alt.Chart(df).encode(
        x=alt.X("b:N", sort=axes, title=None, axis=alt.Axis(labelAngle=-30)),
        y=alt.Y("a:N", sort=axes, title=None),
    )
    cells = base.mark_rect(stroke=_RING, strokeWidth=1).encode(
        color=alt.Color("v:Q", scale=alt.Scale(domain=[0, 1], range=_SEQ_BLUE),
                        legend=alt.Legend(title="Cramér's V")),
        tooltip=[alt.Tooltip("a:N", title="axis"), alt.Tooltip("b:N", title="axis"),
                 alt.Tooltip("v:Q", title="Cramér's V", format=".2f")],
    )
    labels = base.mark_text(baseline="middle").encode(
        text=alt.Text("v:Q", format=".2f"),
        color=alt.condition("datum.v > 0.45", alt.value("#f5f5f5"), alt.value("#1a1a1a")),
    )
    return (cells + labels).properties(height=min(360, 44 * len(axes) + 40))


def coverage_grid(pair: str, filled_cells: list, missing: list) -> alt.Chart | None:
    """#7 — the designed axis-pair grid with each cell coloured filled or empty. This
    is the clearest read of combinatorial collapse: a grid mostly empty means whole
    swaths of the intended cross never occur. Two-state encoding (filled = one hue,
    empty = a recessive tone) reinforced by a per-cell stroke, position, tooltip, and
    the coverage table that stays alongside as the accessible fallback."""
    rows = []
    for cell in (filled_cells or []):
        if "×" in cell:
            a, b = cell.split("×", 1)
            rows.append({"a": a, "b": b, "state": "filled"})
    for cell in (missing or []):
        if "×" in cell:
            a, b = cell.split("×", 1)
            rows.append({"a": a, "b": b, "state": "empty"})
    if not rows:
        return None
    df = pd.DataFrame(rows)
    a_name, b_name = ([s.strip() for s in pair.split(" x ", 1)]
                      if " x " in pair else ["", ""])
    grid = alt.Chart(df).mark_rect(stroke=_GRIDLINE, strokeWidth=1).encode(
        x=alt.X("b:N", title=b_name or None,
                axis=alt.Axis(labelAngle=-30, labelOverlap=False)),
        y=alt.Y("a:N", title=a_name or None, axis=alt.Axis(labelOverlap=False)),
        color=alt.Color("state:N",
                        scale=alt.Scale(domain=["filled", "empty"], range=[PRIMARY, _EMPTY]),
                        legend=alt.Legend(title=None, orient="top")),
        tooltip=[alt.Tooltip("a:N", title=a_name or "row"),
                 alt.Tooltip("b:N", title=b_name or "col"),
                 alt.Tooltip("state:N", title="cell")],
    )
    # base leaves room for the rotated x-labels + axis title below the plot
    return grid.properties(height=min(560, 52 * df["a"].nunique() + 150))
