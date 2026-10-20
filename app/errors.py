from dataclasses import dataclass


@dataclass
class ApiError(Exception):
    status: int
    code: str
    message: str


class CacheUnavailable(Exception):
    pass
