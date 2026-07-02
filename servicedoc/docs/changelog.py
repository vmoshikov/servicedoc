from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Literal

from servicedoc.models.docs import ChangelogEntry

_PUNCT = re.compile(r"[^\w\s]")


def _normalize(text: str) -> list[str]:
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    text = _PUNCT.sub("", text)
    return text.split()


def _union_find_clusters(n: int, pairs: list[tuple[int, int]]) -> list[int]:
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    for a, b in pairs:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb
    return [find(i) for i in range(n)]


def _char_normalize(text: str) -> str:
    text = text.lower()
    text = unicodedata.normalize("NFD", text)
    return _PUNCT.sub("", text).strip()


def deduplicate(entries: list[ChangelogEntry], threshold: float = 0.75) -> list[ChangelogEntry]:
    if len(entries) <= 1:
        return entries

    # character-level comparison works better for morphologically-rich languages
    normalized = [_char_normalize(e.message) for e in entries]
    similar_pairs: list[tuple[int, int]] = []

    for i in range(len(entries)):
        for j in range(i + 1, len(entries)):
            ratio = difflib.SequenceMatcher(None, normalized[i], normalized[j]).ratio()
            if ratio >= threshold:
                similar_pairs.append((i, j))

    clusters = _union_find_clusters(len(entries), similar_pairs)
    # group by cluster root
    cluster_map: dict[int, list[int]] = {}
    for idx, root in enumerate(clusters):
        cluster_map.setdefault(root, []).append(idx)

    result: list[ChangelogEntry] = []
    for members in cluster_map.values():
        # pick longest message as representative
        rep = max(members, key=lambda i: len(entries[i].message))
        entry = entries[rep].model_copy(update={"cluster_representative": True})
        result.append(entry)

    return result


KIND_ORDER: dict[str, int] = {
    "other": 0,  # will be filtered as BREAKING if breaking=True
    "feat": 1,
    "fix": 2,
    "refactor": 3,
    "docs": 4,
    "test": 5,
    "chore": 6,
    "ci": 7,
}


def group_entries(
    entries: list[ChangelogEntry],
) -> dict[str, list[ChangelogEntry]]:
    groups: dict[str, list[ChangelogEntry]] = {
        "breaking": [],
        "feat": [],
        "fix": [],
        "refactor": [],
        "docs": [],
        "test": [],
        "chore": [],
        "other": [],
    }
    for entry in entries:
        if entry.breaking:
            groups["breaking"].append(entry)
        else:
            groups.setdefault(entry.kind, groups["other"]).append(entry)
    return {k: v for k, v in groups.items() if v}
