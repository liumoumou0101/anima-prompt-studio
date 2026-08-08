from __future__ import annotations

import re
import unicodedata


class InputPreprocessor:
    _controls = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")

    def normalize(self, text: str) -> str:
        text = unicodedata.normalize("NFKC", text)
        text = self._controls.sub("", text)
        text = text.replace("，", ", ").replace("。", ".\n").replace("；", "; ")
        text = text.replace("：", ": ").replace("！", "!").replace("？", "?")
        lines = [re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines()]
        return "\n".join(line for line in lines if line).strip()

