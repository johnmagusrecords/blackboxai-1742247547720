import pytest
from math_operations import multiply

def test_multiply():
    assert multiply(2, 3) == 6
    assert multiply(-1, 5) == -5
    assert multiply(-2, -3) == 6
    assert multiply(0, 5) == 0
