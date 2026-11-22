"""Recognize standalone instructions to preserve an exact prompt field."""
import re


def exact_prompt_fields(delta: str, reviewed: dict | None) -> dict[str, str]:
    if not reviewed:
        return {}
    fields = {}
    for clause in re.split(r"[。.!！;；,，\n]", delta.casefold()):
        clause = clause.strip()
        for field, chinese in (("positive", "正[向面]"), ("negative", "负[向面]")):
            label = rf"{chinese}(?:提示词|正文|文本|原文)?"
            exact = r"(?:连同(?:空白|空格|换行|格式))?(?:(?:请|务必|必须|完全|逐字|原样|保持|原文))*"
            if (re.fullmatch(rf"(?:请)?{label}{exact}(?:不变|不动|原样|不要改动|不要改|保持原样)", clause)
                    or re.fullmatch(rf"(?:请)?保持{label}(?:逐字)?(?:不变|原样)", clause)
                    or re.fullmatch(rf"(?:please )?(?:keep|leave) (?:the )?{field}(?: prompt)? "
                                    r"(?:unchanged|exactly as (?:written|it is)|verbatim)", clause)):
                fields[field] = reviewed[field]
    return fields
