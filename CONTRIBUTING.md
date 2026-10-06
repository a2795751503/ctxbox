# Contributing to ctxbox / 为 ctxbox 做贡献

[English](#english) | [中文](#中文)

---

## English

First off, thank you! ctxbox grows by community adapters — every AI tool you add helps everyone.

### Ground rules

- **Privacy is sacred**: ctxbox never sends user data anywhere. PRs adding telemetry/network calls with user content will be rejected.
- **Never overwrite originals**: all write operations must be atomic (temp file + `os.replace`) and create a backup first.
- **Never lose data**: when parsing fails, degrade to a `raw` ContentPart with a warning — don't raise, don't skip silently.

### Dev setup

```bash
git clone https://github.com/a2795751503/ctxbox.git
cd ctxbox
pip install -e ".[dev]"
pytest
```

### Code style

- `ruff check src tests` and `ruff format` must pass (CI enforces it)
- `mypy src` should stay clean
- Commit messages follow [Conventional Commits](https://www.conventionalcommits.org): `feat:`, `fix:`, `adapter:`, `docs:` …
- Core (`src/ctxbox/core/`) must never import PySide6 — keep core GUI-free

### Adding a new adapter

Adding support for a new AI tool is the most valuable contribution. It's ~100 lines:

1. Create `src/ctxbox/core/adapters/my_tool.py`:

```python
from pathlib import Path
from .base import BaseAdapter, register
from ..model.schema import Session, Turn, ContentPart, Role

@register
class MyToolAdapter(BaseAdapter):
    name = "my-tool"
    display_name = "My Tool"

    def detect(self) -> list[Path]:
        # Return all session files on this machine. Use core.utils.paths
        # for cross-platform home/config dirs — never hardcode C:\ or /Users.
        ...

    def parse(self, path: Path) -> Session:
        # Convert the native file into the unified Session model.
        # Use core.normalize.read_jsonl_tolerant() for JSONL files — it
        # handles encoding, dirty lines and schema drift for you.
        ...

    def serialize(self, session: Session) -> bytes:
        # Convert back to native format (for injection).
        # Preserve raw fields from Turn.meta / ContentPart.raw for
        # lossless round-trips.
        ...

    def inject(self, session: Session, target_dir: Path | None = None) -> Path:
        # Write as a NEW session file (new id, new filename).
        # NEVER overwrite the source file.
        ...
```

2. Add fixture files to `tests/fixtures/my_tool/` (include a **dirty/broken sample**!).
3. Add `tests/test_adapter_my_tool.py` — assert the round-trip: `parse → serialize → parse` yields the same turns.
4. Update the support matrix in both READMEs.
5. Open a PR with the `adapter:` prefix.

### Testing

```bash
pytest                      # all tests
pytest tests/test_normalize.py -v
```

Fixtures must be synthetic or anonymized — **never commit real user conversation data**.

---

## 中文

首先感谢你！ctxbox 靠社区适配器成长 —— 你添加的每个 AI 工具都能帮到所有人。

### 基本原则

- **隐私是红线**：ctxbox 绝不把用户数据发往任何地方。加入遥测/联网上传用户内容的 PR 会被拒绝。
- **绝不覆盖原始文件**：所有写操作必须原子化（临时文件 + `os.replace`），且先创建备份。
- **绝不丢数据**：解析失败时降级为 `raw` ContentPart 并记录警告 —— 不抛异常、不静默跳过。

### 开发环境

```bash
git clone https://github.com/a2795751503/ctxbox.git
cd ctxbox
pip install -e ".[dev]"
pytest
```

### 代码风格

- `ruff check src tests` 与 `ruff format` 必须通过（CI 强制）
- `mypy src` 保持干净
- 提交信息遵循 [Conventional Commits](https://www.conventionalcommits.org)：`feat:`、`fix:`、`adapter:`、`docs:` …
- 核心层（`src/ctxbox/core/`）禁止 import PySide6 —— 保持 core 与 GUI 解耦

### 添加新适配器

支持一个新的 AI 工具是最有价值的贡献，大约 100 行代码。步骤见上方英文版（代码注释为中文开发者同样友好），核心要点：

1. 在 `src/ctxbox/core/adapters/` 新建适配器文件，继承 `BaseAdapter`，用 `@register` 注册
2. 实现 `detect / parse / serialize / inject` 四个方法，路径用 `core.utils.paths` 跨平台抽象
3. JSONL 文件统一走 `core.normalize.read_jsonl_tolerant()`（编码、脏行、版本漂移都帮你处理了）
4. 在 `tests/fixtures/` 放样本（**必须包含脏/损坏样本**），写 round-trip 测试
5. 更新双语 README 的支持矩阵，用 `adapter:` 前缀提 PR

### 测试

fixture 必须是合成或匿名化数据 —— **绝不要提交真实用户对话数据**。
