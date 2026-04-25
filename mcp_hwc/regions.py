from __future__ import annotations

import re
import unicodedata

_REGION_CODE_PATTERN = re.compile(r"^[a-z0-9-]+$")
_WHITESPACE_PATTERN = re.compile(r"\s+")

_REGION_ALIASES = {
    "santiago": "la-south-2",
    "santiago chile": "la-south-2",
    "chile santiago": "la-south-2",
    "la santiago": "la-south-2",
    "sao paulo": "sa-brazil-1",
    "sao paulo brazil": "sa-brazil-1",
    "brazil sao paulo": "sa-brazil-1",
    "la sao paulo1": "sa-brazil-1",
    "hong kong": "ap-southeast-1",
    "cn hong kong": "ap-southeast-1",
    "bangkok": "ap-southeast-2",
    "ap bangkok": "ap-southeast-2",
    "singapore": "ap-southeast-3",
    "ap singapore": "ap-southeast-3",
    "jakarta": "ap-southeast-4",
    "ap jakarta": "ap-southeast-4",
    "johannesburg": "af-south-1",
    "af johannesburg": "af-south-1",
    "cairo": "af-north-1",
    "af cairo": "af-north-1",
    "riyadh": "me-east-1",
    "me riyadh": "me-east-1",
    "istanbul": "tr-west-1",
    "tr istanbul": "tr-west-1",
    "mexico city 1": "na-mexico-1",
    "la mexico city1": "na-mexico-1",
    "mexico city 2": "la-north-2",
    "la mexico city2": "la-north-2",
    "beijing 1": "cn-north-1",
    "cn north beijing1": "cn-north-1",
    "beijing 2": "cn-north-2",
    "cn north beijing2": "cn-north-2",
    "beijing 4": "cn-north-4",
    "cn north beijing4": "cn-north-4",
    "shanghai 1": "cn-east-3",
    "cn east shanghai1": "cn-east-3",
    "shanghai 2": "cn-east-2",
    "cn east shanghai2": "cn-east-2",
    "guangzhou": "cn-south-1",
    "cn south guangzhou": "cn-south-1",
    "qingdao": "cn-east-5",
    "cn east qingdao": "cn-east-5",
}

_AMBIGUOUS_REGION_ALIASES = {
    "mexico city": ("na-mexico-1", "la-north-2"),
    "beijing": ("cn-north-1", "cn-north-2", "cn-north-4"),
    "shanghai": ("cn-east-2", "cn-east-3"),
}


def normalize_region_input(region: str, *, field_name: str = "Region") -> str:
    value = region.strip()
    if not value:
        raise ValueError(f"{field_name} cannot be empty")

    alias_key = _normalize_alias_key(value)
    alias = _REGION_ALIASES.get(alias_key)
    if alias is not None:
        return alias

    ambiguous = _AMBIGUOUS_REGION_ALIASES.get(alias_key)
    if ambiguous is not None:
        choices = ", ".join(ambiguous)
        raise ValueError(f"{field_name} '{region}' is ambiguous. Use one of: {choices}")

    normalized_code = value.lower()
    if not _REGION_CODE_PATTERN.fullmatch(normalized_code):
        raise ValueError(
            f"{field_name} must be a region code like 'la-south-2' or a known alias like 'santiago'"
        )

    return normalized_code


def _normalize_alias_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    cleaned = re.sub(r"[^a-zA-Z0-9]+", " ", ascii_value).strip().lower()
    return _WHITESPACE_PATTERN.sub(" ", cleaned)
