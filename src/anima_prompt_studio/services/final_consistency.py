from __future__ import annotations

import re

from anima_prompt_studio.domain.models import PromptJob, SubjectMode


class FinalConsistencyService:
    """Deterministic final-output checks; reports problems without rewriting user text."""

    @staticmethod
    def _affirmed_in_prose(prose: str, concept: str) -> bool:
        for match in re.finditer(rf"\b{re.escape(concept.casefold())}s?\b", prose.casefold()):
            prefix = prose.casefold()[max(0, match.start() - 55):match.start()]
            if re.search(r"(?:\bwithout\b|\bno\b|\bnot\b|n't\b|\bnever\b)[^.!?;,]{0,40}$", prefix):
                continue
            return True
        return False

    def validate(self, job: PromptJob) -> tuple[list[str], list[str]]:
        tag_section, _, prose = job.positive_prompt.partition("\n\n")
        tags = {x.strip().casefold() for x in tag_section.split(",") if x.strip()}
        lower = prose.casefold()
        consistency: list[str] = []
        cleanliness: list[str] = []

        if job.effective_subject_mode() == SubjectMode.SCENE:
            forbidden = tags & {"1girl", "1boy", "solo", "looking at viewer", "upper body", "portrait", "bust", "centered"}
            if forbidden:
                consistency.append("纯场景包含人物标签：" + ", ".join(sorted(forbidden)))

        if job.semantic_frame.gaze_intent == "away" and "looking at viewer" in tags:
            consistency.append("看向远方/画外的语义与 looking at viewer 冲突")
        if job.semantic_frame.gaze_intent == "viewer" and "looking away" in tags:
            consistency.append("看镜头语义与 looking away 冲突")
        if any(x in lower for x in ("looks into the distance", "looks outside", "looks out the window")) and "looking at viewer" in tags:
            consistency.append("自然语言视线离开镜头，但标签仍看向 viewer")

        for item in job.semantic_frame.excluded_concepts:
            if item.canonical_tag.casefold() in tags:
                consistency.append(f"已排除概念仍出现在正向标签：{item.canonical_tag}")
            if self._affirmed_in_prose(prose, item.canonical_tag):
                consistency.append(f"已排除概念仍出现在正向正文：{item.canonical_tag}")

        for mention in job.semantic_frame.unresolved_lora_mentions:
            consistency.append(f"文本提到的 LoRA 未匹配本地配置：{mention}")

        authority = job.authoritative_text()
        camera_is_gaze = (
            any(x in authority for x in ("看镜头", "看向镜头"))
            if not job.uses_english_authority()
            else bool(re.search(r"\b(?:looks?|looking)\s+(?:at|toward|towards)\s+(?:the )?camera\b", authority, re.I))
        )
        if "camera" in tags and camera_is_gaze:
            consistency.append("视线目标‘镜头’被错误编译成 camera 对象标签")

        grammar_patterns = (
            (r"\ba (?:girl|boy|woman|man) aren't\b", "单数主语错误使用 aren't"),
            (r"\bshort\s+[a-z]+-haired\b", "short 与 -haired 词性搭配错误"),
            (r"\blong\s+[a-z]+-haired\b", "long 与 -haired 词性搭配错误"),
            (r"\b(?:the|a) girl\b[^.]{0,45}\bthey(?:'re| are| have)\b", "单人人物与复数代词冲突"),
            (r"\bin the moon\b", "月光被错误表达为 in the moon"),
            (r"\b(?:this time|originally|used to)\b", "最终描述仍包含属性修改历史"),
            (r"\bwas\s+[^.]{0,45}\bbut\b", "最终描述仍保留 was...but... 历史结构"),
            (r"\b(?:a|one|1)\s*girl\b[^.]*\bgirls\b|\b1girl\b[^.]*\bgirls\b", "单人人数与复数 girls 冲突"),
        )
        for pattern, message in grammar_patterns:
            if re.search(pattern, lower, flags=re.I):
                cleanliness.append(message)
        if job.composition.people_count == 1 and re.search(r"\bgirls\b", lower):
            cleanliness.append("单人人数与复数 girls 冲突")
        if re.search(r"(?:^|\.\s+)(?:the girl|the character|a girl)\s*\.(?:\s|$)", lower):
            cleanliness.append("存在无信息独立残句")

        job.consistency_failures = list(dict.fromkeys(consistency))
        job.cleanliness_failures = list(dict.fromkeys(cleanliness))
        return job.consistency_failures, job.cleanliness_failures
