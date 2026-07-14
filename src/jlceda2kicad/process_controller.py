"""Asynchronous, shell-free QProcess adapter with timeout and cancellation."""

import locale
from dataclasses import dataclass

from PySide6.QtCore import QByteArray, QObject, QProcess, QProcessEnvironment, QTimer, Signal

from .easyeda_cli import CommandSpec
from .logging_config import redact_text


@dataclass(frozen=True, slots=True)
class ProcessResult:
    exit_code: int
    normal_exit: bool
    stdout: str
    stderr: str
    timed_out: bool = False
    cancelled: bool = False

    @property
    def succeeded(self) -> bool:
        return (
            self.exit_code == 0 and self.normal_exit and not self.timed_out and not self.cancelled
        )


class ProcessController(QObject):
    output = Signal(str)
    started = Signal()
    completed = Signal(object)

    def __init__(self, parent: QObject | None = None, *, kill_grace_ms: int = 1_000) -> None:
        super().__init__(parent)
        self._process = QProcess(self)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._kill_grace_ms = kill_grace_ms
        self._output_encoding = locale.getpreferredencoding(False)
        self._stdout: list[str] = []
        self._stderr: list[str] = []
        self._timed_out = False
        self._cancelled = False
        self._completed = False
        self._process.started.connect(self.started)
        self._process.readyReadStandardOutput.connect(self._read_stdout)
        self._process.readyReadStandardError.connect(self._read_stderr)
        self._process.finished.connect(self._on_finished)
        self._process.errorOccurred.connect(self._on_error)
        self._timer.timeout.connect(self._on_timeout)

    @property
    def is_running(self) -> bool:
        return self._process.state() != QProcess.ProcessState.NotRunning

    def start(self, command: CommandSpec, *, timeout_ms: int) -> None:
        if self.is_running:
            raise RuntimeError("已有转换进程正在运行。")
        if timeout_ms <= 0:
            raise ValueError("timeout_ms must be positive")
        self._stdout.clear()
        self._stderr.clear()
        self._timed_out = False
        self._cancelled = False
        self._completed = False
        self._process.setProcessEnvironment(QProcessEnvironment.systemEnvironment())
        self._process.setWorkingDirectory(str(command.working_dir))
        self._process.setProgram(str(command.program))
        self._process.setArguments(list(command.arguments))
        self._timer.start(timeout_ms)
        self._process.start()

    def cancel(self) -> None:
        if not self.is_running:
            return
        self._cancelled = True
        self._terminate_then_kill()

    def _on_timeout(self) -> None:
        if not self.is_running:
            return
        self._timed_out = True
        self._terminate_then_kill()

    def _terminate_then_kill(self) -> None:
        self._process.terminate()
        QTimer.singleShot(self._kill_grace_ms, self._kill_if_running)

    def _kill_if_running(self) -> None:
        if self.is_running:
            self._process.kill()

    def _read_stdout(self) -> None:
        self._record(_byte_array_bytes(self._process.readAllStandardOutput()), self._stdout)

    def _read_stderr(self) -> None:
        self._record(_byte_array_bytes(self._process.readAllStandardError()), self._stderr)

    def _record(self, data: bytes, destination: list[str]) -> None:
        if not data:
            return
        text = redact_text(data.decode(self._output_encoding, errors="replace"))
        destination.append(text)
        for line in text.splitlines():
            if line:
                self.output.emit(line)

    def _on_error(self, error: QProcess.ProcessError) -> None:
        if error == QProcess.ProcessError.FailedToStart and not self._completed:
            self._timer.stop()
            message = redact_text(self._process.errorString())
            self._stderr.append(message)
            self.output.emit(message)
            self._emit_completed(-1, False)

    def _on_finished(self, exit_code: int, exit_status: QProcess.ExitStatus) -> None:
        self._read_stdout()
        self._read_stderr()
        self._timer.stop()
        self._emit_completed(exit_code, exit_status == QProcess.ExitStatus.NormalExit)

    def _emit_completed(self, exit_code: int, normal_exit: bool) -> None:
        if self._completed:
            return
        self._completed = True
        self.completed.emit(
            ProcessResult(
                exit_code=exit_code,
                normal_exit=normal_exit,
                stdout="".join(self._stdout),
                stderr="".join(self._stderr),
                timed_out=self._timed_out,
                cancelled=self._cancelled,
            )
        )


def _byte_array_bytes(value: QByteArray) -> bytes:
    data = value.data()
    if isinstance(data, bytes):
        return data
    if isinstance(data, bytearray):
        return bytes(data)
    return data.tobytes()
