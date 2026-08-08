from __future__ import annotations

from anima_prompt_studio.domain.models import SemanticWarning, WarningLevel
import re


CONCEPTS = {
    "左右": (("左", "left"), ("右", "right")),
    "上下": (("上方", "向上", "above", "upward"), ("下方", "向下", "below", "downward")),
    "人数": (("一个", "一人", "one", "a girl", "a boy", "a person", "1girl", "1boy"), ("两个", "两人", "two", "2girls", "2boys", "2people"), ("三个", "三人", "three", "3girls", "3boys", "3people")),
    "姿态": (("坐", "sitting", "sit"), ("站", "standing", "stand"), ("躺", "lying", "lie")),
    "环境": (("室内", "indoors"), ("室外", "outdoors")),
    "时间": (("白天", "daytime"), ("夜", "night")),
    "性别": (("女", "girl", "woman", "female"), ("男", "boy", "man", "male")),
    "发色": (("白发", "white hair", "white-haired"), ("黑发", "black hair", "black-haired"), ("金发", "blonde")),
    "瞳色": (("金瞳", "golden eyes", "gold eyes"), ("蓝瞳", "blue eyes"), ("红瞳", "red eyes")),
}


class SemanticDiffService:
    @staticmethod
    def _source_affirmed(chinese: str, token: str) -> bool:
        start = chinese.find(token)
        while start >= 0:
            prefix = chinese[max(0, start - 8):start]
            if not re.search(r"(?:不在|不是|没有|没|无|改掉|不要)[^，。；！？]{0,5}$", prefix):
                override_positions = [chinese.rfind(marker) for marker in ("改成", "改为", "改穿", "后来", "这次")]
                if start >= max(override_positions, default=-1):
                    return True
            start = chinese.find(token, start + 1)
        return False

    def compare(self, chinese: str, english: str, back_chinese: str) -> list[SemanticWarning]:
        warnings: list[SemanticWarning] = []
        combined_target = (english + " " + back_chinese).lower()
        if re.search(r"(?:不|没有|没|未|无|并非|不是)", chinese):
            semantic_negative_preserved = (
                ("脚不着地" in chinese and "feet off the ground" in combined_target)
                or ("没有穿鞋" in chinese and "barefoot" in combined_target)
            )
            if not semantic_negative_preserved and not re.search(r"(?:不|没有|没|未|无|并非|不是|without|\bnot\b|n't\b|\bno\b|never)", combined_target):
                warnings.append(SemanticWarning(level=WarningLevel.RED, concept="否定", message="原文包含否定，但翻译或回译可能丢失否定关系。"))
        for concept, groups in CONCEPTS.items():
            for group in groups:
                source_present = any(self._source_affirmed(chinese, token) for token in group if not token.isascii())
                target_present = any(token.lower() in combined_target for token in group)
                if source_present and not target_present:
                    warnings.append(SemanticWarning(level=WarningLevel.RED, concept=concept, message=f"关键概念可能丢失：{group[0]}"))
        if not warnings:
            warnings.append(SemanticWarning(level=WarningLevel.GREEN, concept="基础检查", message="未发现预设关键概念冲突（不代表翻译绝对正确）。"))
        return warnings
