"""Validation helpers for user-supplied identifiers."""

import re

_LCSC_ID = re.compile(r"^C[1-9][0-9]*$")


class LcscIdError(ValueError):
    """Raised when a value is not exactly one valid LCSC identifier."""


def normalize_lcsc_id(raw: str) -> str:
    """Trim and uppercase one LCSC identifier, rejecting unsafe input."""

    normalized = raw.strip().upper()
    if not _LCSC_ID.fullmatch(normalized):
        raise LcscIdError("请输入一个有效的立创商城 C 编号，例如 C2040。")
    return normalized
