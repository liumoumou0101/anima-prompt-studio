from __future__ import annotations

import re

from anima_prompt_studio.domain.models import PromptJob


class QualityTagGuard:
    """Keeps optional quality packs from contradicting the user's content."""

    SAFETY_TAGS = {"safe", "sensitive", "nsfw", "explicit"}
    NIGHT_STYLE_TAGS = {"night", "neon lights", "cyberpunk atmosphere", "rim lighting"}
    DYNAMIC_TAGS = {"dynamic angle", "motion lines", "speed lines", "dynamic pose", "action shot"}

    _explicit_re = re.compile(
        r"(?:裸体|全裸|露点|乳头|阴茎|阴部|性交|性爱|做爱|后入|男上位|女上位|高潮|"
        r"\bnude\b|\bnaked\b|\bnipples?\b|\bpenis\b|\bvagina\b|\bsex\b|\bexplicit\b|"
        r"\bmissionary\b|\bcowgirl\b|\bdoggy style\b)",
        re.I,
    )
    _sensitive_re = re.compile(
        r"(?:内衣|情趣|比基尼|泳装|乳沟|胸部|透视|薄纱|蕾丝|"
        r"\blingerie\b|\bbikini\b|\bswimsuit\b|\bcleavage\b|\bbreasts?\b|\bsheer\b|\blace\b)",
        re.I,
    )
    _day_re = re.compile(
        r"(?:白天|日间|正午|中午|清晨|早晨|晨光|阳光下|"
        r"\bdaytime\b|\bdaylight\b|\bnoon\b|\bmorning\b|\bsunlit\b)",
        re.I,
    )
    _night_re = re.compile(r"(?:夜晚|夜间|深夜|月光|\bnight\b|\bmoonlight\b)", re.I)
    _still_re = re.compile(
        r"(?:静止不动|保持静止|静态姿势|安静地坐着|一动不动|"
        r"\bstanding still\b|\bsitting still\b|\bmotionless\b|\bstatic pose\b)",
        re.I,
    )
    _motion_re = re.compile(
        r"(?:奔跑|跑动|冲刺|跳跃|飞跃|战斗|挥舞|追逐|"
        r"\brunn?ing\b|\bsprint(?:ing)?\b|\bjump(?:ing)?\b|\bleap(?:ing)?\b|\bfight(?:ing)?\b|\bchasing\b)",
        re.I,
    )
    _breast_re = re.compile(r"(?:乳房|胸部|乳沟|巨乳|贫乳|平胸|\bbreasts?\b|\bcleavage\b|\bchest focus\b)", re.I)
    _navel_re = re.compile(r"(?:肚脐|小腹|腹部|露脐|腰腹|\bnavel\b|\bmidriff\b|\bbelly\b)", re.I)
    _sheer_re = re.compile(r"(?:透明衣|透视装|薄纱|半透明|\bsheer\b|\btransparent (?:fabric|clothes|clothing)\b)", re.I)
    _lace_re = re.compile(r"(?:蕾丝|花边|\blace\b)", re.I)

    @staticmethod
    def _context(job: PromptJob) -> str:
        matched = " ".join(item.tag for item in job.matched_tags if item.state.value != "excluded")
        slots = " ".join(
            " ".join(slot.identity_tags + slot.appearance_tags + slot.clothing_tags + [slot.action_text])
            for slot in job.character_slots[:max(1, job.composition.people_count)]
        )
        return " ".join(filter(None, (job.authoritative_text(), job.canonical_prose, matched, slots)))

    def safety_tag(self, job: PromptJob) -> str:
        context = self._context(job)
        if job.quality_profile_id in {"uncensored_detail", "ultimate_adult"} or self._explicit_re.search(context):
            return "explicit"
        if self._sensitive_re.search(context):
            return "sensitive"
        return "safe"

    def filter(self, job: PromptJob, tags: list[str]) -> list[str]:
        context = self._context(job)
        blocked = set(self.SAFETY_TAGS)

        if self._day_re.search(context) and not self._night_re.search(context):
            blocked.add("night")
            if not re.search(r"(?:霓虹|\bneon\b)", context, re.I):
                blocked.add("neon lights")
            if not re.search(r"(?:赛博朋克|\bcyberpunk\b)", context, re.I):
                blocked.add("cyberpunk atmosphere")
            if not re.search(r"(?:轮廓光|边缘光|\brim light(?:ing)?\b)", context, re.I):
                blocked.add("rim lighting")
        if self._still_re.search(context) and not self._motion_re.search(context):
            blocked.update(self.DYNAMIC_TAGS)
        if not self._breast_re.search(context):
            blocked.add("detailed breasts")
        if not self._navel_re.search(context):
            blocked.add("detailed navel")
        if not self._sheer_re.search(context):
            blocked.add("sheer fabric")
        if not self._lace_re.search(context):
            blocked.add("lace details")

        result = [tag for tag in tags if tag.casefold() not in blocked]
        result.append(self.safety_tag(job))
        return result
