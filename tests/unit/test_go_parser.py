from pathlib import Path

import pytest

from servicedoc.parsers.go.parser import GoParser


@pytest.fixture
def go_fixture() -> Path:
    return Path(__file__).parent.parent / "fixtures" / "sample_go"


@pytest.mark.asyncio
async def test_exported_functions_captured(go_fixture):
    parser = GoParser()
    symbols = await parser.parse_file(go_fixture / "main.go")
    names = {s.name for s in symbols}
    assert "GetUser" in names
    assert "CreateUser" in names
    assert "DeleteUser" in names


@pytest.mark.asyncio
async def test_unexported_skipped(go_fixture):
    parser = GoParser()
    symbols = await parser.parse_file(go_fixture / "main.go")
    names = {s.name for s in symbols}
    assert "main" not in names


@pytest.mark.asyncio
async def test_comment_extracted(go_fixture):
    parser = GoParser()
    symbols = await parser.parse_file(go_fixture / "main.go")
    get_user = next((s for s in symbols if s.name == "GetUser"), None)
    assert get_user is not None
    assert get_user.comment is not None
    assert "пользователя" in get_user.comment


@pytest.mark.asyncio
async def test_needs_ai_false_when_comment_exists(go_fixture):
    parser = GoParser()
    symbols = await parser.parse_file(go_fixture / "main.go")
    get_user = next((s for s in symbols if s.name == "GetUser"), None)
    assert get_user is not None
    assert get_user.needs_ai is False
