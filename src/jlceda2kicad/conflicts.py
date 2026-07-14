"""Component-level conflict detection and narrowly scoped merge helpers."""

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .models import ConflictPolicy
from .sexpr import Atom, ListExpr, parse_one, remove_spans


class ComponentConflictError(RuntimeError):
    """Raised when the selected policy does not permit an existing item."""


@dataclass(frozen=True, slots=True)
class SymbolMergeResult:
    text: str
    skipped: bool = False
    overwritten_names: tuple[str, ...] = ()


def _symbol_name(symbol: ListExpr) -> str:
    atoms = symbol.atoms
    if len(atoms) < 2:
        raise ValueError("符号节点缺少名称。")
    return atoms[1].value


def _property_value(symbol: ListExpr, property_name: str) -> str | None:
    for child in symbol.children:
        atoms = child.atoms
        if child.head == "property" and len(atoms) >= 3:
            if atoms[1].value == property_name:
                return atoms[2].value
    return None


def _top_level_symbols(root: ListExpr) -> tuple[ListExpr, ...]:
    return tuple(child for child in root.children if child.head == "symbol")


def merge_symbol_library(
    existing_text: str | None,
    incoming_text: str,
    lcsc_id: str,
    policy: ConflictPolicy,
) -> SymbolMergeResult:
    """Merge one generated component without rewriting unrelated symbol nodes."""

    incoming_root = parse_one(incoming_text)
    if incoming_root.head != "kicad_symbol_lib":
        raise ValueError("转换输出不是 KiCad 符号库。")
    incoming_symbols = _top_level_symbols(incoming_root)
    if not incoming_symbols:
        raise ValueError("转换输出不包含符号节点。")
    incoming_names = {_symbol_name(symbol) for symbol in incoming_symbols}

    if existing_text is None:
        return SymbolMergeResult(incoming_text)

    existing_root = parse_one(existing_text)
    if existing_root.head != "kicad_symbol_lib":
        raise ValueError("现有文件不是 KiCad 符号库。")
    collisions = tuple(
        symbol
        for symbol in _top_level_symbols(existing_root)
        if _symbol_name(symbol) in incoming_names
        or _property_value(symbol, "LCSC Part") == lcsc_id
    )
    if collisions and policy is ConflictPolicy.CANCEL:
        details = ", ".join(_symbol_name(symbol) for symbol in collisions)
        raise ComponentConflictError(f"符号冲突：{lcsc_id}（{details}）")
    if collisions and policy is ConflictPolicy.SKIP_EXISTING:
        return SymbolMergeResult(existing_text, skipped=True)

    base = existing_text
    overwritten: tuple[str, ...] = ()
    if collisions:
        overwritten = tuple(_symbol_name(symbol) for symbol in collisions)
        base = remove_spans(
            base, tuple((symbol.start, symbol.end) for symbol in collisions)
        )

    symbol_source = "\n".join(
        incoming_text[symbol.start : symbol.end] for symbol in incoming_symbols
    )
    insert_at = base.rfind(")")
    if insert_at < 0:
        raise ValueError("现有符号库缺少结束括号。")
    prefix = base[:insert_at].rstrip()
    merged = f"{prefix}\n  {symbol_source}\n{base[insert_at:]}"
    return SymbolMergeResult(merged, overwritten_names=overwritten)


def resolve_file_conflicts(
    staged_to_target: Mapping[Path, Path], policy: ConflictPolicy
) -> tuple[dict[Path, Path], tuple[Path, ...]]:
    """Apply a policy per file, allowing missing artifacts to remain importable."""

    existing = tuple(target for target in staged_to_target.values() if target.exists())
    if existing and policy is ConflictPolicy.CANCEL:
        names = ", ".join(path.name for path in existing)
        raise ComponentConflictError(f"文件冲突：{names}")
    if policy is ConflictPolicy.SKIP_EXISTING:
        selected = {
            staged: target
            for staged, target in staged_to_target.items()
            if not target.exists()
        }
        return selected, existing
    return dict(staged_to_target), ()

