from __future__ import annotations

import re

from anima_prompt_studio.domain.models import CompositionContext, PromptJob


class CompositionContextExtractor:
    """Separates movement, gaze, placement and relational uses of direction words."""

    _movement = {
        "right": re.compile(r"(?:向|朝|往)(?:画面|图中|镜头中)?(?:的)?右(?:侧|边|方)?[^，。；！？]{0,12}(?:奔跑|跑|移动|冲|飞|前进)"),
        "left": re.compile(r"(?:向|朝|往)(?:画面|图中|镜头中)?(?:的)?左(?:侧|边|方)?[^，。；！？]{0,12}(?:奔跑|跑|移动|冲|飞|前进)"),
        "up": re.compile(r"(?:向|朝)(?:画面)?(?:的)?上(?:方)?[^，。]{0,10}(?:飞|跃|移动|上升)"),
        "down": re.compile(r"(?:向|朝)(?:画面)?(?:的)?下(?:方)?[^，。]{0,10}(?:降落|移动|下降)"),
    }
    _gaze = {
        "right": re.compile(r"(?:向|朝)(?:画面)?(?:的)?右(?:侧|边|方)?(?:看|望)|(?:视线|目光)[^，。]{0,8}右"),
        "left": re.compile(r"(?:向|朝)(?:画面)?(?:的)?左(?:侧|边|方)?(?:看|望)|(?:视线|目光)[^，。]{0,8}左"),
        "down": re.compile(r"(?:低头|向下看|看向下方)"),
        "up": re.compile(r"(?:抬头|向上看|仰望)"),
        "viewer": re.compile(r"(?:看镜头|看向镜头)"),
        "object": re.compile(r"(?:看书|看向手中|看着手中|看蘑菇|寻找[^，。]{0,8}蘑菇)"),
    }
    _subject = {
        "right": re.compile(r"(?:站|坐|位于|处于|停留|放置|安排|主体|人物)[^，。]{0,8}(?:在)?(?:画面|图中|镜头中)(?:的)?右(?:侧|边)|(?:在|位于)(?:画面|图中|镜头中)(?:的)?右(?:侧|边)|(?:画面|图中|镜头中)(?:的)?右(?:侧|边)[^，。]{0,6}(?:站|坐|有)"),
        "left": re.compile(r"(?:站|坐|位于|处于|停留|放置|安排|主体|人物)[^，。]{0,8}(?:在)?(?:画面|图中|镜头中)(?:的)?左(?:侧|边)|(?:在|位于)(?:画面|图中|镜头中)(?:的)?左(?:侧|边)|(?:画面|图中|镜头中)(?:的)?左(?:侧|边)[^，。]{0,6}(?:站|坐|有)"),
        "center": re.compile(r"(?:站|坐|位于|处于|主体|人物)[^，。]{0,8}(?:画面|图中|镜头中)(?:的)?(?:中央|中心)|居中构图"),
    }
    _meta = re.compile(r"(?:向|朝|在|位于)?(?:画面|图中|镜头中|构图中)(?:的)?(?:左侧|右侧|中央|中心)?")
    _motion_relation = re.compile(r"(?:(?:她|他|人物)的)?(?:长发|头发|围巾|衣摆|披风)[^，。]{0,12}(?:在)?(?:她|他)?身后[^，。]{0,8}(?:飘|飞|扬)")

    def extract(self, job: PromptJob) -> CompositionContext:
        text = job.authoritative_text()
        context = CompositionContext()
        if job.uses_english_authority():
            lower = text.casefold()
            if re.search(r"\b(?:runs?|running|moves?|moving|flies?|flying|rushes?)\s+(?:toward|towards|to)?\s*(?:the )?right\b", lower):
                context.movement_direction = "right"
            elif re.search(r"\b(?:runs?|running|moves?|moving|flies?|flying|rushes?)\s+(?:toward|towards|to)?\s*(?:the )?left\b", lower):
                context.movement_direction = "left"
            if re.search(r"\b(?:looks?|looking|gazes?)\s+(?:toward|towards|to)?\s*(?:the )?right\b", lower):
                context.gaze_direction = "right"
            elif re.search(r"\b(?:looks?|looking|gazes?)\s+(?:toward|towards|to)?\s*(?:the )?left\b", lower):
                context.gaze_direction = "left"
            elif re.search(r"\b(?:looks?|looking)\s+at\s+(?:the )?(?:viewer|camera)\b", lower):
                context.gaze_direction = "viewer"
            if re.search(r"\b(?:subject|girl|boy|character)\s+(?:is |stands? |sits? )?(?:on |at )?(?:the )?right(?: side)?\b", lower):
                context.explicit_subject_position = "right"
            elif re.search(r"\b(?:subject|girl|boy|character)\s+(?:is |stands? |sits? )?(?:on |at )?(?:the )?left(?: side)?\b", lower):
                context.explicit_subject_position = "left"
            elif "centered composition" in lower or re.search(r"\bsubject is centered\b", lower):
                context.explicit_subject_position = "center"
            context.dynamic_action = context.movement_direction != "none" or bool(
                re.search(r"\b(?:running|jumping|leaping|descending|flying|picking|gathering)\b", lower)
            )
            return context
        for direction, pattern in self._movement.items():
            if pattern.search(text):
                context.movement_direction = direction
                break
        for direction, pattern in self._gaze.items():
            if pattern.search(text):
                context.gaze_direction = direction
                break
        for position, pattern in self._subject.items():
            if pattern.search(text):
                context.explicit_subject_position = position
                break
        context.dynamic_action = context.movement_direction != "none" or any(
            token in text for token in (
                "奔跑", "跑动", "跳跃", "跳过", "跃下", "跃起", "纵身跳",
                "降落", "降下", "从天而降", "飞行", "采摘", "采蘑菇",
            )
        )
        context.composition_meta_spans = [match.group(0) for match in self._meta.finditer(text) if match.group(0)]
        context.motion_relation_spans = [match.group(0) for match in self._motion_relation.finditer(text)]
        return context
