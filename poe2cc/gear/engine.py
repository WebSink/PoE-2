"""Адаптер к реальному движку PoB2 через существующий `pob-mcp` (stdio MCP).

Здесь нет ни строчки игровой математики: модуль только разговаривает с MCP-сервером
по JSON-RPC 2.0 (newline-delimited, как требует stdio-транспорт MCP) и возвращает
то, что посчитал PoB2.

Ошибки разделены намеренно:

* `EngineUnavailable` — сервер не найден, не запустился или не ответил на
  `initialize`. Это не «нет улучшений», а «нечем считать»;
* `EngineCalculationError` — сервер ответил ошибкой (например, PoB2 не разобрал
  текст предмета) или не ответил вовремя.
"""

from __future__ import annotations

import contextlib
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROTOCOL_VERSION = "2025-06-18"
CLIENT_NAME = "poe2cc-gear-analyzer"
CLIENT_VERSION = "0.1.0"


class EngineError(RuntimeError):
    """Базовая ошибка движка."""


class EngineUnavailable(EngineError):
    """Движок недоступен: не найден, не запустился, не отвечает на handshake."""


class EngineCalculationError(EngineError):
    """Движок доступен, но расчёт или вызов инструмента завершился ошибкой."""


@dataclass(frozen=True)
class EngineInfo:
    command: str
    transport: str = "pob-mcp (stdio MCP)"
    pob2_version: str = "unknown"
    tree_data_version: str = "unknown"
    protocol_version: str = DEFAULT_PROTOCOL_VERSION

    def as_dict(self) -> dict:
        return {
            "name": "Path of Building - PoE2",
            "version": self.pob2_version,
            "tree_data_version": self.tree_data_version,
            "transport": self.transport,
            "command": self.command,
            "protocol_version": self.protocol_version,
        }


class PobEngine(Protocol):
    """Порт движка: всё, что анализатору нужно от PoB2."""

    def load_build(self, source: str) -> dict: ...

    def set_config(self, var: str, value: Any) -> None: ...

    def get_stats(self, fields: list[str] | None = None) -> dict[str, Any]: ...

    def get_skills(self) -> dict: ...

    def get_items(self) -> dict: ...

    def equip_item(self, item_text: str, slot: str | None = None) -> dict: ...

    def unequip_item(self, slot: str) -> dict: ...

    def sanity_check(self) -> list[str]: ...

    def close(self) -> None: ...


# --------------------------------------------------------------------------- #
# Поиск установки
# --------------------------------------------------------------------------- #
def locate_engine_command(explicit: str | None = None) -> str | None:
    """Ищет исполняемый файл pob-mcp: аргумент → env → локальная установка → PATH."""
    candidates: list[Path] = []
    for value in (explicit, os.environ.get("POE2CC_POB_MCP_CMD")):
        if value:
            candidates.append(Path(value))
    candidates.extend(
        [
            ROOT / ".tools" / "pob-mcp" / ".venv" / "Scripts" / "pob-mcp.exe",
            ROOT / ".tools" / "pob-mcp" / ".venv" / "bin" / "pob-mcp",
        ]
    )
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which("pob-mcp")
    return found


def engine_env() -> dict[str, str]:
    env = dict(os.environ)
    install_dir = env.get("POB_MCP_INSTALL_DIR") or str(ROOT / ".tools" / "pob2")
    luajit = env.get("POB_MCP_LUAJIT") or str(ROOT / ".tools" / "luajit" / "bin" / "luajit.exe")
    if Path(install_dir).exists():
        env["POB_MCP_INSTALL_DIR"] = install_dir
    if Path(luajit).exists():
        env["POB_MCP_LUAJIT"] = luajit
    env.setdefault("POB_MCP_LOG_LEVEL", "WARNING")
    env.setdefault("PYTHONIOENCODING", "utf-8")
    return env


_VERSION_LINE = re.compile(r"^VERSION\[(?P<version>[^\]]+)\]")


