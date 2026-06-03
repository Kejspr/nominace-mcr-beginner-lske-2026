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


def is_regional_qualifier(position: str) -> bool:
    rank = parse_position_rank(position)
    return rank is not None and rank <= QUALIFYING_PLACES


def is_ano_value(value: str) -> bool:
    return value.startswith("ANO")


def _sort_rank(position: str) -> int:
    return parse_position_rank(position) or 9999


def _overflow_boundary_remiza(
    rank: int,
    group_size: int,
    assigned_count: int,
    position: str,
    tied: frozenset[str],
) -> bool:
    """Remiza jen kdyz by neodmitnuti na hrane postupu prekrocili limit."""
    if rank != QUALIFYING_PLACES or group_size <= 1:
        return False
    if not is_boundary_tie(position, tied):
        return False
    return assigned_count + group_size > QUALIFYING_PLACES


def _kraje_label(remiza: bool) -> str:
    if remiza:
        return "ANO (remiza)"
    return "ANO"


def _postupuje_ano_label(remiza: bool, confirmed: bool) -> str:
    if remiza:
        return "ANO (remiza)"
    if confirmed:
        return "ANO (potvrzeno)"
    return "ANO"


def regional_qualifier_label(position: str, tied: frozenset[str]) -> str:
    if not is_regional_qualifier(position):
        return "NE"
    if is_boundary_tie(position, tied):
        return "ANO (remiza)"
    return "ANO"


def _rank_groups(
    candidates: list[tuple[Hashable, str, bool]],
) -> list[list[tuple[Hashable, str, bool]]]:
    groups: list[list[tuple[Hashable, str, bool]]] = []
    index = 0
    while index < len(candidates):
        rank = _sort_rank(candidates[index][1])
        group: list[tuple[Hashable, str, bool]] = []
        while index < len(candidates) and _sort_rank(candidates[index][1]) == rank:
            group.append(candidates[index])
            index += 1
        groups.append(group)
    return groups


@dataclass(frozen=True)
class CategorySlotResult:
    postupuje: dict[Hashable, str]
    postup_kraje: dict[Hashable, str]
    summary: str


def compute_category_slots(
    rows: list[tuple[Hashable, str, bool, bool]],
) -> CategorySlotResult:
    """
    Postupuje + postup z Kraje pro jednu kategorii.

    rows: (klic, pozice, declined, confirmed_v_nominations)
    """
    positions = [position for _, position, _, _ in rows]
    tied = tied_position_labels(positions)
    postupuje: dict[Hashable, str] = {}
    postup_kraje: dict[Hashable, str] = {}

    candidates: list[tuple[Hashable, str, bool]] = []
    for key, position, declined, _confirmed in sorted(rows, key=lambda row: _sort_rank(row[1])):
        if declined:
            postupuje[key] = "NE (odmítnuto)"
            postup_kraje[key] = _kraje_label(False) if is_regional_qualifier(position) else "NE"
        else:
            candidates.append((key, position, _confirmed))

    assigned_keys: set[Hashable] = set()
    assigned_count = 0
    overflow_remiza_ranks: list[int] = []

    for group in _rank_groups(candidates):
        rank = parse_position_rank(group[0][1]) or 9999
        group_size = len(group)
        need = QUALIFYING_PLACES - assigned_count
        remiza = _overflow_boundary_remiza(
            rank, group_size, assigned_count, group[0][1], tied
        )
        if remiza:
            overflow_remiza_ranks.append(rank)

        if rank <= QUALIFYING_PLACES:
            if assigned_count >= QUALIFYING_PLACES and not remiza:
                for key, position, _confirmed in group:
                    postup_kraje.setdefault(
                        key,
                        _kraje_label(False) if is_regional_qualifier(position) else "NE",
                    )
                continue
            for key, position, confirmed in group:
                postupuje[key] = _postupuje_ano_label(remiza, confirmed)
                postup_kraje[key] = _kraje_label(remiza)
                assigned_keys.add(key)
            assigned_count += group_size
            continue

        if need <= 0:
            continue

        for key, position, confirmed in group[:need]:
            postupuje[key] = "ANO (potvrzeno)" if confirmed else "ANO"
            postup_kraje[key] = "NE"
            assigned_keys.add(key)
        assigned_count += min(need, group_size)

    for group in _rank_groups(candidates):
        for key, position, confirmed in group:
            if key in assigned_keys:
                continue
            postupuje[key] = "NE (zájem o postup)" if confirmed else "NE"
            postup_kraje.setdefault(
                key,
                _kraje_label(False) if is_regional_qualifier(position) else "NE",
            )

    summary = _build_qualification_summary(assigned_count, overflow_remiza_ranks)
    return CategorySlotResult(
        postupuje=postupuje,
        postup_kraje=postup_kraje,
        summary=summary,
    )


def compute_category_postupuje(
    rows: list[tuple[Hashable, str, bool, bool]],
) -> dict[Hashable, str]:
    return compute_category_slots(rows).postupuje


def _format_rank_places(ranks: list[int]) -> str:
    labels = [f"{rank}." for rank in ranks]
    if len(labels) == 1:
        return f"{labels[0]} místě"
    if len(labels) == 2:
        return f"{labels[0]} a {labels[1]} místě"
    return ", ".join(labels[:-1]) + f" a {labels[-1]} místě"


def _build_qualification_summary(
    assigned_count: int,
    overflow_remiza_ranks: list[int],
) -> str:
    if assigned_count <= QUALIFYING_PLACES and not overflow_remiza_ranks:
        return ""

    parts: list[str] = []
    if assigned_count > QUALIFYING_PLACES:
        parts.append(
            f"Postupuje {assigned_count} závodníků (limit {QUALIFYING_PLACES}"
        )
    if overflow_remiza_ranks:
        remiza_text = _format_rank_places(sorted(set(overflow_remiza_ranks)))
        if parts:
            parts[0] += f", remízy na {remiza_text})"
        else:
            parts.append(f"Remízy na {remiza_text}")
    elif parts:
        parts[0] += ")"
    return parts[0] if parts else ""


@dataclass(frozen=True)
class CategoryQualificationInfo:
    qualifier_count: int
    tied_among_qualifiers: tuple[int, ...]
    summary: str


def analyze_category_qualification_rows(
    rows: list[tuple[Hashable, str, bool, bool]],
) -> CategoryQualificationInfo:
    slots = compute_category_slots(rows)
    active_regional = sum(
        1
        for _key, position, declined, _confirmed in rows
        if is_regional_qualifier(position) and not declined
    )
    return CategoryQualificationInfo(
        qualifier_count=active_regional,
        tied_among_qualifiers=tuple(sorted(set(
            rank
            for rank in (
                parse_position_rank(position) or 0
                for _key, position, _declined, _confirmed in rows
            )
            if rank == QUALIFYING_PLACES
        ))),
        summary=slots.summary,
    )


def analyze_category_qualification(positions: list[str]) -> CategoryQualificationInfo:
    """Zpetna kompatibilita bez informace o odmitnuti."""
    rows = [
        (index, position, False, False)
        for index, position in enumerate(positions)
    ]
    return analyze_category_qualification_rows(rows)


def boundary_tied_ranks(positions: list[str]) -> tuple[int, ...]:
    tied = tied_position_labels(positions)
    return tuple(sorted({
        rank
        for position in tied
        if (rank := parse_position_rank(position)) is not None
        and rank == QUALIFYING_PLACES
        and is_regional_qualifier(position)
    }))
