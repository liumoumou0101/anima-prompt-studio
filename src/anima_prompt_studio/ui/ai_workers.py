from __future__ import annotations

from PySide6.QtCore import QObject, Signal, Slot

from anima_prompt_studio.services.ai_extract_service import AIExtractService, ExtractedPrompt
from anima_prompt_studio.services.ai_prompt_service import AIClient


class AIExtractWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    done = Signal()

    def __init__(self, *, service: AIExtractService, client: AIClient, source_text: str) -> None:
        super().__init__()
        self.service = service
        self.client = client
        self.source_text = source_text

    @Slot()
    def run(self) -> None:
        try:
            result: ExtractedPrompt = self.service.extract(self.source_text, self.client)
            self.succeeded.emit(result)
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.done.emit()


class AIModelListWorker(QObject):
    succeeded = Signal(object)
    failed = Signal(str)
    done = Signal()

    def __init__(self, *, client: AIClient) -> None:
        super().__init__()
        self.client = client

    @Slot()
    def run(self) -> None:
        try:
            self.succeeded.emit(self.client.list_models())
        except Exception as exc:
            self.failed.emit(str(exc))
        finally:
            self.done.emit()
