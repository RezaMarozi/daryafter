"""Tiny translation layer. English is the source text; other languages are
JSON files in daryafter/locales/<code>.json mapping English text -> translation."""
from __future__ import annotations

import json

from .paths import locales_dir

_table: dict[str, str] = {}
_lang = "en"


def set_language(code: str) -> None:
    global _table, _lang
    _lang = code or "en"
    _table = {}
    if _lang == "en":
        return
    path = locales_dir() / f"{_lang}.json"
    try:
        _table = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _table = {}


def language() -> str:
    return _lang


def tr(text: str) -> str:
    return _table.get(text, text)
