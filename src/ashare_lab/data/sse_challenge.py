"""Fail-closed solver for the current SSE static-file cookie challenge."""

import re
from typing import Final

_ARGUMENT_PATTERN: Final = re.compile(rb"var arg1='([0-9A-F]{40})'")
_POSITION_ORDER: Final = (
    15,
    35,
    29,
    24,
    33,
    16,
    1,
    38,
    10,
    9,
    19,
    31,
    40,
    27,
    22,
    23,
    25,
    13,
    6,
    11,
    39,
    18,
    20,
    8,
    14,
    21,
    32,
    26,
    2,
    30,
    7,
    4,
    17,
    5,
    3,
    28,
    34,
    37,
    12,
    36,
)
_MASK: Final = "3000176000856006061501533003690027800375"


def solve_sse_cookie(content: bytes) -> str | None:
    """Return the versioned challenge cookie or refuse unknown HTML."""
    matched = _ARGUMENT_PATTERN.search(content)
    if matched is None:
        return None
    argument = matched.group(1).decode("ascii")
    reordered = "".join(argument[position - 1] for position in _POSITION_ORDER)
    solved = "".join(
        f"{int(reordered[index : index + 2], 16) ^ int(_MASK[index : index + 2], 16):02x}"
        for index in range(0, len(reordered), 2)
    )
    return f"acw_sc__v2={solved}"
