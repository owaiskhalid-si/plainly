"""Which files to lint."""

from __future__ import annotations

import fnmatch
import subprocess
from pathlib import Path

from plainly.config import Config


def collect_files(paths: list[str], config: Config) -> list[Path]:
    """Files to lint: explicit files as given; directories expanded with the include patterns,
    minus excludes. With no paths, the config root (or the working directory)."""
    targets = [Path(p) for p in paths] or [config.root]
    out: list[Path] = []
    seen: set[Path] = set()
    for target in targets:
        if target.is_file():
            candidates = [target]
        elif target.is_dir():
            candidates = sorted({p for pattern in config.include for p in target.glob(pattern) if p.is_file()})
        else:
            raise FileNotFoundError(str(target))
        for path in candidates:
            resolved = path.resolve()
            if resolved in seen or (target.is_dir() and is_excluded(path, target, config.exclude)):
                continue
            seen.add(resolved)
            out.append(path)
    return out


def is_excluded(path: Path, base: Path, patterns: list[str]) -> bool:
    try:
        rel = path.relative_to(base)
    except ValueError:
        rel = path
    posix = rel.as_posix()
    for pattern in patterns:
        if fnmatch.fnmatch(posix, pattern) or fnmatch.fnmatch(path.name, pattern):
            return True
        if any(fnmatch.fnmatch(part, pattern) for part in rel.parts[:-1]):
            return True
    return False


def changed_files(ref: str, config: Config) -> list[Path]:
    """Files changed since `ref` (per `git diff --name-only`), filtered by the include patterns."""
    result = subprocess.run(
        ["git", "diff", "--name-only", "--diff-filter=ACMR", ref],
        capture_output=True,
        text=True,
        check=True,
        cwd=config.root,
    )
    root = _git_root(config.root)
    out: list[Path] = []
    for line in result.stdout.splitlines():
        name = line.strip()
        if not name:
            continue
        path = root / name
        if path.is_file() and matches_include(path, config) and not is_excluded(path, root, config.exclude):
            out.append(path)
    return out


def matches_include(path: Path, config: Config) -> bool:
    posix = path.as_posix()
    return any(
        fnmatch.fnmatch(posix, pattern) or fnmatch.fnmatch(path.name, pattern.split("/")[-1])
        for pattern in config.include
    )


def _git_root(start: Path) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True, cwd=start
    )
    return Path(result.stdout.strip())
