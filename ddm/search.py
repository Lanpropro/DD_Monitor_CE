"""关注搜索共用的中文、全拼与首字母匹配。"""
from functools import lru_cache
from itertools import groupby

from pypinyin import Style, lazy_pinyin


@lru_cache(maxsize=8192)
def _pinyin_keys(text: str) -> tuple[str, ...]:
    if not any('\u3400' <= char <= '\u9fff' for char in text):
        return '', ''
    full, initials = (''.join(''.join(lazy_pinyin(text, style=style)).split())
                      for style in (Style.NORMAL, Style.FIRST_LETTER))
    abbreviated = ''.join(char if char.isalpha() else ''.join(run)
                          for char, run in groupby(initials))
    return full, initials, abbreviated


def matches_text(text: str, query: str) -> bool:
    text, query = text.casefold(), query.casefold()
    if query in text:
        return True
    compact = ''.join(query.split())
    return bool(compact) and any(compact in key for key in _pinyin_keys(text))
