"""A direct submission's pre-acceptance budget; unrelated clients keep their defaults."""
from contextvars import ContextVar
import time

from ..core.requirements import WorkbenchError


class DirectPreparationTimeout(WorkbenchError):
    def __init__(self):
        super().__init__("direct_preparation_timeout", "连接或准备超时，请检查连接或更换链接后重试。")


_budget = ContextVar("direct_preparation_budget", default=None)


class DirectPreparationBudget:
    def __init__(self, seconds=8.0):
        self.deadline = time.monotonic() + seconds

    def check(self):
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise DirectPreparationTimeout()
        return remaining

    def __enter__(self):
        self._token = _budget.set(self)
        return self

    def __exit__(self, *_args):
        _budget.reset(self._token)


def current_preparation_budget():
    return _budget.get()


def preparation_request_timeout(timeout):
    budget = current_preparation_budget()
    if budget is None:
        return timeout
    # A healthy gateway may need several seconds to answer. Limit connection
    # establishment separately and give the read the rest of this shared budget.
    remaining = budget.check()
    connect = min(timeout[0], 2.0, remaining / 3)
    read = min(timeout[1], remaining - connect)
    return connect, read
