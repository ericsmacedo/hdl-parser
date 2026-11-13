# MIT License
#
# Copyright (c) 2026 ericsmacedo
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Compare the output of ``hdl_parser`` between two git revisions.

Usage::

    uv run python tools/compare_refs.py [OPTIONS] FILES...

Each side is parsed in a subprocess with ``PYTHONPATH=<tree>/src``, so the revision under test is the code that runs.
Nothing is written inside the repository and nothing leaves the machine: results go to stdout and, optionally, to the
directory given by ``--out``.

Exit codes: 0 everything identical, 1 differences found, 2 usage or git error.
"""

from __future__ import annotations

import argparse
import contextlib
import difflib
import inspect
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

IDENTICAL = "identical"
CHANGED = "changed"
NEWLY_FAILING = "newly failing"
NEWLY_PASSING = "newly passing"
FAILING_BOTH = "failing on both"
CLASSES = (IDENTICAL, CHANGED, NEWLY_FAILING, NEWLY_PASSING, FAILING_BOTH)

SUFFIXES = (".sv", ".v")
WORKING_TREE = "working tree"

EXIT_OK = 0
EXIT_DIFF = 1
EXIT_USAGE = 2


class ToolError(Exception):
    """Usage or git problem. Mapped to exit code 2."""


# --------------------------------------------------------------------------------------------------------------------
# Input collection
# --------------------------------------------------------------------------------------------------------------------


def collect_inputs(paths: Sequence[str | Path], filelists: Sequence[str | Path] = ()) -> list[str]:
    """Collect HDL files from files, directories and filelists.

    Directories are searched recursively for ``*.sv`` and ``*.v``. Duplicates are removed, order is kept.

    Args:
        paths: Files and/or directories.
        filelists: Filelist files, parsed by ``hdl_parser.filelistparser.parse_filelist``.

    Returns:
        File paths, as given by the user (or as written in the filelist).

    Raises:
        ToolError: A path does not exist or nothing was found.
    """
    found: list[Path] = []
    for item in map(Path, paths):
        if item.is_dir():
            found.extend(sorted(p for p in item.rglob("*") if p.is_file() and p.suffix in SUFFIXES))
        elif item.is_file():
            found.append(item)
        else:
            raise ToolError(f"No such file or directory: {item}")
    if filelists:
        from hdl_parser.filelistparser import parse_filelist  # noqa: PLC0415

        for filelist in map(Path, filelists):
            if not filelist.is_file():
                raise ToolError(f"No such filelist: {filelist}")
            parse_filelist(found, [], filelist)
    result = list(dict.fromkeys(str(p) for p in found))
    if not result:
        raise ToolError("No input files found.")
    return result


# --------------------------------------------------------------------------------------------------------------------
# Dump mode (runs in a subprocess, against the revision under test)
# --------------------------------------------------------------------------------------------------------------------


def dump_files(files: Sequence[str], macro_files: Sequence[str] = (), expected_tree: str | Path | None = None) -> dict:
    """Parse all files with the currently importable ``hdl_parser``.

    Args:
        files: Input files.
        macro_files: Files with macro definitions.
        expected_tree: When given, ``hdl_parser`` must be imported from below this directory.

    Returns:
        ``{"notes": [...], "files": {path: {"result": ..., "seconds": ...}}}``

    Raises:
        RuntimeError: ``hdl_parser`` was imported from somewhere else than ``expected_tree``.
    """
    import hdl_parser  # noqa: PLC0415

    if expected_tree is not None:
        module_file = Path(hdl_parser.__file__).resolve()
        if not module_file.is_relative_to(Path(expected_tree).resolve()):
            raise RuntimeError(f"hdl_parser imported from {module_file}, expected below {expected_tree}")

    notes: list[str] = []
    kwargs: dict[str, Any] = {}
    if macro_files:
        supports_macros = (
            hasattr(hdl_parser, "parse_defines") and "macros" in inspect.signature(hdl_parser.parse_file).parameters
        )
        if supports_macros:
            kwargs["macros"] = hdl_parser.parse_defines(*macro_files)
        else:
            notes.append("this revision does not support macro files; parsed without them")

    results: dict[str, dict] = {}
    for path in files:
        start = time.perf_counter()
        try:
            data = json.loads(hdl_parser.parse_file(path, **kwargs).overview)
            if "path" in data:
                data["path"] = path
            result: dict = data
        except Exception as exc:
            result = {"error": f"{type(exc).__name__}: {exc}"}
        results[path] = {"result": result, "seconds": time.perf_counter() - start}
    return {"notes": notes, "files": results}


def _run_dump_mode(args: argparse.Namespace) -> int:
    request = json.loads(Path(args.dump_request).read_text(encoding="utf-8"))
    dump = dump_files(request["files"], request["macro_files"], args.dump_tree)
    Path(args.dump_to).write_text(json.dumps(dump), encoding="utf-8")
    return EXIT_OK


# --------------------------------------------------------------------------------------------------------------------
# Running one side
# --------------------------------------------------------------------------------------------------------------------


def _git(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise ToolError("git not found") from exc
    if proc.returncode != 0:
        raise ToolError(f"git {' '.join(args)} failed: {proc.stderr.strip()}")
    return proc.stdout


def repo_root() -> Path:
    """Return the root of the git repository containing this script."""
    return Path(_git(Path(__file__).resolve().parent, "rev-parse", "--show-toplevel").strip())


@contextlib.contextmanager
def checkout(root: Path, ref: str | None) -> Iterator[Path]:
    """Yield a source tree for ``ref``; the repository itself for ``None`` (working tree).

    A ref is checked out into a temporary detached worktree which is always removed.
    """
    if ref is None:
        yield root
        return
    _git(root, "rev-parse", "--verify", "--quiet", f"{ref}^{{commit}}")
    tmp = Path(tempfile.mkdtemp(prefix="compare_refs_"))
    tree = tmp / "tree"
    try:
        _git(root, "worktree", "add", "--detach", str(tree), ref)
        yield tree
    finally:
        try:
            if tree.exists():
                subprocess.run(
                    ["git", "-C", str(root), "worktree", "remove", "--force", str(tree)],
                    capture_output=True,
                    check=False,
                )
            subprocess.run(["git", "-C", str(root), "worktree", "prune"], capture_output=True, check=False)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


def run_side(tree: Path, files: Sequence[str], macro_files: Sequence[str]) -> dict:
    """Run dump mode in a subprocess that imports ``hdl_parser`` from ``tree/src``.

    Args:
        tree: Source tree (repository or worktree).
        files: Input files.
        macro_files: Macro files.

    Returns:
        The dump, see ``dump_files``.

    Raises:
        ToolError: The subprocess failed.
    """
    with tempfile.TemporaryDirectory(prefix="compare_refs_dump_") as tmp:
        request = Path(tmp) / "request.json"
        output = Path(tmp) / "dump.json"
        request.write_text(json.dumps({"files": list(files), "macro_files": list(macro_files)}), encoding="utf-8")
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join(filter(None, [str(tree / "src"), env.get("PYTHONPATH")]))
        env["PYTHONDONTWRITEBYTECODE"] = "1"  # never write __pycache__ into the tree
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--dump-to",
            str(output),
            "--dump-request",
            str(request),
            "--dump-tree",
            str(tree),
        ]
        proc = subprocess.run(cmd, env=env, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            raise ToolError(f"parsing in {tree} failed:\n{proc.stderr.strip()}")
        return json.loads(output.read_text(encoding="utf-8"))


# --------------------------------------------------------------------------------------------------------------------
# Comparison and rendering
# --------------------------------------------------------------------------------------------------------------------


def _is_error(result: dict) -> bool:
    return set(result) == {"error"}


def classify(base: dict, head: dict) -> str:
    """Classify the results of one file on both sides."""
    base_err, head_err = _is_error(base), _is_error(head)
    if base_err and head_err:
        return FAILING_BOTH
    if head_err:
        return NEWLY_FAILING
    if base_err:
        return NEWLY_PASSING
    return IDENTICAL if base == head else CHANGED


def compare(base: dict, head: dict) -> dict[str, str]:
    """Classify every file of two dumps.

    Args:
        base: Dump of the base side.
        head: Dump of the head side.

    Returns:
        Mapping from input path to class, in input order.
    """
    return {
        path: classify(entry["result"], head["files"][path]["result"])
        for path, entry in base["files"].items()
        if path in head["files"]
    }


def _pretty(result: dict) -> list[str]:
    return json.dumps(result, indent=2, sort_keys=True).splitlines(keepends=True)


def render_diff(path: str, base: dict, head: dict, base_label: str = "base", head_label: str = "head") -> str:
    """Return the unified diff of the pretty-printed results of one file."""
    lines = difflib.unified_diff(
        _pretty(base), _pretty(head), fromfile=f"{base_label}:{path}", tofile=f"{head_label}:{path}"
    )
    return "".join(line if line.endswith("\n") else line + "\n" for line in lines)


def has_differences(classes: dict[str, str], base: dict, head: dict) -> bool:
    """Return True if anything differs. Failing on both with the same error does not count."""
    for path, cls in classes.items():
        if cls == FAILING_BOTH:
            if base["files"][path]["result"] != head["files"][path]["result"]:
                return True
        elif cls != IDENTICAL:
            return True
    return False


def total_seconds(dump: dict) -> float:
    """Return the total parse time of a dump."""
    return sum(entry["seconds"] for entry in dump["files"].values())


def render_report(
    base: dict, head: dict, base_label: str = "base", head_label: str = "head", quiet: bool = False
) -> tuple[str, int]:
    """Render diffs and summary.

    Args:
        base: Dump of the base side.
        head: Dump of the head side.
        base_label: Name of the base side.
        head_label: Name of the head side.
        quiet: Summary only.

    Returns:
        The report text and the exit code (0 identical, 1 differences).
    """
    classes = compare(base, head)
    out: list[str] = []
    for side, dump in ((base_label, base), (head_label, head)):
        out.extend(f"note ({side}): {note}\n" for note in dump.get("notes", []))
    if not quiet:
        for path, cls in classes.items():
            b, h = base["files"][path]["result"], head["files"][path]["result"]
            if cls == IDENTICAL or (cls == FAILING_BOTH and b == h):
                continue
            out.append(f"=== {cls}: {path}\n")
            out.append(render_diff(path, b, h, base_label, head_label))
    counts = Counter(classes.values())
    out.append(f"Summary: {base_label} -> {head_label}, {len(classes)} files\n")
    out.extend(f"  {cls:<16} {counts[cls]}\n" for cls in CLASSES)
    t_base, t_head = total_seconds(base), total_seconds(head)
    ratio = f"{t_head / t_base:.2f}x" if t_base > 0 else "n/a"
    out.append(f"Parse time: {base_label} {t_base:.3f}s, {head_label} {t_head:.3f}s, ratio {ratio}\n")
    return "".join(out), EXIT_DIFF if has_differences(classes, base, head) else EXIT_OK


# --------------------------------------------------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(description="Compare hdl_parser output between two git revisions.")
    parser.add_argument("files", nargs="*", metavar="FILES", help="Files and/or directories (searched for *.sv, *.v)")
    parser.add_argument("--base", default="main", help="Base git ref. Default: main")
    parser.add_argument(
        "--head", default=None, help="Head git ref. Default: the working tree incl. uncommitted changes"
    )
    parser.add_argument("-f", "--filelist", action="append", default=[], metavar="PATH", help="Filelist (repeatable)")
    parser.add_argument(
        "-m", "--macro-file", action="append", default=[], metavar="PATH", help="Macro file (repeatable)"
    )
    parser.add_argument("--out", metavar="DIR", help="Directory to keep base.json and head.json (outside the repo)")
    parser.add_argument("--quiet", action="store_true", help="Summary only")
    parser.add_argument("--dump-to", help=argparse.SUPPRESS)
    parser.add_argument("--dump-request", help=argparse.SUPPRESS)
    parser.add_argument("--dump-tree", help=argparse.SUPPRESS)
    return parser


def _prepare_out(out: str | None, root: Path) -> Path | None:
    if out is None:
        return None
    out_dir = Path(out).resolve()
    if out_dir == root or root in out_dir.parents:
        raise ToolError(f"--out must be outside the repository ({root})")
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def _run(args: argparse.Namespace) -> int:
    root = repo_root()
    out_dir = _prepare_out(args.out, root)
    for macro_file in args.macro_file:
        if not Path(macro_file).is_file():
            raise ToolError(f"No such macro file: {macro_file}")
    files = collect_inputs(args.files, args.filelist)

    dumps = []
    for ref in (args.base, args.head):
        with checkout(root, ref) as tree:
            dumps.append(run_side(tree, files, args.macro_file))
    base, head = dumps
    if out_dir is not None:
        (out_dir / "base.json").write_text(json.dumps(base, indent=2, sort_keys=True), encoding="utf-8")
        (out_dir / "head.json").write_text(json.dumps(head, indent=2, sort_keys=True), encoding="utf-8")

    text, code = render_report(base, head, args.base, args.head or WORKING_TREE, args.quiet)
    sys.stdout.write(text)
    return code


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point.

    Args:
        argv: Command line arguments. ``sys.argv[1:]`` by default.

    Returns:
        Exit code: 0 identical, 1 differences, 2 usage or git error.
    """
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.dump_to:
        return _run_dump_mode(args)
    if not args.files and not args.filelist:
        parser.error("no input files given")
    try:
        return _run(args)
    except ToolError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return EXIT_USAGE
    except KeyboardInterrupt:
        sys.stderr.write("interrupted\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())
