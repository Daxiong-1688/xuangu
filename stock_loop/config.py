from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_yaml_compatible(path: Path) -> dict[str, Any]:
    """Load JSON-formatted YAML without requiring third-party packages."""
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"缺少配置文件：{path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"配置文件 {path} 当前使用 JSON 兼容 YAML 格式，请保持合法 JSON 语法：{exc}"
        ) from exc


def load_project_config(root: Path) -> dict[str, dict[str, Any]]:
    return {
        "strategy": load_yaml_compatible(root / "config" / "strategy.yaml"),
        "data_source": load_yaml_compatible(root / "config" / "data_source.yaml"),
        "run": load_yaml_compatible(root / "config" / "run_config.yaml"),
    }
