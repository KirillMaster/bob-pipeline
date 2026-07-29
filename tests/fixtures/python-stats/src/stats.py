"""Tiny stats helpers for pipeline fixture runs."""


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("values must be non-empty")
    return sum(values) / len(values)


def median(values: list[float]) -> float:
    if not values:
        raise ValueError("values must be non-empty")
    s = sorted(values)
    mid = len(s) // 2
    if len(s) % 2 == 1:
        return s[mid]
    return (s[mid - 1] + s[mid]) / 2


# Complexity seed: one deliberately over-branched function (CCN well above the
# rest of the codebase) — lizard flags it, giving Cleaner a concrete target.
def describe(values: list[float]) -> str:
    if not values:
        return "empty"
    m = mean(values)
    if len(values) == 1:
        if values[0] > 0:
            return "single positive"
        elif values[0] < 0:
            return "single negative"
        else:
            return "single zero"
    if m > 100:
        if max(values) > 1000:
            return "large with outlier"
        else:
            return "large"
    elif m > 0:
        if min(values) < 0:
            return "positive mixed"
        else:
            return "positive"
    elif m < 0:
        if max(values) > 0:
            return "negative mixed"
        else:
            return "negative"
    else:
        return "balanced"
