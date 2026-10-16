"""Small, dependency-free statistics with explicit denominators."""

from __future__ import annotations

import math
from typing import TypedDict


class Rate(TypedDict):
    k: int
    n: int
    rate: float | None
    ci_low: float | None
    ci_high: float | None


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float] | None:
    """Wilson score interval for k successes out of n (95% by default). None if n == 0."""
    if n <= 0:
        return None
    if not 0 <= k <= n:
        raise ValueError(f"k={k} must be between 0 and n={n}")
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def rate(k: int, n: int) -> Rate:
    ci = wilson(k, n)
    return Rate(
        k=k,
        n=n,
        rate=round(k / n, 4) if n else None,
        ci_low=round(ci[0], 4) if ci else None,
        ci_high=round(ci[1], 4) if ci else None,
    )


def quantile(values: list[float], q: float) -> float | None:
    """Linear-interpolated quantile (same as numpy's default). None for no values."""
    if not values:
        return None
    xs = sorted(values)
    pos = (len(xs) - 1) * q
    lo = math.floor(pos)
    hi = math.ceil(pos)
    return xs[lo] + (xs[hi] - xs[lo]) * (pos - lo)
