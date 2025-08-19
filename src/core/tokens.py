"""
Naive token estimation utilities for conversation context size.

Authors:
    - Benjamin Dourthe (benjamin@adonamed.com)
"""
import math
import re
from typing import Dict, List

_TOKEN_PATTERN = re.compile(r"\w+|[^\w\s]", re.UNICODE)


def estimate_tokens(text: str) -> int:
    """Return a rough token estimate for a given text using a regex-based heuristic."""
    if not text:
        return 0
    s = text.strip()
    if not s:
        return 0
    units = _TOKEN_PATTERN.findall(s)
    by_regex = len(units)
    by_chars = math.ceil(len(s) / 4)
    return max(by_regex, by_chars)


def estimate_messages_tokens(messages: List[Dict]) -> int:
    """Return approximate total tokens for a list of chat messages.

    Parameters:
        - messages (list[dict]): [{'role': str, 'content': str, 'ts': str}, ...]

    Returns:
        - int: approximate token count

    Authors:
        - Benjamin Dourthe (benjamin@adonamed.com)
    """
    if not messages:
        return 0
    total = 0
    overhead = 4
    for m in messages:
        try:
            total += estimate_tokens(str(m.get('content', '') or '')) + overhead
        except Exception:
            total += overhead
    return int(total)
