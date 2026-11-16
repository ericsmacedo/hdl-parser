# MIT License
#
# Copyright (c) 2025-2026 ericsmacedo
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

"""Test Command Line Interface."""

import json
from pathlib import Path

from click.testing import CliRunner
from contextlib_chdir import chdir
from pytest import mark
from test2ref import assert_refdata, configure

from hdl_parser.cli import cli
from hdl_parser.project import SCHEMA_VERSION, Project

from .conftest import EXAMPLES_PATH, PRJ_PATH

configure(ignore_spaces=True)

# We are just testing a reduced set of examples here
EXAMPLES = (
    EXAMPLES_PATH / "sv" / "param_module.sv",
    EXAMPLES_PATH / "sv" / "adder.sv",
    EXAMPLES_PATH / "sv" / "bcd_adder.sv",
)
REPLACEMENTS = ((Path("examples"), "EXAMPLES"),)


@mark.parametrize("example", EXAMPLES)
def test_gen_sv_instance(tmp_path, runner, example):
    """Test Info Command."""
    result = runner.invoke(cli, ["gen-sv-instance", str(example)])

    assert result.exit_code == 0
    (tmp_path / "output.txt").write_text(result.output)

    assert_refdata(test_gen_sv_instance, tmp_path, flavor=example.name)


@mark.parametrize("example", EXAMPLES)
@mark.parametrize("pre", ((), ("--no-color",)))
@mark.parametrize("post", ((), ("--level=4", "-s")))
def test_info(tmp_path, example, pre, post):
    """Test Info Command."""
    runner = CliRunner()
    result = runner.invoke(cli, [*pre, "info", str(example.relative_to(PRJ_PATH)), *post])

    assert result.exit_code == 0
    (tmp_path / "output.md").write_text(result.output)

    posts = ",".join(post)
    assert_refdata(test_info, tmp_path, flavor=f"{example.name}-{posts}", replacements=REPLACEMENTS)


@mark.parametrize("example", EXAMPLES)
def test_json(tmp_path, runner, example):
    """Test json Command."""
    result = runner.invoke(cli, ["json", str(example)])

    assert result.exit_code == 0
    (tmp_path / "output.json").write_text(result.output)

    assert_refdata(test_json, tmp_path, flavor=example.name)


@mark.parametrize("cmd", ("info", "json"))
def test_multiple(tmp_path, runner, cmd):
    """Test Command - Multiple Files."""
    examples = (str(example.relative_to(Path.cwd())) for example in EXAMPLES)
    result = runner.invoke(cli, [cmd, *examples])

    assert result.exit_code == 0
    (tmp_path / "output.txt").write_text(result.output)

    assert_refdata(test_multiple, tmp_path, flavor=cmd, replacements=REPLACEMENTS)


@mark.parametrize("cmd", ("info", "json"))
def test_filelist(tmp_path, runner, cmd, examples):
    """Test Command - Multiple Files."""
    examples = examples.relative_to(Path.cwd())
    result = runner.invoke(cli, [cmd, "-f", str(examples / "sv" / "filelist.f")])

    assert result.exit_code == 0
    (tmp_path / "output.txt").write_text(result.output)

    assert_refdata(test_filelist, tmp_path, flavor=cmd, replacements=REPLACEMENTS)


