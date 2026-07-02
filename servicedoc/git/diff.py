import asyncio
from pathlib import Path

import git


class DiffExtractor:
    def __init__(self, repo_path: Path) -> None:
        self.repo_path = repo_path

    async def get_diff(self, from_ref: str | None, to_ref: str) -> dict[str, str]:
        def _get() -> dict[str, str]:
            repo = git.Repo(self.repo_path)
            if from_ref:
                diffs = repo.commit(from_ref).diff(repo.commit(to_ref), create_patch=True)
            else:
                # first tag: diff against the empty tree, not the working dir,
                # so the result is "everything present at to_ref" rather than
                # "to_ref vs whatever HEAD/working tree currently is".
                diffs = repo.commit(to_ref).diff(git.NULL_TREE, create_patch=True)
            result: dict[str, str] = {}
            for d in diffs:
                path_key = d.b_path or d.a_path
                if path_key and d.diff:
                    result[path_key] = d.diff.decode("utf-8", errors="replace")
            return result

        return await asyncio.to_thread(_get)

    async def stats(self, from_ref: str | None, to_ref: str) -> dict[str, int]:
        def _get() -> dict[str, int]:
            repo = git.Repo(self.repo_path)
            if from_ref:
                diffs = repo.commit(from_ref).diff(repo.commit(to_ref), create_patch=True)
            else:
                diffs = repo.commit(to_ref).diff(git.NULL_TREE, create_patch=True)
            added = removed = 0
            file_count = 0
            for d in diffs:
                file_count += 1
                if d.diff:
                    text = d.diff.decode("utf-8", errors="replace")
                    for line in text.splitlines():
                        if line.startswith("+") and not line.startswith("+++"):
                            added += 1
                        elif line.startswith("-") and not line.startswith("---"):
                            removed += 1
            return {"files": file_count, "added": added, "removed": removed}

        return await asyncio.to_thread(_get)
