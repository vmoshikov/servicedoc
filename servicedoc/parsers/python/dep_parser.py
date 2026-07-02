import re
import tomllib
from pathlib import Path

from servicedoc.models.repo import Dependency

_GIT_HOSTS = ("github.com", "gitlab.com", "gitlab.", "bitbucket.org")
_GIT_DEP = re.compile(r"git\+https?://([^@#]+)")
_VERSION_SEP = re.compile(r"[><=!~\[;]")


def _is_git_url(dep: str) -> bool:
    return dep.startswith("git+")


def _name_from_git_url(url: str) -> str:
    m = _GIT_DEP.search(url)
    if m:
        return m.group(1).rstrip("/").split("/")[-1]
    return url


def parse_pyproject(path: Path) -> list[Dependency]:
    deps: list[Dependency] = []
    with open(path, "rb") as f:
        data = tomllib.load(f)

    raw = data.get("project", {}).get("dependencies", [])
    for dep_str in raw:
        dep_str = dep_str.strip()
        if _is_git_url(dep_str):
            m = _GIT_DEP.search(dep_str)
            git_url = m.group(0).replace("git+", "") if m else None
            name = _name_from_git_url(dep_str)
            deps.append(Dependency(name=name, version="git", git_url=git_url, is_external_git=True))
        else:
            name = _VERSION_SEP.split(dep_str)[0].strip()
            version = dep_str[len(name):].strip() or "*"
            is_git = any(h in name for h in _GIT_HOSTS)
            deps.append(Dependency(name=name, version=version, is_external_git=is_git))

    return deps


def parse_requirements(path: Path) -> list[Dependency]:
    deps: list[Dependency] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if _is_git_url(line):
            m = _GIT_DEP.search(line)
            git_url = m.group(0).replace("git+", "") if m else None
            name = _name_from_git_url(line)
            deps.append(Dependency(name=name, version="git", git_url=git_url, is_external_git=True))
        else:
            name = _VERSION_SEP.split(line)[0].strip()
            version = line[len(name):].strip() or "*"
            deps.append(Dependency(name=name, version=version))

    return deps
