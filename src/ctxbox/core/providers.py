"""供应商配置中心 (CC Switch 风格): 预设管理 + 一键切换当前配置。

支持工具:
- Claude Code: ~/.claude/settings.json 的 env 块
  (ANTHROPIC_BASE_URL / ANTHROPIC_AUTH_TOKEN / ANTHROPIC_MODEL)
- Codex: ~/.codex/config.toml 的 model_provider / model 与
  [model_providers.<id>] 表 (name/base_url/wire_api/token)

安全契约:
- 预设存在 ctxbox 自己的 providers.json, 不改它不会影响任何工具
- apply 写真实配置前必做备份 (make_backup), 原子写入, 其余配置原样保留
- 除 apply 外的一切操作都是只读的
"""

from __future__ import annotations

import json
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import tomllib

from .utils import atomic_write, ctxbox_data_dir, dotdir, make_backup

TOOLS = ("claude-code", "codex")
TOOL_LABELS = {"claude-code": "Claude Code", "codex": "Codex CLI"}


# --------------------------------------------------------------------- 模型 --
@dataclass
class ProviderPreset:
    """一个可复用的供应商配置预设。"""

    tool: str
    name: str
    base_url: str = ""
    api_key: str = ""
    model: str = ""
    wire_api: str = "responses"  # codex 专用: responses / chat
    notes: str = ""
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])

    def masked_key(self) -> str:
        if not self.api_key:
            return "(未设置)"
        if len(self.api_key) <= 8:
            return "****"
        return f"{self.api_key[:4]}…{self.api_key[-4:]}"


# ------------------------------------------------------------------ 预设仓库 --
class PresetStore:
    """providers.json: {"presets": [...]} — CRUD 全部原子落盘。"""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (ctxbox_data_dir() / "providers.json")

    def _read(self) -> list[ProviderPreset]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        presets = []
        for item in data.get("presets", []):
            try:
                presets.append(ProviderPreset(**item))
            except TypeError:
                continue  # 旧版本字段不兼容时跳过而不是全崩
        return presets

    def _write(self, presets: list[ProviderPreset]) -> None:
        payload = {"version": 1, "presets": [asdict(p) for p in presets]}
        atomic_write(self.path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))

    def list(self, tool: str | None = None) -> list[ProviderPreset]:
        presets = self._read()
        return [p for p in presets if tool is None or p.tool == tool]

    def get(self, preset_id: str) -> ProviderPreset | None:
        return next((p for p in self._read() if p.id == preset_id), None)

    def upsert(self, preset: ProviderPreset) -> None:
        presets = self._read()
        for i, p in enumerate(presets):
            if p.id == preset.id:
                presets[i] = preset
                break
        else:
            presets.append(preset)
        self._write(presets)

    def delete(self, preset_id: str) -> bool:
        presets = self._read()
        kept = [p for p in presets if p.id != preset_id]
        if len(kept) == len(presets):
            return False
        self._write(kept)
        return True


# --------------------------------------------------------------- TOML 写出 --
def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)  # JSON 转义与 TOML 基本兼容
    if isinstance(value, list):
        return "[ " + ", ".join(_toml_scalar(v) for v in value) + " ]"
    raise TypeError(f"unsupported TOML value: {type(value)!r}")


def _toml_is_table(value: Any) -> bool:
    return isinstance(value, dict)


def _toml_key(key: str) -> str:
    """裸 key 仅允许 A-Za-z0-9_-; 其余 (@, 点, 空格, 中文…) 必须加引号。"""
    return key if all(c.isalnum() or c in "_-" for c in key) else json.dumps(key)


def dump_toml(data: dict[str, Any], _prefix: str = "") -> str:
    """最小 TOML 序列化器: 标量/数组/嵌套表, 保持配置语义不变。"""
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not _toml_is_table(v)}
    tables = {k: v for k, v in data.items() if _toml_is_table(v)}
    for k, v in scalars.items():
        lines.append(f"{_toml_key(k)} = {_toml_scalar(v)}")
    for k, v in tables.items():
        full = f"{_prefix}.{_toml_key(k)}" if _prefix else _toml_key(k)
        lines.append("")
        lines.append(f"[{full}]")
        body = dump_toml(v, full)
        if body:
            lines.append(body.rstrip("\n"))
    return "\n".join(lines) + ("\n" if lines else "")


# ------------------------------------------------------------ 真实配置读写 --
def claude_settings_path() -> Path:
    return dotdir(".claude") / "settings.json"


def codex_config_path() -> Path:
    return dotdir(".codex") / "config.toml"


