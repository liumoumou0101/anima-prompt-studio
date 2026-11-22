"""Local Chinese-leakage check for Anima's generated English prompts."""
import re


# Include traditional/compatibility forms and supplementary Han ideographs.
# Do not use an ASCII-only check: Latin names can legitimately have accents.
_HAN = re.compile(r"[\u3007\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff"
                  r"\U00020000-\U0002ffff\U00030000-\U0003ffff]")


def contains_chinese(text: str) -> bool:
    return _HAN.search(text) is not None
