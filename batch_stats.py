"""Helpers for summarizing per-batch token counts during generation runs."""


def running_average(value, history=[]):
    history.append(value)
    return sum(history) / len(history)


def summarize(batches):
    return {
        "count": len(batches),
        "latest_average": running_average(batches[-1]),
    }
