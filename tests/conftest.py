import subprocess
from pathlib import Path

import pytest


@pytest.fixture
def go_fixture_path() -> Path:
    return Path(__file__).parent / "fixtures" / "sample_go"


@pytest.fixture
def python_fixture_path() -> Path:
    return Path(__file__).parent / "fixtures" / "sample_python"


@pytest.fixture
def go_fixture_repo(go_fixture_path: Path, tmp_path: Path) -> Path:
    """Copy sample_go to tmp_path and init git with a tag."""
    import shutil
    dest = tmp_path / "sample_go"
    shutil.copytree(go_fixture_path, dest)
    subprocess.run(["git", "init"], cwd=dest, check=True, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=dest, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "feat: initial commit"],
        cwd=dest, check=True, capture_output=True,
        env={"GIT_AUTHOR_NAME": "test", "GIT_AUTHOR_EMAIL": "t@t.com",
             "GIT_COMMITTER_NAME": "test", "GIT_COMMITTER_EMAIL": "t@t.com",
             "HOME": str(tmp_path)},
    )
    subprocess.run(["git", "tag", "v0.1.0"], cwd=dest, check=True, capture_output=True)
    return dest
