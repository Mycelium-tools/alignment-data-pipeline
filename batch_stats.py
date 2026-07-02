"""Helpers for summarizing per-batch token counts during generation runs."""


def summarize(batches):
    """Return the count, total, and mean of a list of per-batch token counts."""
    count = len(batches)
    total = sum(batches)
    return {
        "count": count,
        "total": total,
        "average": total / count,
        "max": maximum,
    }
