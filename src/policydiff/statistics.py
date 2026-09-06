"""Classical fixed-report paired statistics; not sequential or clustered inference."""
from functools import lru_cache
import math


@lru_cache(maxsize=4096, typed=True)
def regression_p(losses, wins):
    """Exact one-sided conditional sign test for P(loss) > P(win)."""
    if not (type(losses) is int and type(wins) is int and losses >= 0 and wins >= 0
            and losses + wins <= 1000):
        raise ValueError("invalid paired sign-test counts (maximum 1000)")
    n = losses + wins
    return sum(math.comb(n, k) for k in range(losses, n + 1)) / (1 << n)


def _cdf(k, n, p):
    if p <= 0:
        return 1.0
    if p >= 1:
        return float(k >= n)
    return min(1.0, math.fsum(math.exp(math.lgamma(n + 1) - math.lgamma(j + 1)
               - math.lgamma(n - j + 1) + j * math.log(p) + (n - j) * math.log1p(-p))
               for j in range(k + 1)))


@lru_cache(maxsize=4096, typed=True)
def harmful_flip_upper_bound(losses, n, alpha):
    """One-sided Clopper-Pearson bound; caller establishes sampling eligibility."""
    if not (type(losses) is int and type(n) is int and 0 < n <= 1000 and 0 <= losses <= n
            and type(alpha) in (int, float) and math.isfinite(alpha) and 0 < alpha < 1):
        raise ValueError("invalid binomial bound inputs")
    if losses == n:
        return 1.0
    if losses == 0:
        return -math.expm1(math.log(alpha) / n)
    low, high = 0.0, 1.0
    for _ in range(60):
        mid = (low + high) / 2
        if _cdf(losses, n, mid) > alpha:
            low = mid
        else:
            high = mid
    return high
