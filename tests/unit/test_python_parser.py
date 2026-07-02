from pathlib import Path

import pytest

from servicedoc.parsers.python.parser import PythonParser


@pytest.fixture
def py_fixture() -> Path:
    return Path(__file__).parent.parent / "fixtures" / "sample_python"


@pytest.mark.asyncio
async def test_public_functions_captured(py_fixture):
    parser = PythonParser()
    symbols = await parser.parse_file(py_fixture / "main.py")
    names = {s.name for s in symbols}
    assert "get_user" in names
    assert "create_user" in names


@pytest.mark.asyncio
async def test_private_functions_skipped(py_fixture):
    parser = PythonParser()
    symbols = await parser.parse_file(py_fixture / "main.py")
    assert all(not s.name.startswith("_") for s in symbols)


@pytest.mark.asyncio
async def test_classes_captured(py_fixture):
    parser = PythonParser()
    symbols = await parser.parse_file(py_fixture / "main.py")
    class_names = {s.name for s in symbols if s.kind == "class"}
    assert "CreateUserRequest" in class_names
    assert "UserResponse" in class_names


@pytest.mark.asyncio
async def test_docstring_extracted(py_fixture):
    parser = PythonParser()
    symbols = await parser.parse_file(py_fixture / "main.py")
    get_user = next((s for s in symbols if s.name == "get_user"), None)
    assert get_user is not None
    assert get_user.comment is not None
    assert "пользователя" in get_user.comment.lower()
