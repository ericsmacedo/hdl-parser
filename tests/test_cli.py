# MIT License
#
# Copyright (c) 2025 ericsmacedo
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

from pathlib import Path

from click.testing import CliRunner
from pytest import mark
from test2ref import assert_refdata, configure

from sv_simpleparser.cli import cli

from .conftest import EXAMPLES_PATH, PRJ_PATH

configure(ignore_spaces=True)

# We are just testing a reduced set of examples here
EXAMPLES = (
    EXAMPLES_PATH / "param_module.sv",
    EXAMPLES_PATH / "adder.sv",
    EXAMPLES_PATH / "bcd_adder.sv",
)


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
    assert_refdata(
        test_info, tmp_path, flavor=f"{example.name}-{posts}", replacements=((Path("examples"), "EXAMPLES"),)
    )


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
    examples = (str(example) for example in EXAMPLES)
    result = runner.invoke(cli, [cmd, *examples])

    assert result.exit_code == 0
    (tmp_path / "output.txt").write_text(result.output)

    assert_refdata(test_multiple, tmp_path, flavor=cmd)


@mark.parametrize("cmd", ("info", "json"))
def test_filelist(tmp_path, runner, cmd, examples):
    """Test Command - Multiple Files."""
    result = runner.invoke(cli, [cmd, "-f", str(examples / "filelist.f")])

    assert result.exit_code == 0
    (tmp_path / "output.txt").write_text(result.output)

    assert_refdata(test_filelist, tmp_path, flavor=cmd)


def test_cli_help_smoke(runner):
    """Test that help command works."""
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "Usage:" in result.output


def test_empty(runner):
    """Test Empty File Command."""
    empty_file = Path("file.sv")
    empty_file.touch()

    # Run the command
    result = runner.invoke(cli, ["info", str(empty_file)])

    assert result.exit_code == 1
