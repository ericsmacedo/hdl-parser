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

"""Project Configuration File."""

import json
from pathlib import Path

from contextlib_chdir import chdir
from pytest import fixture, mark, raises

from hdl_parser._config import ConfigError, find_config, read_config
from hdl_parser.cli import cli

TOP = """\
module top (input a, output y);
`ifdef FAST
  assign y = a;
`else
  assign y = ~a;
`endif
`ifdef NEVER
  sub u_sub ();
`endif
endmodule
"""

CONFIG = """\
filelist = "list.f"
expand_macros = true
resolve_ifdefs = true
closed_world = true
defines = { FAST = "" }
"""


@fixture
def design(tmp_path) -> Path:
    """Design with filelist and configuration file."""
    (tmp_path / "rtl").mkdir()
    (tmp_path / "rtl" / "top.sv").write_text(TOP)
    (tmp_path / "rtl" / "other.sv").write_text("module other; endmodule\n")
    (tmp_path / "list.f").write_text("rtl/top.sv\n")
    (tmp_path / "hdl-parser.toml").write_text(CONFIG)
    (tmp_path / "sub").mkdir()
    return tmp_path


def _assigns(output: str) -> list[int]:
    """Lines of the assignments: a list of objects, or a table."""
    assigns = json.loads(output)["result"].get("assigns", [])
    if isinstance(assigns, dict):
        idx = assigns["columns"].index("line")
        return [row[idx] for row in assigns["rows"]]
    return [assign["line"] for assign in assigns]


def _insts(output: str) -> list:
    return json.loads(output)["result"].get("insts", [])


def test_find(design):
    """The File Is Searched In The Directory And Its Parents."""
    assert find_config(design / "sub") == design / "hdl-parser.toml"
    assert find_config(design) == design / "hdl-parser.toml"
    (design / "hdl-parser.toml").unlink()
    found = find_config(design / "sub")
    assert found is None or design not in found.parents


def test_read(tmp_path, tmp_path_factory):
    """Values By Command Line Parameter, Paths Relative To The File."""
    path = tmp_path / "hdl-parser.toml"
    absolute = tmp_path_factory.mktemp("abs")
    path.write_text(
        f'paths = ["rtl"]\nexclude = "models/*"\ninc_dirs = ["inc", "{absolute.as_posix()}"]\ncache_dir = "~/cache"\n'
        "jobs = 4\n"
        'cache = true\ndefines = { A = "", W = 8 }\nblackbox = ["*_cell_*"]\npassthrough = "buf"\n'
        'exclude_problems = ["lib/*"]\nroot = "."\n'
    )
    assert read_config(path) == {
        "paths": (tmp_path / "rtl",),
        "exclude": ("models/*",),
        "inc_dirs": (tmp_path / "inc", absolute),
        "cache_dir": Path("~/cache").expanduser(),
        "jobs": 4,
        "cache": True,
        "defines": ("A=", "W=8"),
        "blackboxes": ("*_cell_*",),
        "passthrough": ("buf",),
        "excludes": ("lib/*",),
        "root": tmp_path,
    }


@mark.parametrize(
    "text, message",
    (
        ("unknown = 1", "unknown key 'unknown'. Known: filelist, "),
        ("jobs = true", "'jobs' must be an integer."),
        ("cache = 1", "'cache' must be true or false."),
        ("paths = 1", "'paths' must be a string or a list of strings."),
        ("filelist = 1", "'filelist' must be a string."),
        ('defines = "A"', "'defines' must be a table"),
        ("defines = { A = true }", "'defines' must be a string or an integer as value of 'A'."),
        ('filelist = "a.f"\npaths = ["rtl"]', "give either 'filelist' or 'paths'."),
        ("filelist = ", "Invalid value"),
    ),
)
def test_read_invalid(tmp_path, text, message):
    """Invalid Files Are Reported."""
    path = tmp_path / "hdl-parser.toml"
    path.write_text(text)
    with raises(ConfigError) as exc:
        read_config(path)
    assert message in str(exc.value)
    assert str(path) in str(exc.value)


def test_cli(runner, design):
    """The Options Of The File Are Used, Wherever The Command Is Started Below It."""
    with chdir(design / "sub"):
        result = runner.invoke(cli, ["module", "top"])
    assert result.exit_code == 0, result.output
    # FAST defined, NEVER undefined (closed world)
    assert _assigns(result.output) == [3]
    assert _insts(result.output) == []


def test_cli_override(runner, design):
    """The Command Line Takes Precedence."""
    with chdir(design):
        # replaces the defines: FAST is undefined now
        result = runner.invoke(cli, ["module", "top", "-D", "OTHER"])
        assert result.exit_code == 0, result.output
        assert _assigns(result.output) == [5]
        # replaces the filelist (and is not reported as conflict)
        result = runner.invoke(cli, ["module", "other", "rtl/other.sv"])
        assert result.exit_code == 0, result.output
        result = runner.invoke(cli, ["module", "top", "rtl/other.sv"])
        assert result.exit_code == 3
        # ignored
        result = runner.invoke(cli, ["--no-config", "module", "top", "rtl/top.sv"])
        assert result.exit_code == 0, result.output
        assert _assigns(result.output) == [3, 5]


def test_cli_explicit(runner, design, tmp_path_factory):
    """A File Given By '--config'."""
    elsewhere = tmp_path_factory.mktemp("elsewhere")
    with chdir(elsewhere):
        result = runner.invoke(cli, ["module", "top"])
        assert result.exit_code != 0
        result = runner.invoke(cli, ["--config", str(design / "hdl-parser.toml"), "module", "top"])
        assert result.exit_code == 0, result.output
        assert _assigns(result.output) == [3]


def test_cli_invalid(runner, design):
    """An Invalid File Is A Usage Error."""
    (design / "hdl-parser.toml").write_text("jobs = 0.5\n")
    with chdir(design):
        result = runner.invoke(cli, ["module", "top"])
    assert result.exit_code == 2
    assert "'jobs' must be an integer." in result.output


def test_cli_parse_commands(runner, design):
    """Commands Parsing Single Files Do Not Use The File."""
    with chdir(design):
        result = runner.invoke(cli, ["json", "rtl/top.sv"])
    assert result.exit_code == 0, result.output
    assert '"FAST"' in result.output