def detect_pob2_version(install_dir: str | Path | None = None) -> tuple[str, str]:
    """Возвращает (версия PoB2, версия данных дерева) по локальной установке."""
    directory = Path(
        install_dir or os.environ.get("POB_MCP_INSTALL_DIR") or ROOT / ".tools" / "pob2"
    )
    version = "unknown"
    changelog = directory / "changelog.txt"
    if changelog.is_file():
        try:
            with changelog.open(encoding="utf-8", errors="replace") as handle:
                match = _VERSION_LINE.match(handle.readline().strip())
            if match:
                version = match.group("version")
        except OSError:
            pass

    tree_data = "unknown"
    game_versions = directory / "GameVersions.lua"
    if game_versions.is_file():
        try:
            text = game_versions.read_text(encoding="utf-8", errors="replace")
            entries = re.findall(r'"(0_\d+)"', text)
            if entries:
                tree_data = entries[-1]
        except OSError:
            pass
    return version, tree_data


# --------------------------------------------------------------------------- #
# stdio-клиент MCP
# --------------------------------------------------------------------------- #
class McpStdioEngine:
    """Минимальный MCP-клиент: `initialize` + `tools/call` по stdio."""

    def __init__(
        self,
        command: str | None = None,
        *,
        env: dict[str, str] | None = None,
        timeout: float = 120.0,
        start_timeout: float = 90.0,
    ) -> None:
        resolved = locate_engine_command(command)
        if not resolved:
            raise EngineUnavailable(
                "не найден pob-mcp: задайте POE2CC_POB_MCP_CMD или установите "
                ".tools/pob-mcp (см. docs/integrations/mcp-status.md)"
            )
        self._command = resolved
        self._env = env if env is not None else engine_env()
        self._timeout = timeout
        self._start_timeout = start_timeout
        self._next_id = 0
        self._responses: queue.Queue[dict] = queue.Queue()
        self._stderr_tail: list[str] = []
        self._closed = False
        self._process: subprocess.Popen[str] | None = None
        self._info = EngineInfo(command=resolved)

    # -- жизненный цикл ------------------------------------------------------ #
    def __enter__(self) -> McpStdioEngine:
        self.start()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    def start(self) -> None:
        if self._process is not None:
            return
        try:
            self._process = subprocess.Popen(
                [self._command],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=self._env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        except OSError as exc:
            raise EngineUnavailable(f"pob-mcp не запускается ({self._command}): {exc}") from exc

        threading.Thread(target=self._read_stdout, name="pob-mcp-stdout", daemon=True).start()
        threading.Thread(target=self._read_stderr, name="pob-mcp-stderr", daemon=True).start()

        version, tree_data = detect_pob2_version(self._env.get("POB_MCP_INSTALL_DIR"))
        self._info = EngineInfo(
            command=self._command,
            pob2_version=version,
            tree_data_version=tree_data,
        )

        try:
            self._request(
                "initialize",
                {
                    "protocolVersion": DEFAULT_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
                },
                timeout=self._start_timeout,
            )
        except EngineError as exc:
            self.close()
            raise EngineUnavailable(f"pob-mcp не прошёл handshake: {exc}") from exc

        self._notify("notifications/initialized", {})

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        process = self._process
        self._process = None
        if process is None:
            return
        try:
            if process.stdin:
                process.stdin.close()
        except OSError:
            pass
        try:
            process.terminate()
            process.wait(timeout=10)
        except (OSError, subprocess.TimeoutExpired):
            with contextlib.suppress(OSError):
                process.kill()

    # -- транспорт ----------------------------------------------------------- #
    def _read_stdout(self) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        for line in process.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            self._responses.put(message)
        self._responses.put({"__eof__": True})

    def _read_stderr(self) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        for line in process.stderr:
            self._stderr_tail.append(line.rstrip())
            del self._stderr_tail[:-40]

    def _send(self, message: dict) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise EngineUnavailable("pob-mcp не запущен")
        try:
            process.stdin.write(json.dumps(message, ensure_ascii=False) + "\n")
            process.stdin.flush()
        except (OSError, ValueError) as exc:
            raise EngineUnavailable(f"канал к pob-mcp закрыт: {exc}") from exc

    def _notify(self, method: str, params: dict) -> None:
        self._send({"jsonrpc": "2.0", "method": method, "params": params})

    def _request(self, method: str, params: dict | None = None, timeout: float | None = None):
        self._next_id += 1
        request_id = self._next_id
        message: dict[str, Any] = {"jsonrpc": "2.0", "id": request_id, "method": method}
        if params is not None:
            message["params"] = params
        self._send(message)

        deadline = time.monotonic() + (timeout if timeout is not None else self._timeout)
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise EngineCalculationError(
                    f"pob-mcp не ответил на {method} за {timeout or self._timeout:g} с"
                )
            try:
                response = self._responses.get(timeout=remaining)
            except queue.Empty:
                raise EngineCalculationError(
                    f"pob-mcp не ответил на {method} за {timeout or self._timeout:g} с"
                ) from None
            if response.get("__eof__"):
                raise EngineUnavailable(
                    "pob-mcp закрыл поток вывода"
                    + (f": {' | '.join(self._stderr_tail[-3:])}" if self._stderr_tail else "")
                )
            if response.get("id") != request_id:
                # уведомления и чужие ответы пропускаем
                continue
            if "error" in response:
                error = response["error"]
                raise EngineCalculationError(f"{method}: {error.get('message', error)}")
            return response.get("result", {})

    # -- tools/call ---------------------------------------------------------- #
    def call_tool(self, name: str, arguments: dict | None = None) -> Any:
        result = self._request("tools/call", {"name": name, "arguments": arguments or {}})
        if result.get("isError"):
            text = _content_text(result) or "без описания"
            raise EngineCalculationError(f"{name}: {text}")
        structured = result.get("structuredContent")
        if structured is not None:
            return structured
        text = _content_text(result)
        if text is None:
            return {}
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return text

    # -- инструменты pob-mcp ------------------------------------------------- #
    @property
    def info(self) -> EngineInfo:
        return self._info

    def load_build(self, source: str) -> dict:
        return self.call_tool("load_build", {"source": source})

    def set_config(self, var: str, value: Any) -> None:
        self.call_tool("set_config", {"var": var, "value": value})

    def get_stats(self, fields: list[str] | None = None) -> dict[str, Any]:
        result = self.call_tool("get_stats", {"fields": fields} if fields else {})
        if isinstance(result, dict) and "stats" in result and isinstance(result["stats"], dict):
            return result["stats"]
        if not isinstance(result, dict):
            raise EngineCalculationError(f"get_stats вернул не объект: {type(result).__name__}")
        return result

    def get_skills(self) -> dict:
        return self.call_tool("get_skills")

    def get_items(self) -> dict:
        return self.call_tool("get_items")

    def equip_item(self, item_text: str, slot: str | None = None) -> dict:
        arguments: dict[str, Any] = {"item_text": item_text}
        if slot:
            arguments["slot"] = slot
        return self.call_tool("equip_item_raw", arguments)

    def unequip_item(self, slot: str) -> dict:
        return self.call_tool("unequip_item", {"slot": slot})

    def sanity_check(self) -> list[str]:
        result = self.call_tool("sanity_check")
        if isinstance(result, dict):
            return list(result.get("result") or result.get("warnings") or [])
        return list(result or [])


def _content_text(result: dict) -> str | None:
    content = result.get("content")
    if not isinstance(content, list):
        return None
    for block in content:
        if isinstance(block, dict) and block.get("type") == "text":
            return block.get("text")
    return None


# --------------------------------------------------------------------------- #
# Фабрика
# --------------------------------------------------------------------------- #
EngineFactory = type[McpStdioEngine]


def open_engine(command: str | None = None, timeout: float = 120.0) -> McpStdioEngine:
    engine = McpStdioEngine(command, timeout=timeout)
    engine.start()
    return engine
