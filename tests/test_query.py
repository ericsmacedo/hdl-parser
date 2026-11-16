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


"""Test Queries."""

import json
import re
import shlex

from contextlib_chdir import chdir
from pytest import fixture, mark, raises

from hdl_parser import Project, query
from hdl_parser.cli import cli

from .conftest import PRJ_PATH

IBEX = PRJ_PATH / "tests" / "corpus" / "sv" / "ibex"


@fixture(scope="module")
def ibex() -> Project:
    """The ibex core."""
    return Project.from_filelist(IBEX / "ibex_core.f")


@fixture
def small(tmp_path) -> Project:
    """A small design: top with two instances of sub, an undefined module, a package."""
    (tmp_path / "top.sv").write_text(
        """\
module top #(parameter W = 8) (input logic clk_i, output logic [W-1:0] q_o);
  sub u_a (.clk_i(clk_i));
  sub u_b (.clk_i(clk_i));
  missing u_m ();
endmodule
"""
    )
    (tmp_path / "sub.sv").write_text("module sub (input logic clk_i);\n  leaf u_leaf ();\nendmodule\n")
    (tmp_path / "leaf.sv").write_text("module leaf; endmodule\n")
    (tmp_path / "pkg.sv").write_text("package pkg;\n  parameter int A = 1;\n  parameter int B = 2;\nendpackage\n")
    return Project.from_dir(tmp_path)


def test_module(small):
    """Everything Of A Module, With Full Identifiers."""
    answer = query.module(small, "top")
    result = answer["result"]
    assert answer["query"] == "module"
    assert result["id"] == "top.sv:top"
    assert result["kind"] == "module"
    assert result["file"] == "top.sv"
    assert result["loc"]["line"] == 1
    assert [port["id"] for port in result["ports"]] == ["top.sv:top.clk_i", "top.sv:top.q_o"]
    assert result["insts"][0]["connections"][0]["id"] == "top.sv:top.u_a.clk_i"
    assert "omitted" not in answer
    assert "others" not in answer


def test_module_summary(small):
    """Names And Counts Only."""
    result = query.module(small, "top", summary=True)["result"]
    assert result["counts"] == {"params": 1, "ports": 2, "insts": 3}
    assert "ports" not in result


def test_module_fields_limit(small):
    """Selected Fields, Limited Lists."""
    answer = query.module(small, "top", fields=["ports", "insts"], limit=1)
    assert set(answer["result"]) == {"id", "kind", "name", "ports", "insts"}
    assert len(answer["result"]["ports"]) == 1
    assert answer["omitted"] == {"ports": 1, "insts": 2}
    with raises(query.QueryError) as error:
        query.module(small, "top", fields=["prots"])
    assert error.value.code == "bad-argument"
    assert "ports" in error.value.suggestions


def test_module_package(small):
    """Packages, By Name And Full Identifier."""
    assert query.module(small, "pkg", summary=True)["result"]["counts"] == {"params": 2}
    assert query.module(small, "pkg.sv:pkg")["result"]["kind"] == "package"


def test_module_not_found(small):
    """Similar Names Are Suggested."""
    with raises(query.QueryError) as error:
        query.module(small, "tpo")
    assert error.value.code == "not-found"
    assert error.value.to_dict()["error"]["suggestions"] == ["top"]
    with raises(query.QueryError) as error:
        query.module(small, "top.sv:tpo")
    assert error.value.suggestions[0] == "top.sv:top"


def test_module_others(tmp_path):
    """Further Definitions Are Named."""
    (tmp_path / "a.sv").write_text("module m; endmodule\n")
    (tmp_path / "b.sv").write_text("module m; endmodule\n")
    answer = query.module(Project.from_dir(tmp_path), "m")
    assert answer["result"]["id"] == "a.sv:m"
    assert answer["others"] == ["b.sv:m"]


def test_hierarchy_tops(small):
    """Without Top: The Top Modules."""
    answer = query.hierarchy(small)
    assert [top["id"] for top in answer["result"]] == ["top.sv:top"]
    assert answer["total"] == 1


def test_hierarchy(small):
    """Instance Tree With Locations."""
    result = query.hierarchy(small, "top")["result"]
    assert result["definition"] == "top.sv:top"
    u_a, u_b, u_m = result["children"]
    assert u_a["inst"] == "top.sv:top.u_a"
    assert u_a["loc"]["line"] == 2
    assert u_a["children"][0]["name"] == "u_leaf"
    assert u_b["name"] == "u_b"
    assert "definition" not in u_m
    assert u_m["loc"]["line"] == 4


