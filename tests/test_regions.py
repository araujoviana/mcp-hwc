import pytest

from mcp_hwc.regions import normalize_region_input


def test_normalize_region_input_accepts_region_code() -> None:
    assert normalize_region_input("la-south-2") == "la-south-2"


def test_normalize_region_input_resolves_human_aliases() -> None:
    assert normalize_region_input("Santiago") == "la-south-2"
    assert normalize_region_input("Sao Paulo") == "sa-brazil-1"
    assert normalize_region_input("São Paulo") == "sa-brazil-1"


def test_normalize_region_input_rejects_ambiguous_aliases() -> None:
    with pytest.raises(ValueError, match="ambiguous"):
        normalize_region_input("Mexico City")
