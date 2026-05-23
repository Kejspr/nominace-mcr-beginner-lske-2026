#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Logika postupu z Kraje, remiz a souhrnu kategorie."""

from collections import Counter
from dataclasses import dataclass
from typing import Hashable, Optional

from config import QUALIFYING_PLACES


def parse_position_rank(position: str) -> Optional[int]:
    try:
        return int(position.replace(".", "").strip())
    except ValueError:
        return None


def tied_position_labels(positions: list[str]) -> frozenset[str]:
    counts = Counter(position for position in positions if position)
    return frozenset(label for label, count in counts.items() if count > 1)


def is_boundary_tie(position: str, tied: frozenset[str]) -> bool:
    if position not in tied:
        return False
    rank = parse_position_rank(position)
    return rank is not None and rank == QUALIFYING_PLACES


def boundary_tied_ranks(positions: list[str]) -> tuple[int, ...]:
    tied = tied_position_labels(positions)
    return tuple(sorted({
        rank
        for position in tied
        if (rank := parse_position_rank(position)) is not None
        and rank == QUALIFYING_PLACES
        and is_regional_qualifier(position)
    }))


def is_regional_qualifier(position: str) -> bool:
    rank = parse_position_rank(position)
    return rank is not None and rank <= QUALIFYING_PLACES


def is_ano_value(value: str) -> bool:
    return value.startswith("ANO")


def _kraje_ano_label(position: str, tied: frozenset[str]) -> str:
    if is_boundary_tie(position, tied):
        return "ANO (remiza)"
    return "ANO"


def regional_qualifier_label(position: str, tied: frozenset[str]) -> str:
    if not is_regional_qualifier(position):
        return "NE"
    return _kraje_ano_label(position, tied)


def _postupuje_ano_label(
    position: str,
    tied: frozenset[str],
    active_at_same_rank: int,
    confirmed: bool,
) -> str:
    if is_boundary_tie(position, tied) and active_at_same_rank > 1:
        return "ANO (remiza)"
    if confirmed:
        return "ANO (potvrzeno)"
    return "ANO"


def compute_category_postupuje(
    rows: list[tuple[Hashable, str, bool, bool]],
) -> dict[Hashable, str]:
    """
    Postupuje pro jednu kategorii.

    rows: (klic, pozice, declined, confirmed_v_nominations)
    """
    positions = [position for _, position, _, _ in rows]
    tied = tied_position_labels(positions)
    labels: dict[Hashable, str] = {}
    waitlist: list[tuple[int, Hashable, str]] = []

    def sort_rank(position: str) -> int:
        return parse_position_rank(position) or 9999

    active_kraje_count = sum(
        1
        for _, position, declined, _ in rows
        if is_regional_qualifier(position) and not declined
    )
    open_slots = max(0, QUALIFYING_PLACES - active_kraje_count)

    active_at_position = Counter(
        position
        for _, position, declined, _ in rows
        if not declined and is_regional_qualifier(position)
    )

    for key, position, declined, confirmed in sorted(rows, key=lambda row: sort_rank(row[1])):
        if declined:
            labels[key] = "NE (odmítnuto)"
            continue

        if is_regional_qualifier(position):
            labels[key] = _postupuje_ano_label(
                position,
                tied,
                active_at_position[position],
                confirmed,
            )
            continue

        if confirmed:
            waitlist.append((sort_rank(position), key, position))
        else:
            labels[key] = "NE"

    for _, key, _position in sorted(waitlist, key=lambda item: item[0]):
        if open_slots > 0:
            labels[key] = "ANO"
            open_slots -= 1
        else:
            labels[key] = "NE (zájem o postup)"

    return labels


def _format_rank_places(ranks: list[int]) -> str:
    labels = [f"{rank}." for rank in ranks]
    if len(labels) == 1:
        return f"{labels[0]} místě"
    if len(labels) == 2:
        return f"{labels[0]} a {labels[1]} místě"
    return ", ".join(labels[:-1]) + f" a {labels[-1]} místě"


@dataclass(frozen=True)
class CategoryQualificationInfo:
    qualifier_count: int
    tied_among_qualifiers: tuple[int, ...]
    summary: str


def analyze_category_qualification(positions: list[str]) -> CategoryQualificationInfo:
    qualifier_count = sum(1 for position in positions if is_regional_qualifier(position))
    tied_ranks = boundary_tied_ranks(positions)

    summary = ""
    if qualifier_count > QUALIFYING_PLACES or tied_ranks:
        parts: list[str] = []
        if qualifier_count > QUALIFYING_PLACES:
            parts.append(
                f"Postupuje {qualifier_count} závodníků (limit {QUALIFYING_PLACES}"
            )
        if tied_ranks:
            remiza_text = _format_rank_places(tied_ranks)
            if parts:
                parts[0] += f", remízy na {remiza_text})"
            else:
                parts.append(f"Remízy na {remiza_text}")
        elif parts:
            parts[0] += ")"
        summary = parts[0] if parts else ""

    return CategoryQualificationInfo(
        qualifier_count=qualifier_count,
        tied_among_qualifiers=tuple(tied_ranks),
        summary=summary,
    )
