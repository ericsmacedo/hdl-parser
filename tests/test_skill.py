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

"""The Skill For AI Agents Covers Every Query, Argument And Diagnostic."""

from hdl_parser._diagnostics import SEVERITIES
from hdl_parser._mcp import TOOLS
from hdl_parser.cli import cli

from .conftest import PRJ_PATH

SKILL_PATH = PRJ_PATH / "skills" / "hdl-parser"


def test_frontmatter():
    """The Skill Has A Name And A Description."""
    text = (SKILL_PATH / "SKILL.md").read_text()
    head, sep, _ = text.removeprefix("---\n").partition("\n---\n")
    assert sep
    fields = dict(line.split(": ", 1) for line in head.splitlines())
    assert fields["name"] == "hdl-parser"
    assert 50 < len(fields["description"]) <= 1024


def test_reference():
    """Every MCP Tool, Argument And Diagnostic Code Is Described."""
    text = (SKILL_PATH / "reference.md").read_text()
    for tool in TOOLS:
        assert f"## `{tool['name']}`" in text
        for name in tool["inputSchema"]["properties"]:
            assert name == "detail" or f"| `{name}`" in text, (tool["name"], name)
    for code in SEVERITIES:
        assert f"`{code}`" in text, code


def test_skill():
    """Every Query Is Named In The Skill."""
    text = (SKILL_PATH / "SKILL.md").read_text()
    for tool in TOOLS:
        assert f"`{tool['name']}`" in text, tool["name"]
    commands = set(cli.commands) - {"json", "info", "gen-sv-instance", "schema", "project", "mcp"}
    for name in commands:
        assert f"{name} " in text or f"`{name}`" in text, name
