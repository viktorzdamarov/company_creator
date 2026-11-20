import pytest

from app.services.weights import assign_shares, distribute


@pytest.mark.parametrize(
    ("n", "expected"),
    [
        (0, []),
        (1, [100]),
        (2, [50, 50]),
        (3, [34, 33, 33]),
        (4, [25, 25, 25, 25]),
        (6, [17, 17, 17, 17, 16, 16]),
        (7, [15, 15, 14, 14, 14, 14, 14]),
        (100, [1] * 100),
    ],
)
def test_distribute_known_values(n, expected):
    assert distribute(n) == expected


@pytest.mark.parametrize("n", range(1, 101))
def test_distribute_properties(n):
    shares = distribute(n)
    assert len(shares) == n
    assert sum(shares) == 100
    assert max(shares) - min(shares) <= 1
    assert shares == sorted(shares, reverse=True)  # remainder goes to the first offers
    assert min(shares) >= 1


def test_negative_n_rejected():
    with pytest.raises(ValueError):
        distribute(-1)


def test_more_offers_than_percent_rejected():
    with pytest.raises(ValueError):
        distribute(101)


def test_assign_shares_keeps_order():
    assert assign_shares([3749, 3717, 18813]) == [(3749, 34), (3717, 33), (18813, 33)]


def test_assign_shares_empty():
    assert assign_shares([]) == []


def test_assign_shares_rejects_duplicates():
    with pytest.raises(ValueError, match="duplicate"):
        assign_shares([1, 1])


def test_add_and_remove_scenario():
    """Editor scenario from the acceptance plan: 1 -> add -> add -> remove."""
    offers = [3749]
    assert [s for _, s in assign_shares(offers)] == [100]
    offers.append(3717)
    assert [s for _, s in assign_shares(offers)] == [50, 50]
    offers.append(18813)
    assert [s for _, s in assign_shares(offers)] == [34, 33, 33]
    offers.remove(3749)
    assert assign_shares(offers) == [(3717, 50), (18813, 50)]


# ---------------------------------------------------------------- pinned shares

import pytest as _pytest  # noqa: E402

from app.services.weights import PinnedSharesError, distribute_with_pins  # noqa: E402


@_pytest.mark.parametrize(
    "pins, expected",
    [
        ([None, None, None], [34, 33, 33]),
        ([25, None, None], [25, 38, 37]),
        ([25, None, None, None], [25, 25, 25, 25]),
        ([50, 50], [50, 50]),
        ([60, None], [60, 40]),
        ([30, 30], [30, 30]),  # all pinned: returned as is, Push checks the sum
        ([], []),
    ],
)
def test_distribute_with_pins(pins, expected):
    assert distribute_with_pins(pins) == expected


@_pytest.mark.parametrize("pins", [[60, 50], [100, None], [99, None, None]])
def test_distribute_with_pins_impossible(pins):
    with _pytest.raises(PinnedSharesError):
        distribute_with_pins(pins)
