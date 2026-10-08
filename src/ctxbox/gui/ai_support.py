"""AI 服务的 GUI 侧支撑: QSettings 存取 + 后台线程调用 AiClient。

AI 服务是 ctxbox 唯一的联网功能: 仅在用户配置后、且只对预览确认的内容发送。
"""

from __future__ import annotations

from PySide6.QtCore import QObject, QSettings, QThread, Signal

from ctxbox.core.ai_client import PROMPT_LABELS, PROMPTS, AiClient, AiConfig, AiError

DEFAULT_BASE_URL = "https://api.openai.com/v1"
DEFAULT_MODEL = "gpt-4o-mini"


def load_ai_config() -> AiConfig:
    st = QSettings("ctxbox", "ctxbox")
    return AiConfig(
        base_url=str(st.value("ai_base_url", DEFAULT_BASE_URL)),
        api_key=str(st.value("ai_key", "")),
        model=str(st.value("ai_model", DEFAULT_MODEL)),
    )


def save_ai_config(base_url: str, api_key: str, model: str) -> None:
    st = QSettings("ctxbox", "ctxbox")
    st.setValue("ai_base_url", base_url.strip() or DEFAULT_BASE_URL)
    st.setValue("ai_key", api_key.strip())
    st.setValue("ai_model", model.strip() or DEFAULT_MODEL)


class AiWorker(QObject):
    """后台线程跑 AiClient (网络请求不能堵 UI)。"""

    done = Signal(str)
    failed = Signal(str)

    def __init__(
        self,
        cfg: AiConfig,
        *,
        mode: str,
        prompt_key: str | None = None,
        content: str | None = None,
    ) -> None:
        super().__init__()
        self.cfg = cfg
        self.mode = mode  # "test" | "complete"
        self.prompt_key = prompt_key
        self.content = content

    def run(self) -> None:
        try:
            client = AiClient(self.cfg)
            if self.mode == "test":
                self.done.emit(client.test_connection())
            else:
                self.done.emit(client.complete(self.prompt_key, self.content or ""))
        except AiError as exc:
            self.failed.emit(str(exc))
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


def start_ai_job(owner: QObject, worker: AiWorker, on_done, on_failed) -> QThread:
    """启动 worker 线程并管理生命周期 (持引用防 GC, 结束自动清理)。"""
    thread = QThread(owner)
    worker.moveToThread(thread)
    thread.started.connect(worker.run)
    worker.done.connect(on_done)
    worker.failed.connect(on_failed)
    worker.done.connect(thread.quit)
    worker.failed.connect(thread.quit)
    jobs = getattr(owner, "_ai_jobs", None)
    if jobs is None:
        jobs = owner._ai_jobs = []

    def _cleanup() -> None:
        if (thread, worker) in jobs:
            jobs.remove((thread, worker))
        worker.deleteLater()
        thread.deleteLater()

    thread.finished.connect(_cleanup)
    jobs.append((thread, worker))
    thread.start()
    return thread


__all__ = [
    "AiConfig",
    "AiError",
    "AiWorker",
    "PROMPTS",
    "PROMPT_LABELS",
    "load_ai_config",
    "save_ai_config",
    "start_ai_job",
]
