import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from stats import describe, mean, median


@pytest.mark.scenario("S1-AS1")
def test_mean_of_values():
    assert mean([1, 2, 3]) == 2


@pytest.mark.scenario("S1-AS1")
def test_mean_empty_raises():
    with pytest.raises(ValueError):
        mean([])


@pytest.mark.scenario("S1-AS2")
def test_median_odd_and_even():
    assert median([3, 1, 2]) == 2
    assert median([1, 2, 3, 4]) == 2.5


@pytest.mark.scenario("S1-AS3")
def test_describe_basic_buckets():
    assert describe([]) == "empty"
    assert describe([5]) == "single positive"
    assert describe([1, 2, 3]) == "positive"
    assert describe([-1, -2]) == "negative"
