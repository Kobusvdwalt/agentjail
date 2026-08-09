"""Selecting which shared resources a sandbox can see.

A sandbox declares the resources it wants as a list of glob patterns, matched
against paths relative to the resources directory (`vigil-api/SKILL.md`, never a
leading slash). `["*"]` means everything, which is what a sandbox that says
nothing gets — the default has to keep existing callers working unchanged.

The patterns decide two separate things, and both matter:

- what is *mounted* into the sandbox, in `nsjail.py`
- what `sandbox_resources` *lists*, in `manager.py`

Filtering only the listing would be theatre: `/resources` is one bind mount, so
anything mounted can be read with `cat` whether it was listed or not. The mount
is the boundary that holds; the listing is filtered to match so an agent is not
told about files it will then fail to open.
"""

import fnmatch
from pathlib import PurePosixPath

# What a sandbox that expresses no preference gets. Every resource, matching the
# behaviour from before patterns existed.
ALL_RESOURCES = ["*"]


def _matches(rel: str, pattern: str) -> bool:
    """Whether one relative path satisfies one pattern.

    `fnmatch` alone is not enough here. Its `*` crosses directory separators, so
    `vigil-api/*` would match `vigil-api/deep/nested/file.txt` — surprising for
    anyone who has written a `.gitignore`. Matching segment by segment gives `*`
    the shell meaning of "within one directory", and `**` the meaning of "any
    depth".
    """
    if pattern == "*" or pattern == "**":
        return True

    parts = PurePosixPath(rel).parts
    globs = PurePosixPath(pattern).parts

    return _match_parts(parts, globs)


def _match_parts(parts: tuple[str, ...], globs: tuple[str, ...]) -> bool:
    """Match path segments against pattern segments, honouring `**`."""
    if not globs:
        return not parts

    head, *rest = globs

    if head == "**":
        # `**` swallows any number of segments, including none, so try every
        # split and take the first that lets the remaining pattern match.
        for index in range(len(parts) + 1):
            if _match_parts(parts[index:], tuple(rest)):
                return True
        return False

    if not parts:
        return False

    if not fnmatch.fnmatchcase(parts[0], head):
        return False

    return _match_parts(parts[1:], tuple(rest))


def matches(rel: str, patterns: list[str]) -> bool:
    """Whether `rel` is selected by any of `patterns`."""
    return any(_matches(rel, pattern) for pattern in patterns)


def is_prefix_of_match(rel: str, patterns: list[str]) -> bool:
    """Whether `rel` is a directory worth descending into.

    A pattern of `vigil-api/SKILL.md` selects no directory at all, yet the
    directory `vigil-api/` has to be walked to reach the file and has to be
    mounted for the file to be readable. This answers "could something under
    here still match?", which is the question both the walk and the mount are
    really asking about a directory.
    """
    parts = PurePosixPath(rel).parts

    for pattern in patterns:
        globs = PurePosixPath(pattern).parts

        if pattern in ("*", "**"):
            return True

        # A directory is worth entering when the pattern agrees with it as far
        # as the directory goes — the rest of the pattern applies to what is
        # inside it.
        if _match_prefix(parts, globs):
            return True

    return False


def _match_prefix(parts: tuple[str, ...], globs: tuple[str, ...]) -> bool:
    """Whether `parts` could be an ancestor of something matching `globs`."""
    if not parts:
        return True

    if not globs:
        return False

    head, *rest = globs

    if head == "**":
        return True

    if not fnmatch.fnmatchcase(parts[0], head):
        return False

    return _match_prefix(parts[1:], tuple(rest))


def selected_paths(base, patterns: list[str]) -> list:
    """Every path under `base` that `patterns` selects, directories included.

    Returned in sorted order, as relative `Path`s. Directories are included when
    they match in their own right or when something inside them might, so a
    caller can mount or list them without walking the tree a second time.
    """
    selected = []

    for item in sorted(base.rglob("*")):
        rel = item.relative_to(base)
        rel_str = rel.as_posix()

        if item.is_dir():
            if matches(rel_str, patterns) or is_prefix_of_match(rel_str, patterns):
                selected.append(rel)
        elif matches(rel_str, patterns):
            selected.append(rel)

    return selected


def mount_roots(base, patterns: list[str]) -> list:
    """The shallowest directories and files that cover everything selected.

    Mounting one path per matched file would mean a bind mount per file, and
    nsjail takes a flag for each. This collapses the selection to its top-level
    entries: if a directory is fully selected it is mounted whole, and only
    partially-selected directories are descended into.
    """
    roots: list = []

    def walk(directory, rel_prefix) -> None:
        for item in sorted(directory.iterdir()):
            rel = rel_prefix / item.name if rel_prefix else PurePosixPath(item.name)
            rel_str = str(rel)

            if item.is_dir():
                if _fully_selected(item, base, patterns):
                    roots.append(rel)
                elif is_prefix_of_match(rel_str, patterns) or matches(
                    rel_str, patterns
                ):
                    walk(item, rel)
            elif matches(rel_str, patterns):
                roots.append(rel)

    walk(base, None)

    return roots


def _fully_selected(directory, base, patterns: list[str]) -> bool:
    """Whether every file beneath `directory` is selected.

    Only then can the directory be mounted as a unit — otherwise mounting it
    would hand over files the patterns excluded, which is the failure this
    module exists to prevent.
    """
    files = [item for item in directory.rglob("*") if item.is_file()]

    if not files:
        # Nothing inside to leak. Mount it so an empty selected directory still
        # appears, rather than silently vanishing.
        return matches(directory.relative_to(base).as_posix(), patterns)

    return all(matches(item.relative_to(base).as_posix(), patterns) for item in files)
