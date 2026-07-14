from pathlib import Path
from types import SimpleNamespace

from jlceda2kicad.project_context import context_from_path, detect_ipc_context


def test_context_from_project_file_supports_chinese_and_spaces(tmp_path: Path) -> None:
    project = tmp_path / "中文 项目.kicad_pro"
    board = tmp_path / "中文 项目.kicad_pcb"
    project.write_text("{}", encoding="utf-8")
    board.write_text("(kicad_pcb)", encoding="utf-8")

    context = context_from_path(project)

    assert context.project_root == tmp_path
    assert context.project_file == project
    assert context.board_file == board
    assert context.source == "manual"


def test_context_from_directory_finds_matching_project_and_board(tmp_path: Path) -> None:
    project = tmp_path / "demo.kicad_pro"
    board = tmp_path / "demo.kicad_pcb"
    project.write_text("{}", encoding="utf-8")
    board.write_text("(kicad_pcb)", encoding="utf-8")

    context = context_from_path(tmp_path)

    assert context.project_file == project
    assert context.board_file == board


def test_context_from_missing_path_returns_invalid_context(tmp_path: Path) -> None:
    context = context_from_path(tmp_path / "missing")

    assert not context.is_valid
    assert context.source == "none"


def test_detect_ipc_context_uses_official_document_fields(tmp_path: Path) -> None:
    document = SimpleNamespace(
        project=SimpleNamespace(path=str(tmp_path), name="demo"),
        board_filename="demo.kicad_pcb",
    )
    board = SimpleNamespace(document=document)
    fake = SimpleNamespace(get_board=lambda: board, get_version=lambda: "10.0.4")

    context = detect_ipc_context(lambda: fake)

    assert context.project_root == tmp_path
    assert context.project_file == tmp_path / "demo.kicad_pro"
    assert context.board_file == tmp_path / "demo.kicad_pcb"
    assert context.kicad_version == "10.0.4"
    assert context.source == "ipc"
