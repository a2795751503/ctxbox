"""MCP 服务器管理 (CC Switch 风格): 列表 / 新建 / 编辑 / 删除。

存储位置 (真机验证):
- Claude Code: ~/.claude.json 的 "mcpServers" 字典
- Codex: ~/.codex/config.toml 的 [mcp_servers.<name>] 表

安全契约与 providers 相同: 写前必备份, 原子写入, 其余配置原样保留;
list 永远只读。仅支持 stdio 类型 (绝大多数本地 MCP 的形态)。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import tomllib

from . import providers
from .providers import codex_config_path, dump_toml
from .utils import atomic_write, dotdir, make_backup


@dataclass
class McpServer:
    name: str
    command: str = ""
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    startup_timeout_sec: float | None = None  # codex 可选
    tool: str = ""

    def summary(self) -> str:
        arg_text = " ".join(self.args)
        return f"{self.command} {arg_text}".strip()


def claude_config_path() -> Path:
    return dotdir(".claude.json")


def _load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}


def _load_toml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return {}


def list_servers(tool: str) -> list[McpServer]:
    """列出该工具全部 MCP 服务器 (只读)。"""
    if tool == "claude-code":
        raw = _load_json(claude_config_path()).get("mcpServers") or {}
        return [
            McpServer(
                name=name,
                command=str(cfg.get("command", "")),
                args=[str(a) for a in cfg.get("args") or []],
                env={str(k): str(v) for k, v in (cfg.get("env") or {}).items()},
                tool=tool,
            )
            for name, cfg in raw.items()
            if isinstance(cfg, dict)
        ]
    if tool == "codex":
        raw = _load_toml(codex_config_path()).get("mcp_servers") or {}
        return [
            McpServer(
                name=name,
                command=str(cfg.get("command", "")),
                args=[str(a) for a in cfg.get("args") or []],
                env={str(k): str(v) for k, v in (cfg.get("env") or {}).items()},
                startup_timeout_sec=cfg.get("startup_timeout_sec"),
                tool=tool,
            )
            for name, cfg in raw.items()
            if isinstance(cfg, dict)
        ]
    raise ValueError(f"unsupported tool: {tool}")


def upsert_server(tool: str, server: McpServer) -> Path:
    """新建或覆盖同名 MCP 服务器。写前备份, 其余配置原样保留。"""
    if not server.name.strip():
        raise ValueError("MCP 名称不能为空")
    if not server.command.strip():
        raise ValueError("启动命令不能为空")
    if tool == "claude-code":
        path = claude_config_path()
        data = _load_json(path)
        if path.exists():
            make_backup(path, providers._backup_root())
        servers = dict(data.get("mcpServers") or {})
        entry: dict[str, Any] = {
            "type": "stdio",
            "command": server.command,
            "args": list(server.args),
        }
        if server.env:
            entry["env"] = dict(server.env)
        servers[server.name] = entry
        data["mcpServers"] = servers
        atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        return path
    if tool == "codex":
        path = codex_config_path()
        data = _load_toml(path)
        if path.exists():
            make_backup(path, providers._backup_root())
        servers = dict(data.get("mcp_servers") or {})
        entry = {
            "type": "stdio",
            "command": server.command,
            "args": list(server.args),
        }
        if server.env:
            entry["env"] = dict(server.env)
        if server.startup_timeout_sec is not None:
            entry["startup_timeout_sec"] = float(server.startup_timeout_sec)
        servers[server.name] = entry
        data["mcp_servers"] = servers
        atomic_write(path, dump_toml(data).encode("utf-8"))
        return path
    raise ValueError(f"unsupported tool: {tool}")


def delete_server(tool: str, name: str) -> Path:
    """删除指定 MCP 服务器 (不存在也安全返回)。"""
    if tool == "claude-code":
        path = claude_config_path()
        data = _load_json(path)
        servers = dict(data.get("mcpServers") or {})
        if name not in servers:
            return path
        make_backup(path, providers._backup_root())
        del servers[name]
        data["mcpServers"] = servers
        atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
        return path
    if tool == "codex":
        path = codex_config_path()
        data = _load_toml(path)
        servers = dict(data.get("mcp_servers") or {})
        if name not in servers:
            return path
        make_backup(path, providers._backup_root())
        del servers[name]
        data["mcp_servers"] = servers
        atomic_write(path, dump_toml(data).encode("utf-8"))
        return path
    raise ValueError(f"unsupported tool: {tool}")
