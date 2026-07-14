"""A small, span-preserving S-expression scanner for KiCad files."""

import json
import re
from dataclasses import dataclass
from typing import TypeAlias


class SExprError(ValueError):
    """Raised when an S-expression cannot be scanned safely."""


@dataclass(frozen=True, slots=True)
class Atom:
    value: str
    start: int
    end: int
    quoted: bool = False


@dataclass(frozen=True, slots=True)
class ListExpr:
    items: tuple["Node", ...]
    start: int
    end: int

    @property
    def head(self) -> str | None:
        if self.items and isinstance(self.items[0], Atom):
            return self.items[0].value
        return None

    @property
    def children(self) -> tuple["ListExpr", ...]:
        return tuple(item for item in self.items if isinstance(item, ListExpr))

    @property
    def atoms(self) -> tuple[Atom, ...]:
        return tuple(item for item in self.items if isinstance(item, Atom))


Node: TypeAlias = Atom | ListExpr


class _Parser:
    def __init__(self, text: str) -> None:
        self.text = text
        self.length = len(text)

    def skip_space(self, index: int) -> int:
        while index < self.length and self.text[index].isspace():
            index += 1
        return index

    def parse_atom(self, index: int) -> tuple[Atom, int]:
        start = index
        if self.text[index] == '"':
            index += 1
            value: list[str] = []
            while index < self.length:
                char = self.text[index]
                if char == "\\":
                    index += 1
                    if index >= self.length:
                        raise SExprError("字符串转义不完整。")
                    value.append(self.text[index])
                    index += 1
                elif char == '"':
                    return Atom("".join(value), start, index + 1, True), index + 1
                else:
                    value.append(char)
                    index += 1
            raise SExprError("字符串没有结束引号。")

        while index < self.length and not self.text[index].isspace() and self.text[index] not in "()":
            index += 1
        if index == start:
            raise SExprError(f"无法解析位置 {index}。")
        return Atom(self.text[start:index], start, index), index

    def parse_list(self, index: int) -> tuple[ListExpr, int]:
        if index >= self.length or self.text[index] != "(":
            raise SExprError(f"位置 {index} 缺少左括号。")
        start = index
        index += 1
        items: list[Node] = []
        while True:
            index = self.skip_space(index)
            if index >= self.length:
                raise SExprError("S 表达式括号不完整。")
            if self.text[index] == ")":
                return ListExpr(tuple(items), start, index + 1), index + 1
            if self.text[index] == "(":
                item, index = self.parse_list(index)
            else:
                item, index = self.parse_atom(index)
            items.append(item)


def parse_one(text: str) -> ListExpr:
    parser = _Parser(text)
    start = parser.skip_space(0)
    if start >= len(text):
        raise SExprError("S 表达式为空。")
    expression, index = parser.parse_list(start)
    if parser.skip_space(index) != len(text):
        raise SExprError("根表达式后存在无法识别的内容。")
    return expression


def _has_property(expression: ListExpr, name: str, value: str) -> bool:
    for child in expression.children:
        atoms = child.atoms
        if child.head == "property" and len(atoms) >= 3:
            if atoms[1].value == name and atoms[2].value == value:
                return True
    return False


def find_symbol_spans_by_property(text: str, name: str, value: str) -> tuple[tuple[int, int], ...]:
    root = parse_one(text)
    return tuple(
        (child.start, child.end)
        for child in root.children
        if child.head == "symbol" and _has_property(child, name, value)
    )


def remove_spans(text: str, spans: tuple[tuple[int, int], ...]) -> str:
    updated = text
    for start, end in sorted(spans, reverse=True):
        if start < 0 or end > len(updated) or start >= end:
            raise ValueError("invalid text span")
        updated = updated[:start] + updated[end:]
    return updated


def rewrite_footprint_models(text: str, mode: str) -> str:
    if mode not in {"wrl", "step", "none"}:
        raise ValueError("model mode must be wrl, step, or none")
    root = parse_one(text)
    models = tuple(child for child in root.children if child.head == "model")
    if mode == "none":
        return remove_spans(text, tuple((model.start, model.end) for model in models))
    if mode == "wrl":
        return text

    replacements: list[tuple[int, int, str]] = []
    for model in models:
        atoms = model.atoms
        if len(atoms) < 2:
            continue
        path_atom = atoms[1]
        path = re.sub(r"(?i)\.(?:wrl|stp|step)$", ".step", path_atom.value)
        replacements.append((path_atom.start, path_atom.end, json.dumps(path)))
    updated = text
    for start, end, replacement in sorted(replacements, reverse=True):
        updated = updated[:start] + replacement + updated[end:]
    return updated