def test_hierarchy_limit(small):
    """Nodes Beyond The Limit Are Counted."""
    answer = query.hierarchy(small, "top", limit=2, summary=True)
    result = answer["result"]
    assert result == {
        "name": "top",
        "module": "top",
        "truncated": True,
        "children": [{"name": "u_a", "module": "sub", "children": [{"name": "u_leaf", "module": "leaf"}]}],
    }
    assert answer["omitted"] == 3


def test_hierarchy_depth_fields(small):
    """Depth And Fields."""
    result = query.hierarchy(small, "top", depth=0, fields=["module"])["result"]
    assert result == {"name": "top", "module": "top", "truncated": True}
    with raises(query.QueryError):
        query.hierarchy(small, "top", fields=["foo"])
    with raises(query.QueryError) as error:
        query.hierarchy(small, "nope")
    assert error.value.code == "not-found"


def test_where_used(small):
    """All Instances, With Location."""
    answer = query.where_used(small, "sub", limit=1)
    assert answer["module"] == "sub.sv:sub"
    assert answer["result"] == [
        {
            "inst": "top.sv:top.u_a",
            "module": "top.sv:top",
            "file": "top.sv",
            "loc": {"line": 2, "col": 3, "end_line": 2, "end_col": 27},
        }
    ]
    assert answer["total"] == 2
    assert answer["omitted"] == 1
    assert query.where_used(small, "top")["result"] == []
    with raises(query.QueryError):
        query.where_used(small, "nope")


def test_find(small):
    """Part Of Name, Wildcards, Kinds, Fields."""
    found = query.find(small, "CLK", kinds=["port"])["result"]
    assert [item["id"] for item in found] == ["sub.sv:sub.clk_i", "top.sv:top.clk_i"]
    assert found[0]["direction"] == "input"
    assert found[0]["loc"]["line"] == 1
    found = query.find(small, "top.sv:top.u_*", kinds=["instance"])["result"]
    assert [item["id"] for item in found] == ["top.sv:top.u_a", "top.sv:top.u_b", "top.sv:top.u_m"]
    assert found[0]["module"] == "sub"
    found = query.find(small, "u_?", fields=["module"])["result"]
    assert found[0] == {"id": "top.sv:top.u_a", "kind": "instance", "name": "u_a", "module": "sub"}
    with raises(query.QueryError) as error:
        query.find(small, "x", kinds=["prot"])
    assert error.value.code == "bad-argument"


def test_diagnostics(small):
    """Problems, Filtered."""
    answer = query.diagnostics(small)
    assert answer["result"] == [
        {
            "file": "top.sv",
            "code": "undefined-module",
            "severity": "warning",
            "message": "module 'missing' of instance 'u_m' is not defined in the project.",
            "loc": {"line": 4, "col": 3, "end_line": 4, "end_col": 18},
            "item": "top.sv:top.u_m",
        }
    ]
    assert answer["counts"] == {"error": 0, "warning": 1, "info": 0}
    assert query.diagnostics(small, severity="error")["result"] == []
    assert query.diagnostics(small, codes=["no-module"])["total"] == 0
    assert query.diagnostics(small, file="sub.sv")["total"] == 0
    with raises(query.QueryError):
        query.diagnostics(small, severity="fatal")
    with raises(query.QueryError) as error:
        query.diagnostics(small, file="sub.svh")
    assert error.value.suggestions == ("sub.sv",)


def test_diagnostics_included(tmp_path):
    """The Included File Is Named Separately, A Filelist Problem Has No Parsed File."""
    (tmp_path / "inc.svh").write_text("`define BAD(\n")
    (tmp_path / "top.sv").write_text('`include "inc.svh"\nmodule top; endmodule\n')
    (tmp_path / "top.f").write_text("top.sv\n-unknown\n")
    project = Project.from_filelist(tmp_path / "top.f", expand_macros=True)
    result = query.diagnostics(project)["result"]
    by_code = {entry["code"]: entry for entry in result}
    assert by_code["filelist-unknown"]["file"] == "top.f"
    assert by_code["macro-bad-define"]["file"] == "top.sv"
    assert by_code["macro-bad-define"]["included"] == "inc.svh"


