from __future__ import annotations

import json
import subprocess
from collections import deque
from json import JSONDecodeError
from pathlib import Path
from typing import Any


def read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (JSONDecodeError, OSError, UnicodeDecodeError):
        return {}


def tail_file(path: Path, lines: int = 100) -> list[str]:
    if not path.exists():
        return []
    buffer: deque[str] = deque(maxlen=max(lines, 1))
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            buffer.append(line.rstrip("\n"))
    return list(buffer)


def count_lines(path: Path) -> int:
    if not path.exists():
        return 0
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        return sum(1 for _ in handle)


def run_command(args: list[str], *, timeout: int = 5) -> tuple[bool, str]:
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            check=False,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, ""
    output = result.stdout.strip()
    if result.returncode != 0:
        output = output or result.stderr.strip()
        return False, output
    return True, output
