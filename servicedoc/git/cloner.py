import asyncio
import logging
from pathlib import Path

import git

from servicedoc.config import GitConfig

logger = logging.getLogger(__name__)


def parse_url_branch(url: str) -> tuple[str, str | None]:
    """Extract branch from URL if encoded as '<url>@branch'.

    Only looks for '@' in the final path segment (after the last '/' or ':'),
    so it doesn't confuse an SSH auth prefix (git@host, ssh://git@host/...)
    or scp-style syntax (git@host:group/repo.git) with a branch suffix.
    """
    last_sep = max(url.rfind("/"), url.rfind(":"))
    tail = url[last_sep + 1:]
    if "@" in tail:
        base, branch = tail.rsplit("@", 1)
        return url[:last_sep + 1] + base, branch
    return url, None


def _detect_default_branch(auth_url: str) -> str:
    """Query remote HEAD to detect default branch name."""
    try:
        refs = git.cmd.Git().ls_remote("--symref", auth_url, "HEAD")
        for line in refs.splitlines():
            # ref: refs/heads/main	HEAD
            if line.startswith("ref: refs/heads/"):
                return line.split("refs/heads/")[1].split("\t")[0].strip()
    except Exception as exc:
        logger.debug("Could not detect default branch: %s", exc)
    return "main"


class GitCloner:
    def __init__(self, config: GitConfig, cache_dir: Path) -> None:
        self.config = config
        self.cache_dir = cache_dir

    def _auth_url(self, url: str) -> str:
        # token injection only applies to HTTPS; SSH URLs (git@host:...,
        # ssh://git@host/...) authenticate via the system's SSH agent/keys.
        if not url.startswith(("http://", "https://")):
            return url
        if "github.com" in url and self.config.github_token:
            return url.replace("https://", f"https://{self.config.github_token}@")
        if "gitlab" in url and self.config.gitlab_token:
            return url.replace("https://", f"https://oauth2:{self.config.gitlab_token}@")
        return url

    async def clone(self, url: str, target_dir: Path, branch: str = "main") -> Path:
        # allow branch encoded in URL: https://github.com/org/repo@feature-branch
        clean_url, url_branch = parse_url_branch(url)
        if url_branch:
            branch = url_branch
            url = clean_url

        auth_url = self._auth_url(url)

        def _do_clone() -> None:
            nonlocal branch
            if (target_dir / ".git").exists():
                logger.info("Repo already cloned at %s, pulling", target_dir)
                repo = git.Repo(target_dir)
                repo.remotes.origin.pull()
                return
            target_dir.mkdir(parents=True, exist_ok=True)
            # auto-detect default branch if caller passed sentinel "main" and it may not exist
            resolved_branch = branch
            try:
                logger.info("Cloning %s (branch=%s) → %s", url, resolved_branch, target_dir)
                git.Repo.clone_from(auth_url, target_dir, branch=resolved_branch)
            except git.GitCommandError:
                # branch not found — detect actual default branch
                logger.warning("Branch '%s' not found, detecting default branch...", resolved_branch)
                resolved_branch = _detect_default_branch(auth_url)
                logger.info("Using default branch: %s", resolved_branch)
                git.Repo.clone_from(auth_url, target_dir, branch=resolved_branch)

        await asyncio.wait_for(
            asyncio.to_thread(_do_clone),
            timeout=self.config.clone_timeout_seconds,
        )
        return target_dir
