import pytest

from jlceda2kicad.validation import LcscIdError, normalize_lcsc_id


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("C1", "C1"),
        ("C2040", "C2040"),
        (" c2040 ", "C2040"),
        ("\tc99\r\n", "C99"),
    ],
)
def test_normalize_lcsc_id_accepts_one_identifier(raw: str, expected: str) -> None:
    assert normalize_lcsc_id(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", " ", "C0", "C01", "C-1", "C1 C2", "C1;whoami", "C2040\nC1", "元件"],
)
def test_normalize_lcsc_id_rejects_unsafe_or_invalid_input(raw: str) -> None:
    with pytest.raises(LcscIdError, match="C"):
        normalize_lcsc_id(raw)

