"""Structure-aware rewrites for generated KiCad component artifacts."""

import json
import re
from pathlib import Path

from .models import ArtifactSet
from .sexpr import Atom, ListExpr, parse_one, rewrite_footprint_models

_WINDOWS_FORBIDDEN = set('<>:"/\\|?*')
_WINDOWS_RESERVED = re.compile(r"^(?:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?$", re.I)


def validate_component_name(value: str, label: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{label} name is empty")
    if normalized.endswith((".", " ")) or _WINDOWS_RESERVED.fullmatch(normalized):
        raise ValueError(f"{label} name is reserved on Windows")
    if any(ord(char) < 32 or char in _WINDOWS_FORBIDDEN for char in normalized):
        raise ValueError(f"{label} name contains a forbidden filename character")
    return normalized


def _quoted(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def _apply(text: str, replacements: list[tuple[int, int, str]]) -> str:
    result = text
    for start, end, replacement in sorted(replacements, reverse=True):
        result = result[:start] + replacement + result[end:]
    return result


def _property_atom(symbol: ListExpr, name: str) -> Atom | None:
    for child in symbol.children:
        atoms = child.atoms
        if child.head == "property" and len(atoms) >= 3 and atoms[1].value == name:
            return atoms[2]
    return None


def rewrite_symbol_component(
    text: str, lcsc_id: str, new_name: str, footprint_identifier: str | None
) -> str:
    normalized = validate_component_name(new_name, "symbol")
    root = parse_one(text)
    symbols = tuple(child for child in root.children if child.head == "symbol")
    matches = tuple(
        symbol
        for symbol in symbols
        if (_property_atom(symbol, "LCSC Part") or Atom("", 0, 0)).value == lcsc_id
    )
    if len(matches) != 1 or len(matches[0].atoms) < 2:
        raise ValueError(f"expected one symbol for {lcsc_id}, found {len(matches)}")
    symbol = matches[0]
    old_name = symbol.atoms[1].value
    replacements = [(symbol.atoms[1].start, symbol.atoms[1].end, _quoted(normalized))]
    for child in symbol.children:
        if child.head == "symbol" and len(child.atoms) >= 2:
            child_name = child.atoms[1]
            if child_name.value.startswith(old_name + "_"):
                renamed = normalized + child_name.value[len(old_name) :]
                replacements.append((child_name.start, child_name.end, _quoted(renamed)))
    for property_name, property_value in (
        ("Value", normalized),
        ("Footprint", footprint_identifier),
    ):
        if property_value is None:
            continue
        atom = _property_atom(symbol, property_name)
        if atom is None:
            insertion = (
                f'\n    (property "{property_name}" {_quoted(property_value)} '
                '(at 0 0 0) (effects (font (size 1.27 1.27)) hide))'
            )
            replacements.append((symbol.end - 1, symbol.end - 1, insertion))
        else:
            replacements.append((atom.start, atom.end, _quoted(property_value)))
    return _apply(text, replacements)


def generated_names(artifacts: ArtifactSet, lcsc_id: str) -> tuple[str, str]:
    symbol_name = ""
    footprint_name = ""
    if artifacts.symbol_libraries:
        root = parse_one(artifacts.symbol_libraries[0].read_text(encoding="utf-8-sig"))
        matches = tuple(
            child
            for child in root.children
            if child.head == "symbol"
            and (_property_atom(child, "LCSC Part") or Atom("", 0, 0)).value == lcsc_id
        )
        if len(matches) != 1 or len(matches[0].atoms) < 2:
            raise ValueError(f"expected one generated symbol for {lcsc_id}")
        symbol_name = matches[0].atoms[1].value
    if artifacts.footprints:
        root = parse_one(artifacts.footprints[0].read_text(encoding="utf-8-sig"))
        if root.head not in {"footprint", "module"} or len(root.atoms) < 2:
            raise ValueError("generated footprint has no root name")
        footprint_name = root.atoms[1].value.rsplit(":", 1)[-1]
    return symbol_name, footprint_name


def normalize_footprint_root(text: str, name: str) -> str:
    """Return a KiCad-library footprint with a modern root and filename-safe name."""

    normalized = validate_component_name(name, "footprint")
    root = parse_one(text)
    if root.head not in {"footprint", "module"} or len(root.atoms) < 2:
        raise ValueError("converted output is not a footprint or module")
    replacements = [(root.atoms[1].start, root.atoms[1].end, _quoted(normalized))]
    if root.head == "module":
        replacements.append((root.atoms[0].start, root.atoms[0].end, "footprint"))
    return _apply(text, replacements)


def rewrite_footprint_component(
    text: str, new_name: str, *, model_mode: str, model_dir: Path
) -> str:
    normalized = validate_component_name(new_name, "footprint")
    selected = normalize_footprint_root(
        rewrite_footprint_models(text, model_mode), normalized
    )
    root = parse_one(selected)
    replacements: list[tuple[int, int, str]] = []
    for child in root.children:
        atoms = child.atoms
        if child.head == "fp_text" and len(atoms) >= 3 and atoms[1].value == "value":
            replacements.append((atoms[2].start, atoms[2].end, _quoted(normalized)))
        if child.head == "property" and len(atoms) >= 3 and atoms[1].value == "Value":
            replacements.append((atoms[2].start, atoms[2].end, _quoted(normalized)))
        if child.head == "model" and len(atoms) >= 2:
            filename = Path(atoms[1].value).name
            if model_mode == "step":
                filename = Path(filename).with_suffix(".step").name
            destination = (model_dir.resolve() / filename).as_posix()
            replacements.append((atoms[1].start, atoms[1].end, _quoted(destination)))
    return _apply(selected, replacements)
