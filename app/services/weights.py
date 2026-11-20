"""Offer weight (share) distribution for a stream.

Rule (agreed with the customer): shares are split evenly between all offers of a stream.
100 is not always divisible by N, so the remainder is given +1 to the first offers:
    1 -> [100], 2 -> [50, 50], 3 -> [34, 33, 33], 7 -> [15, 15, 14, 14, 14, 14, 14]
The sum is always exactly 100 and shares differ by at most 1. No Keitaro dependency.
"""
from collections.abc import Sequence
from typing import TypeVar

TOTAL = 100

T = TypeVar("T")


def distribute(n: int, total: int = TOTAL) -> list[int]:
    """Split ``total`` into ``n`` integer shares as evenly as possible (earlier items get the remainder)."""
    if n < 0:
        raise ValueError(f"number of offers must be >= 0, got {n}")
    if n == 0:
        return []
    if n > total:
        raise ValueError(f"cannot split {total}% between {n} offers with integer shares >= 1")
    base, remainder = divmod(total, n)
    return [base + 1 if i < remainder else base for i in range(n)]


def assign_shares(offer_ids: Sequence[T]) -> list[tuple[T, int]]:
    """Pair each offer (in the given order) with its even share. Duplicates are rejected."""
    if len(set(offer_ids)) != len(offer_ids):
        raise ValueError("duplicate offers in a stream")
    return list(zip(offer_ids, distribute(len(offer_ids))))


class PinnedSharesError(ValueError):
    """Pinned shares cannot be satisfied (sum over 100, or no room left for the unpinned offers)."""


def distribute_with_pins(pins: Sequence[int | None], total: int = TOTAL) -> list[int]:
    """Shares for offers in order; ``pins[i]`` is the pinned share of offer i or None.

    Pinned offers keep their share; the rest is split evenly between the unpinned offers
    (remainder to the first ones). If every offer is pinned the shares are returned as is:
    the caller decides whether a sum != 100 is acceptable (it is not for Push).
    """
    pinned_sum = sum(p for p in pins if p is not None)
    free = sum(1 for p in pins if p is None)
    if pinned_sum > total:
        raise PinnedSharesError(f"Закреплённые доли дают {pinned_sum}% (больше {total}%)")
    if free == 0:
        return [int(p) for p in pins]  # type: ignore[arg-type]
    rest = total - pinned_sum
    if rest < free:
        raise PinnedSharesError(f"На {free} незакреплённых офферов осталось только {rest}%")
    spread = iter(distribute(free, rest))
    return [int(p) if p is not None else next(spread) for p in pins]
