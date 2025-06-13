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

"""Test Fixtures."""

from pathlib import Path

from click.testing import CliRunner
from pytest import fixture

PRJ_PATH = Path(__file__).parent.parent
EXAMPLES_PATH = PRJ_PATH / "examples"
EXAMPLES = tuple(sorted(EXAMPLES_PATH.glob("*.sv")))


@fixture
def examples() -> Path:
    """Path to Examples."""
    return EXAMPLES_PATH


@fixture
def runner():
    """CLI Runner."""
    runner = CliRunner()
    with runner.isolated_filesystem():
        yield runner


@fixture(autouse=True)
def enforce_terminal_size(monkeypatch):
    """Fix issue with varying terminal size."""
    monkeypatch.setenv("SV_SIMPLEPARSER_WIDTH", "75")