def test_cli_help_smoke(runner):
    """Test that help command works."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_empty(tmp_path, runner):
    """Test Empty File Command."""
    with chdir(tmp_path):
        empty_file = Path("file.sv")
        empty_file.touch()

        # Run the command
        result = runner.invoke(cli, ["info", str(empty_file)])

        # there is nothing to show
        assert result.exit_code == 0
        assert result.output == ""


@mark.parametrize("cmd", ("json", "info", "gen-sv-instance", "project", "schema"))
def test_command_help(runner, cmd):
    """The Help Of A Command Is No Failure."""
    result = runner.invoke(cli, [cmd, "--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "Failed" not in result.output


def test_usage_error(runner):
    """Usage Errors Are Reported By Click."""
    result = runner.invoke(cli, ["json", "--unknown-option"])
    assert result.exit_code == 2
    assert "No such option" in result.output
    assert "Failed" not in result.output


def test_failure_reason(runner, examples, caplog, monkeypatch):
    """The Reason Of A Failure Is Reported."""

    def parse_file(*args, **kwargs):
        raise ValueError("something is wrong")

    monkeypatch.setattr("hdl_parser.cli.parse_file", parse_file)
    result = runner.invoke(cli, ["json", str(examples / "sv" / "adder.sv")])
    assert result.exit_code == 1
    assert "ValueError: something is wrong" in caplog.text


@mark.parametrize("cmd", ("json", "info", "gen-sv-instance"))
def test_no_module(runner, tmp_path, examples, cmd):
    """A File Without Modules Does Not Stop The Others."""
    package = tmp_path / "pkg.sv"
    package.write_text("package pkg;\n  typedef logic [3:0] t;\nendpackage\n")
    result = runner.invoke(cli, [cmd, str(package), str(examples / "sv" / "adder.sv")])
    assert result.exit_code == 0
    assert "adder" in result.output


def test_project(runner, examples):
    """All Files As One JSON Document."""
    sv_dir = examples / "sv"
    result = runner.invoke(cli, ["project", str(sv_dir / "adder.sv"), str(sv_dir / "bcd_adder.sv")])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert data["schema_version"] == SCHEMA_VERSION
    assert [file["path"] for file in data["files"]] == ["adder.sv", "bcd_adder.sv"]
    assert data["files"][0]["diagnostics"][0]["code"] == "undefined-module"
    assert data["files"][0]["modules"][0]["loc"]["line"] == 3


def test_project_dir(runner, examples):
    """A Directory, With Excluded Files."""
    result = runner.invoke(cli, ["project", str(examples / "sv"), "-x", "macros/*", "-x", "ifdef*"])
    assert result.exit_code == 0
    paths = [file["path"] for file in json.loads(result.stdout)["files"]]
    assert "adder.sv" in paths
    assert not any(path.startswith(("macros/", "ifdef")) for path in paths)


def test_project_filelist(runner, examples):
    """A Filelist, With Macros."""
    filelist = examples / "sv" / "filelist.f"
    result = runner.invoke(cli, ["project", "-f", str(filelist), "-e", "-D", "WIDTH=8", "-D", "SYNTHESIS"])
    assert result.exit_code == 0
    data = json.loads(result.stdout)
    assert "adder.sv" in [file["path"] for file in data["files"]]
    assert data["settings"]["defines"] == {"WIDTH": "8", "SYNTHESIS": ""}


def test_project_failure(runner, tmp_path, examples, monkeypatch):
    """A File Which Cannot Be Parsed Is Part Of The Document, With A Diagnostic."""
    from hdl_parser import project  # noqa: PLC0415

    bad = tmp_path / "bad.sv"
    bad.write_text("module bad; endmodule\n")
    parse_file = project.parse_file

    def failing(path, **kwargs):
        if path.name == "bad.sv":
            raise ValueError("something is wrong")
        return parse_file(path, **kwargs)

    monkeypatch.setattr(project, "parse_file", failing)
    result = runner.invoke(cli, ["project", "--root", str(tmp_path), str(bad), str(examples / "sv" / "adder.sv")])
    assert result.exit_code == 0
    files = json.loads(result.stdout)["files"]
    assert files[0]["diagnostics"][0]["code"] == "parse-failed"
    assert files[1]["modules"][0]["name"] == "adder"


@mark.parametrize(
    "args",
    (
        ("-f", "examples/sv/filelist.f", "examples/sv/adder.sv"),
        ("examples/sv", "examples/sv/adder.sv"),
        ("examples/sv/adder.sv", "-x", "*"),
        ("examples/sv", "--root", "examples"),
        ("examples/sv/adder.sv", "-r"),
        ("examples/sv/adder.sv", "-D", "=1"),
    ),
)
def test_project_usage(runner, args):
    """Options Which Do Not Fit Together."""
    with chdir(PRJ_PATH):
        result = runner.invoke(cli, ["project", *args])
    assert result.exit_code == 2
    assert "Failed" not in result.output


def test_schema(runner):
    """The Published JSON Schema Is Up To Date."""
    result = runner.invoke(cli, ["schema"])
    assert result.exit_code == 0
    assert json.loads(result.stdout) == Project.json_schema()
    published = PRJ_PATH / "docs" / "schema" / "project.schema.json"
    assert json.loads(published.read_text()) == Project.json_schema(), "run: hdl-parser schema > " + str(published)
