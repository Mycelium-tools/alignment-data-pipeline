"""Helpers for summarizing per-batch token counts during generation runs."""


def summarize(batches):
    """Return count, total, mean, and max of a list of per-batch token counts."""
    count = len(batches)
    total = sum(batches)
    return {
        "count": count,
        "total": total,
        "average": total / count,
        "max": maximum,
    }
