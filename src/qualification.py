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


def _rank_groups(
    candidates: list[tuple[Hashable, str, bool]],
) -> list[list[tuple[Hashable, str, bool]]]:
    def sort_rank(position: str) -> int:
        return parse_position_rank(position) or 9999

    groups: list[list[tuple[Hashable, str, bool]]] = []
    index = 0
    while index < len(candidates):
        rank = sort_rank(candidates[index][1])
        group: list[tuple[Hashable, str, bool]] = []
        while index < len(candidates) and sort_rank(candidates[index][1]) == rank:
            group.append(candidates[index])
            index += 1
        groups.append(group)
    return groups


def compute_category_postupuje(
    rows: list[tuple[Hashable, str, bool, bool]],
) -> dict[Hashable, str]:
    """
    Postupuje pro jednu kategorii.

    Vzdy doplni QUALIFYING_PLACES postupujicich podle poradi (odmitnuti vypadaji).
    Remiza na hrane postupu muze pocet mirne prekrocit.
    confirmed (nominations/) meni jen popisek ANO a informaci NE (zajem o postup).

    rows: (klic, pozice, declined, confirmed_v_nominations)
    """
    positions = [position for _, position, _, _ in rows]
    tied = tied_position_labels(positions)
    labels: dict[Hashable, str] = {}

    def sort_rank(position: str) -> int:
        return parse_position_rank(position) or 9999

    candidates: list[tuple[Hashable, str, bool]] = []
    for key, position, declined, confirmed in sorted(rows, key=lambda row: sort_rank(row[1])):
        if declined:
            labels[key] = "NE (odmítnuto)"
        else:
            candidates.append((key, position, confirmed))

    assigned_keys: set[Hashable] = set()
    assigned_count = 0

    for group in _rank_groups(candidates):
        rank = parse_position_rank(group[0][1]) or 9999
        group_size = len(group)
        boundary_tie = (
            rank == QUALIFYING_PLACES
            and group_size > 1
            and is_boundary_tie(group[0][1], tied)
        )
        need = QUALIFYING_PLACES - assigned_count

        if rank <= QUALIFYING_PLACES:
            if assigned_count >= QUALIFYING_PLACES and not boundary_tie:
                continue
            for key, position, confirmed in group:
                labels[key] = _postupuje_ano_label(
                    position,
                    tied,
                    group_size,
                    confirmed,
                )
                assigned_keys.add(key)
            assigned_count += group_size
            continue

        if need <= 0:
            continue

        for key, position, confirmed in group[:need]:
            labels[key] = "ANO (potvrzeno)" if confirmed else "ANO"
            assigned_keys.add(key)
        assigned_count += min(need, group_size)

    for group in _rank_groups(candidates):
        for key, _position, confirmed in group:
            if key in assigned_keys:
                continue
            labels[key] = "NE (zájem o postup)" if confirmed else "NE"

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
        tied_among_qualifiers=tied_ranks,
        summary=summary,
    )