@mark.parametrize("limit", (None, 0, 5))
def test_limit(ibex, limit):
    """The Default Limit, No Limit, A Given Limit."""
    answer = query.find(ibex, "*", limit=limit)
    total = answer["total"]
    expected = {None: query.DEFAULT_LIMIT, 0: total, 5: 5}[limit]
    assert len(answer["result"]) == expected
    assert answer.get("omitted", 0) == total - expected
    with raises(query.QueryError):
        query.find(ibex, "*", limit=-1)


def test_ibex(ibex):
    """A Real Design."""
    assert query.where_used(ibex, "ibex_alu")["result"][0]["inst"] == "ibex_ex_block.sv:ibex_ex_block.alu_i"
    answer = query.hierarchy(ibex, "ibex_core", depth=1, summary=True)
    assert "omitted" not in answer
    assert all(set(child) <= {"name", "module", "truncated"} for child in answer["result"]["children"])


def test_vhdl_bodies(tmp_path):
    """VHDL Architectures In Other Files."""
    (tmp_path / "e.vhd").write_text("entity e is\n  port (a : in bit);\nend entity;\n")
    (tmp_path / "a.vhd").write_text("architecture rtl of e is\nbegin\nend architecture;\n")
    result = query.module(Project.from_dir(tmp_path), "e")["result"]
    assert result["id"] == "e.vhd:e"
    assert result["bodies"] == ["a.vhd:e"]


_EXAMPLE = re.compile(r"```bash\nhdl-parser (?P<cmd>[^\n]+)\n```\n\n```json\n(?P<answer>.*?)\n```", re.DOTALL)


def test_guide(runner):
    """The Worked Examples Of The Guide For Agents Are Up To Date."""
    text = (PRJ_PATH / "docs" / "agents.md").read_text()
    examples = list(_EXAMPLE.finditer(text))
    assert len(examples) == 8
    with chdir(IBEX):
        for example in examples:
            result = runner.invoke(cli, shlex.split(example["cmd"]))
            assert json.loads(result.stdout) == json.loads(example["answer"]), example["cmd"]


def test_hierarchy_tops_sorted(tmp_path):
    """Tops By Size, Leaves Left Out, Text Tree, Negative Depth."""
    (tmp_path / "a.sv").write_text("module inv; endmodule\n")
    (tmp_path / "b.sv").write_text("module mid; inv u (); endmodule\n")
    (tmp_path / "c.sv").write_text("module big; mid u1 (); mid u2 (); endmodule\n")
    (tmp_path / "d.sv").write_text("module lonely; endmodule\n")
    project = Project.from_dir(tmp_path)
    answer = query.hierarchy(project)
    assert [(top["name"], top["insts"]) for top in answer["result"]] == [("big", 4)]
    assert answer["leaves"] == 1
    assert [top["name"] for top in query.hierarchy(project, leaves=True)["result"]] == ["big", "lonely"]
    assert (
        query.hierarchy(project, "big", text=True)["tree"]
        == "big\n  u1 (small)\n    u (inv)\n  u2 (small)\n    u (inv)"
    )
    with raises(query.QueryError):
        query.hierarchy(project, "big", depth=-1)


def test_where_used_undefined(small):
    """Modules Which Are Not Defined Are Found By Their Instances."""
    answer = query.where_used(small, "missing")
    assert answer["defined"] is False
    assert answer["result"][0]["inst"] == "top.sv:top.u_m"
    assert answer["result"][0]["module"] == "top.sv:top"


def test_diagnostics_group_exclude_blackbox(small):
    """Grouped, Files Excluded, Blackboxes."""
    assert query.diagnostics(small, group_by="code")["result"] == [{"code": "undefined-module", "count": 1}]
    assert query.diagnostics(small, group_by="module")["result"] == [{"module": "missing", "count": 1}]
    assert query.diagnostics(small, exclude=["top.*"])["total"] == 0
    assert query.diagnostics(small, file="t*")["total"] == 1
    assert query.diagnostics(small, blackboxes=["miss*"])["total"] == 0
    with raises(query.QueryError):
        query.diagnostics(small, group_by="foo")


def test_module_bad_field_suggestions(small):
    """Suggestions Without Duplicates."""
    with raises(query.QueryError) as error:
        query.module(small, "top", fields=["nope"])
    assert len(error.value.suggestions) == len(set(error.value.suggestions))
