#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Helpers for hiding security names in screenshot-oriented example GUIs.

The privacy mode is deliberately a display concern: callers keep the original
values for sorting, selection and requests, and only pass visible values
through :func:`mask_chinese_name`.
"""

from __future__ import annotations

import re
from typing import Any


_HAN_RUN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]+")

# Keep this list focused on identity fields.  Generic Chinese copy such as
# button labels, statuses and news titles must remain readable in privacy mode.
_NAME_FIELDS = frozenset(
    {
        "name",
        "stockname",
        "stock_name",
        "prodname",
        "prod_name",
        "zsname",
        "platename",
        "plate_name",
        "sectorname",
        "sector_name",
        "industryname",
        "industry_name",
        "boardname",
        "board_name",
        "companyname",
        "company_name",
        "instrumentname",
        "secuabbr",
        "pk_name",
        "pkname",
        "板块",
        "板块名称",
        "股票名称",
        "代表个股",
        "所属板块",
        "相关板块",
        "领涨股",
        "领跌股",
        "行业",
        "名称",
    }
)


def mask_chinese_name(value: Any) -> str:
    """Replace each Chinese character run except its final character.

    For example, ``贵州茅台`` becomes ``***台``.  Non-Chinese parts (security
    codes, punctuation and suffixes) are retained so the surrounding display
    remains useful.
    """

    text = "" if value is None else str(value)

    def replace(match: re.Match[str]) -> str:
        run = match.group(0)
        return "*" * max(1, len(run) - 1) + run[-1]

    return _HAN_RUN.sub(replace, text)


def is_name_field(key: Any) -> bool:
    """Return whether a response/table field represents an identity name."""

    field = str(key or "").strip()
    leaf = field.rsplit(".", 1)[-1]
    normalized = leaf.lower().replace("-", "_")
    return normalized in _NAME_FIELDS or leaf in _NAME_FIELDS


def display_name(value: Any, privacy_enabled: bool) -> str:
    """Render a name according to the current privacy toggle."""

    text = "" if value is None else str(value)
    return mask_chinese_name(text) if privacy_enabled else text