def read_current(tool: str) -> dict[str, Any]:
    """读取工具当前生效的供应商配置 (只读, 文件不存在返回空)。"""
    if tool == "claude-code":
        p = claude_settings_path()
        data: dict[str, Any] = {}
        if p.exists():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}
        env = data.get("env") or {}
        return {
            "tool": tool,
            "base_url": env.get("ANTHROPIC_BASE_URL", ""),
            "api_key": env.get("ANTHROPIC_AUTH_TOKEN") or env.get("ANTHROPIC_API_KEY", ""),
            "model": env.get("ANTHROPIC_MODEL", ""),
            "path": str(p),
        }
    if tool == "codex":
        p = codex_config_path()
        data: dict[str, Any] = {}
        if p.exists():
            try:
                data = tomllib.loads(p.read_text(encoding="utf-8"))
            except (OSError, tomllib.TOMLDecodeError):
                data = {}
        provider_id = data.get("model_provider", "")
        provider = (data.get("model_providers") or {}).get(provider_id) or {}
        return {
            "tool": tool,
            "provider_id": provider_id,
            "base_url": provider.get("base_url", ""),
            "api_key": provider.get("experimental_bearer_token", ""),
            "model": data.get("model", ""),
            "wire_api": provider.get("wire_api", ""),
            "path": str(p),
        }
    raise ValueError(f"unsupported tool: {tool}")


def _backup_root() -> Path:
    return ctxbox_data_dir() / "backups"


def apply_preset(preset: ProviderPreset) -> Path:
    """把预设写为工具的当前配置。返回真实配置文件路径。

    写前自动备份; 除供应商相关字段外的一切配置原样保留。
    """
    if preset.tool == "claude-code":
        return _apply_claude(preset)
    if preset.tool == "codex":
        return _apply_codex(preset)
    raise ValueError(f"unsupported tool: {preset.tool}")


def _apply_claude(preset: ProviderPreset) -> Path:
    path = claude_settings_path()
    data: dict[str, Any] = {}
    if path.exists():
        make_backup(path, _backup_root())
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = {}
    env = dict(data.get("env") or {})
    env["ANTHROPIC_BASE_URL"] = preset.base_url
    env["ANTHROPIC_AUTH_TOKEN"] = preset.api_key
    if preset.model:
        env["ANTHROPIC_MODEL"] = preset.model
    elif "ANTHROPIC_MODEL" in env:
        del env["ANTHROPIC_MODEL"]
    data["env"] = env
    atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8"))
    return path


def _apply_codex(preset: ProviderPreset) -> Path:
    path = codex_config_path()
    data: dict[str, Any] = {}
    if path.exists():
        make_backup(path, _backup_root())
        try:
            data = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError:
            data = {}
    provider_id = f"ctxbox_{preset.id}"
    providers = dict(data.get("model_providers") or {})
    providers[provider_id] = {
        "name": preset.name,
        "base_url": preset.base_url,
        "wire_api": preset.wire_api or "responses",
        "requires_openai_auth": False,
        "experimental_bearer_token": preset.api_key,
    }
    data["model_providers"] = providers
    data["model_provider"] = provider_id
    if preset.model:
        data["model"] = preset.model
    atomic_write(path, dump_toml(data).encode("utf-8"))
    return path


def active_preset_id(tool: str, store: PresetStore | None = None) -> str | None:
    """判断当前配置匹配哪个预设 (按 base_url+model 比对)。"""
    store = store or PresetStore()
    try:
        current = read_current(tool)
    except Exception:  # noqa: BLE001
        return None
    for p in store.list(tool):
        if p.base_url and p.base_url == current.get("base_url"):
            if tool == "codex" and current.get("provider_id") == f"ctxbox_{p.id}":
                return p.id
            if tool == "claude-code" and (not p.model or p.model == current.get("model")):
                return p.id
    return None


# ------------------------------------------------------------ 存为预设/导入导出 --
def preset_from_current(tool: str) -> ProviderPreset:
    """把工具当前生效的配置读成一个新预设 (不落盘, 由调用方确认后保存)。"""
    cur = read_current(tool)
    return ProviderPreset(
        tool=tool,
        name="",
        base_url=cur.get("base_url", ""),
        api_key=cur.get("api_key", ""),
        model=cur.get("model", ""),
        wire_api=cur.get("wire_api") or "responses",
        notes="从当前配置导入",
    )


def export_presets(path: Path, store: PresetStore, tool: str | None = None) -> int:
    """导出预设为 JSON 文件, 返回条数。tool=None 导出全部。"""
    presets = store.list(tool)
    payload = {"app": "ctxbox", "version": 1, "presets": [asdict(p) for p in presets]}
    atomic_write(path, json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8"))
    return len(presets)


def import_presets(path: Path, store: PresetStore) -> int:
    """从 JSON 文件导入预设, id 冲突时换新 id (不覆盖已有预设)。返回导入条数。"""
    data = json.loads(path.read_text(encoding="utf-8"))
    items = data.get("presets") if isinstance(data, dict) else data
    if not isinstance(items, list):
        raise ValueError("文件里没有 presets 列表")
    existing = {p.id for p in store.list()}
    count = 0
    for item in items:
        try:
            preset = ProviderPreset(**item)
        except TypeError:
            continue
        if preset.tool not in TOOLS:
            continue
        if preset.id in existing:
            preset.id = uuid.uuid4().hex[:12]
        store.upsert(preset)
        existing.add(preset.id)
        count += 1
    return count
