import re
from pathlib import Path

from servicedoc.models.repo import Dependency

_REQUIRE_LINE = re.compile(r"^\s+([\w./\-]+)\s+(v[\w.\-+]+)")
_GIT_HOSTS = ("github.com", "gitlab.com", "gitlab.", "bitbucket.org")


def parse_go_mod(path: Path) -> list[Dependency]:
    deps: list[Dependency] = []
    in_require = False

    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("require ("):
            in_require = True
            continue
        if in_require and stripped == ")":
            in_require = False
            continue
        if stripped.startswith("require ") or in_require:
            m = _REQUIRE_LINE.match(line)
            if m:
                name, version = m.group(1), m.group(2)
                is_git = any(host in name for host in _GIT_HOSTS)
                git_url = f"https://{name}" if is_git else None
                deps.append(Dependency(
                    name=name,
                    version=version,
                    git_url=git_url,
                    is_external_git=is_git,
                ))

    return deps
