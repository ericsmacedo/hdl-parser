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
"""Tests for ``tools/compare_refs.py``."""

import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
TOOL = ROOT / "tools" / "compare_refs.py"

spec = importlib.util.spec_from_file_location("compare_refs", TOOL)
assert spec is not None
assert spec.loader is not None
tool = importlib.util.module_from_spec(spec)
sys.modules["compare_refs"] = tool
_dont_write = sys.dont_write_bytecode
sys.dont_write_bytecode = True  # do not leave tools/__pycache__ behind
try:
    spec.loader.exec_module(tool)
finally:
    sys.dont_write_bytecode = _dont_write


def _dump(**files: tuple[dict, float]) -> dict:
    return {"notes": [], "files": {name: {"result": res, "seconds": sec} for name, (res, sec) in files.items()}}


OK = {"path": "a.sv", "modules": [{"name": "a"}]}
OK2 = {"path": "a.sv", "modules": [{"name": "a", "ports": [{"name": "p"}]}]}
ERR = {"error": "RuntimeError: No module found."}
ERR2 = {"error": "ValueError: other"}


@pytest.mark.parametrize(
    ("base", "head", "expected"),
    [
        (OK, OK, tool.IDENTICAL),
        (OK, OK2, tool.CHANGED),
        (OK, ERR, tool.NEWLY_FAILING),
        (ERR, OK, tool.NEWLY_PASSING),
        (ERR, ERR, tool.FAILING_BOTH),
    ],
)
def test_classify(base, head, expected):
    """Every class."""
    assert tool.classify(base, head) == expected


def test_report_identical():
    """Identical dumps give exit code 0 and a summary."""
    base = _dump(x=(OK, 1.0))
    head = _dump(x=(OK, 2.0))
    text, code = tool.render_report(base, head)
    assert code == 0
    assert "identical        1" in text
    assert "ratio 2.00x" in text
    assert "===" not in text


def test_report_all_classes():
    """Diffs are rendered for differing files, the summary counts each class."""
    base = _dump(a=(OK, 1), b=(OK, 1), c=(OK, 1), d=(ERR, 1), e=(ERR, 1))
    head = _dump(a=(OK, 1), b=(OK2, 1), c=(ERR, 1), d=(OK, 1), e=(ERR, 1))
    text, code = tool.render_report(base, head, "main", "wt")
    assert code == 1
    assert "=== changed: b" in text
    assert "--- main:b" in text
    assert "+++ wt:b" in text
    assert '+          "name": "p"' in text
    assert "=== newly failing: c" in text
    assert "=== newly passing: d" in text
    assert "=== failing on both: e" not in text  # same error on both sides
    for cls in tool.CLASSES:
        assert f"  {cls:<16} 1" in text


def test_report_quiet_and_notes():
    """Quiet omits diffs, notes are shown."""
    base = _dump(x=(OK, 1.0))
    base["notes"] = ["no macros"]
    head = _dump(x=(OK2, 1.0))
    text, code = tool.render_report(base, head, quiet=True)
    assert code == 1
    assert "note (base): no macros" in text
    assert "===" not in text
    assert "changed          1" in text


def test_failing_on_both_different_error():
    """A different error on both sides is a difference."""
    base = _dump(x=(ERR, 1.0))
    head = _dump(x=(ERR2, 1.0))
    text, code = tool.render_report(base, head)
    assert code == 1
    assert "=== failing on both: x" in text


def test_zero_base_time():
    """No division by zero."""
    text, _ = tool.render_report(_dump(x=(OK, 0.0)), _dump(x=(OK, 0.0)))
    assert "ratio n/a" in text


def test_collect_inputs(tmp_path):
    """Files, directories (recursive, sv and v only), filelist, deduplication."""
    (tmp_path / "sub").mkdir()
    a = tmp_path / "a.sv"
    b = tmp_path / "sub" / "b.v"
    c = tmp_path / "c.sv"
    for path in (a, b, c, tmp_path / "sub" / "notes.txt"):
        path.write_text("x")
    filelist = tmp_path / "files.f"
    filelist.write_text("c.sv\n")

    assert tool.collect_inputs([tmp_path]) == [str(a), str(c), str(b)]
    assert tool.collect_inputs([a, a]) == [str(a)]
    assert tool.collect_inputs([a], [filelist]) == [str(a), str(c)]
    assert tool.collect_inputs([], [filelist]) == [str(c)]


def test_collect_inputs_errors(tmp_path):
    """Missing paths and empty results are usage errors."""
    with pytest.raises(tool.ToolError):
        tool.collect_inputs([tmp_path / "missing.sv"])
    with pytest.raises(tool.ToolError):
        tool.collect_inputs([tmp_path])
    with pytest.raises(tool.ToolError):
        tool.collect_inputs([], [tmp_path / "missing.f"])


def test_dump_files():
    """Dump mode on a good file and on a file that raises."""
    missing = ROOT / "tests" / "_does_not_exist.sv"
    adder = ROOT / "examples" / "sv" / "adder.sv"
    dump = tool.dump_files([str(adder), str(missing)], expected_tree=ROOT)
    good = dump["files"][str(adder)]
    assert good["result"]["path"] == str(adder)
    assert good["result"]["modules"][0]["name"] == "adder"
    assert good["seconds"] >= 0
    assert dump["files"][str(missing)]["result"]["error"].startswith("FileNotFoundError")


def test_dump_files_parser_error(tmp_path):
    """A parser exception is recorded, not raised."""
    empty = tmp_path / "empty.sv"
    empty.write_text("")
    dump = tool.dump_files([str(empty)])
    assert dump["files"][str(empty)]["result"] == {"error": "RuntimeError: No module found."}


def test_dump_files_wrong_tree(tmp_path):
    """Importing from a different tree fails loudly."""
    with pytest.raises(RuntimeError, match="expected below"):
        tool.dump_files([], expected_tree=tmp_path)


def test_out_inside_repo_refused(capsys):
    """Outputs inside the repository are refused with exit code 2."""
    code = tool.main(["--out", str(ROOT / "compare_out"), str(ROOT / "examples" / "sv" / "adder.sv")])
    assert code == 2
    assert "outside the repository" in capsys.readouterr().err
    assert not (ROOT / "compare_out").exists()


def test_main_usage_errors(capsys):
    """Missing input is a usage error."""
    assert tool.main(["/nonexistent/file.sv"]) == 2
    assert "error:" in capsys.readouterr().err


def _have_git() -> bool:
    if shutil.which("git") is None:
        return False
    proc = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--verify", "HEAD"], capture_output=True, check=False)
    return proc.returncode == 0


def _worktrees() -> str:
    return subprocess.run(
        ["git", "-C", str(ROOT), "worktree", "list", "--porcelain"], capture_output=True, text=True, check=True
    ).stdout


def test_integration_head_vs_working_tree(tmp_path, capsys):
    """End to end: working tree against HEAD, worktree is cleaned up, --out files are written."""
    if not _have_git():
        pytest.skip("not in a git repository or git not available")
    files = [str(ROOT / "examples" / "sv" / name) for name in ("adder.sv", "bcd_adder.sv")]
    before = _worktrees()

    code = tool.main(["--base", "HEAD", "--out", str(tmp_path / "out"), *files])

    text = capsys.readouterr().out
    assert code in (0, 1)
    assert "Summary: HEAD -> working tree, 2 files" in text
    assert "Parse time:" in text
    assert _worktrees() == before
    base = json.loads((tmp_path / "out" / "base.json").read_text())
    assert set(base["files"]) == set(files)
    assert (tmp_path / "out" / "head.json").is_file()
