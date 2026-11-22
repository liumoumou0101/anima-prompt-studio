"""Exact seed input and browser-safe display; sampling still uses Python integers."""
import re
from typing import Annotated

from pydantic import BeforeValidator, Field, PlainSerializer


def display_seed(value: int) -> int | str:
    return str(value) if abs(value) > 2**53 - 1 else value


def validate_seed(value):
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError("Seed 必须是整数；大整数请使用十进制文本。")
    if isinstance(value, str) and not re.fullmatch(r"-?\d{1,19}", value, flags=re.ASCII):
        raise ValueError("Seed 必须是 -1 或非负十进制整数。")
    return value


Seed = Annotated[int, Field(ge=-1, le=2**63 - 1), BeforeValidator(validate_seed),
                 PlainSerializer(display_seed, return_type=int | str)]
