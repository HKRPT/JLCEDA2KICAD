"""Safety and consistency checks for generated KiCad artifacts."""

import re
from dataclasses import dataclass
from pathlib import Path

from .sexpr import ListExpr, SExprError, parse_one


class ImportValidationError(ValueError):
    """Raised when an artifact is unsafe or structurally invalid."""


@dataclass(frozen=True, slots=True)
class ArtifactValidation:
    pin_or_pad_numbers: frozenset[str] = frozenset()
    model_paths: tuple[str, ...] = ()

    def compare_pad_numbers(self, other: "ArtifactValidation") -> tuple[str, ...]:
        if self.pin_or_pad_numbers == other.pin_or_pad_numbers:
            return ()
        only_here = sorted(self.pin_or_pad_numbers - other.pin_or_pad_numbers)
        only_there = sorted(other.pin_or_pad_numbers - self.pin_or_pad_numbers)
        return (
            "符号引脚与封装焊盘编号不一致："
            f"仅符号 {only_here or '无'}；仅封装 {only_there or '无'}。",
        )


def _parse_file(path: Path, expected_head: str) -> ListExpr:
    if not path.is_file() or path.stat().st_size == 0:
        raise ImportValidationError(f"空文件或文件不存在：{path}")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as error:
        raise ImportValidationError(f"无法读取 UTF-8 文件：{path}: {error}") from error
    try:
        root = parse_one(text)
    except SExprError as error:
        raise ImportValidationError(f"S 表达式括号或字符串无效：{error}") from error
    if root.head != expected_head:
        raise ImportValidationError(
            f"文件类型错误：需要 {expected_head}，实际为 {root.head or '未知'}。"
        )
    return root


def _walk(expression: ListExpr) -> tuple[ListExpr, ...]:
    descendants: list[ListExpr] = []
    for child in expression.children:
        descendants.append(child)
        descendants.extend(_walk(child))
    return tuple(descendants)


def _child_atom(expression: ListExpr, head: str) -> str | None:
    for child in expression.children:
        if child.head == head and len(child.atoms) >= 2:
            return child.atoms[1].value
    return None


def validate_symbol_library(path: Path) -> ArtifactValidation:
    root = _parse_file(path, "kicad_symbol_lib")
    numbers = {
        number
        for node in _walk(root)
        if node.head == "pin"
        if (number := _child_atom(node, "number")) is not None
    }
    return ArtifactValidation(pin_or_pad_numbers=frozenset(numbers))


_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_MANAGED_MODEL_PREFIX = "${KIPRJMOD}/libs/lcsc_project.3dshapes/"


def _validate_model_path(model_path: str) -> None:
    normalized = model_path.replace("\\", "/")
    if (
        _WINDOWS_ABSOLUTE.match(model_path)
        or normalized.startswith("/")
        or "/temp/" in normalized.casefold()
    ):
        raise ImportValidationError(f"模型引用包含绝对路径或临时路径：{model_path}")
    if not normalized.startswith(_MANAGED_MODEL_PREFIX):
        raise ImportValidationError(f"模型引用不是工程相对受管路径：{model_path}")


def validate_footprint(path: Path) -> ArtifactValidation:
    root = _parse_file(path, "footprint")
    nodes = _walk(root)
    pad_numbers = {
        node.atoms[1].value
        for node in nodes
        if node.head == "pad" and len(node.atoms) >= 2 and node.atoms[1].value
    }
    model_paths = tuple(
        node.atoms[1].value
        for node in nodes
        if node.head == "model" and len(node.atoms) >= 2
    )
    for model_path in model_paths:
        _validate_model_path(model_path)
    return ArtifactValidation(frozenset(pad_numbers), model_paths)
