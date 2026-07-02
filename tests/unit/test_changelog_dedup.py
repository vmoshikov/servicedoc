from datetime import datetime

import pytest

from servicedoc.docs.changelog import deduplicate, group_entries
from servicedoc.models.docs import ChangelogEntry


def make_entry(msg: str, kind: str = "feat", breaking: bool = False) -> ChangelogEntry:
    return ChangelogEntry(
        sha="abc123",
        message=msg,
        author="test",
        date=datetime.now(),
        kind=kind,  # type: ignore
        breaking=breaking,
    )


def test_duplicate_messages_merged():
    # nearly identical messages should cluster into one
    entries = [
        make_entry("добавить поддержку JWT аутентификации пользователей"),
        make_entry("добавлена поддержка JWT аутентификации пользователей"),
        make_entry("добавить поддержку JWT аутентификации для всех пользователей"),
    ]
    result = deduplicate(entries)
    assert len(result) == 1


def test_pair_duplicate_merged():
    entries = [
        make_entry("добавить поддержку JWT аутентификации"),
        make_entry("добавлена поддержка JWT аутентификации"),
        make_entry("исправить ошибку в базе данных"),
    ]
    result = deduplicate(entries)
    assert len(result) == 2


def test_different_messages_kept():
    entries = [
        make_entry("добавить JWT аутентификацию"),
        make_entry("исправить ошибку в базе данных"),
        make_entry("рефакторинг модуля пользователей"),
    ]
    result = deduplicate(entries)
    assert len(result) == 3


def test_groups_breaking_separately():
    entries = [
        make_entry("изменить API метода GetUser", kind="feat", breaking=True),
        make_entry("добавить поддержку pagination", kind="feat"),
        make_entry("исправить утечку памяти", kind="fix"),
    ]
    groups = group_entries(entries)
    assert "breaking" in groups
    assert "feat" in groups
    assert "fix" in groups
    assert len(groups["breaking"]) == 1
