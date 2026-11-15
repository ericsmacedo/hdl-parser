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

"""Functions And Tasks."""

import re

from pytest import mark

from hdl_parser import Function, Port, parse_file, parse_text

from .conftest import PRJ_PATH, plain

CORPUS = tuple(sorted((PRJ_PATH / "tests" / "corpus" / "sv").glob("*/*.sv")))

TEXT = """\
package p;
  // Number of bits
  function automatic int unsigned bits(input int unsigned value, int base = 2);
    for (int i = 0; i < 2; i++) begin end
    return 1;
  endfunction : bits

  function logic [7:0] swap(logic [7:0] data, output logic ok, ref my_t r, const ref int c[4]);
  endfunction
  function void nothing();
  endfunction
  function implicit;
    input [3:0] a, b;
    input c;
    implicit = a;
  endfunction
  function pkg::t user(other_t x);
  endfunction
  task automatic wait_clks(int n = 1, output bit done);
    repeat (n) @(posedge clk);
  endtask
  task plain;
  endtask
  import "DPI-C" function int dpi(input int a);
  class c;
    function void method(); endfunction
  endclass
  function int after();
  endfunction
endpackage
"""


def _args(function) -> list[str]:
    return [
        " ".join(filter(None, (arg.direction, arg.ptype, arg.dtype, arg.dim, arg.name, arg.dim_unpacked, arg.default)))
        for arg in function.args
    ]


def test_functions():
    """Signatures Of Functions And Tasks."""
    functions = parse_text(TEXT).packages[0].functions
    assert [
        (function.kind, function.name, function.rtype, function.dim, _args(function)) for function in functions
    ] == [
        ("function", "bits", "int unsigned", "", ["input int unsigned value", "input int base 2"]),
        (
            "function",
            "swap",
            "logic",
            "[7:0]",
            ["input logic [7:0] data", "output logic ok", "ref my_t r", "ref int c [4]"],
        ),
        ("function", "nothing", "void", "", []),
        ("function", "implicit", "", "", ["input [3:0] a", "input [3:0] b", "input c"]),
        ("function", "user", "pkg::t", "", ["input other_t x"]),
        ("task", "wait_clks", "", "", ["input int n 1", "output bit done"]),
        ("task", "plain", "", "", []),
        # the methods of classes and DPI imports are no functions of the package
        ("function", "after", "int", "", []),
    ]
    assert functions[0].comment == ("Number of bits",)


def test_model():
    """Identifiers, Locations And Output."""
    file = parse_text(TEXT)
    assert file.diagnostics == ()
    bits = file.find("p.bits")
    assert plain(bits) == Function(
        name="bits",
        kind="function",
        rtype="int unsigned",
        args=(
            Port(direction="input", ptype="int", dtype="unsigned", name="value"),
            Port(direction="input", ptype="int", name="base", default="2"),
        ),
        comment=("Number of bits",),
    )
    assert (bits.loc.line, bits.loc.end_line) == (3, 6)
    assert file.find("p.bits.base") is bits.args[1]
    assert bits.args[1].loc.line == 3
    assert '"functions"' in file.overview


def test_module_and_interface():
    """Functions And Tasks Within Modules And Interfaces."""
    text = """\
interface i (input logic clk);
  task automatic send(input logic [7:0] data);
  endtask
endinterface
module top (input logic a = 1'b0);
  function automatic logic f(logic x);
    return x;
  endfunction
  if (A) begin : g_a
    function logic g(); endfunction
  end
  sub u0 ();
endmodule
"""
    file = parse_text(text)
    assert [item.id for item in file.iter_items()] == [
        "i",
        "i.clk",
        "i.send",
        "i.send.data",
        "top",
        "top.a",
        "top.f",
        "top.f.x",
        "top.g",
        "top.u0",
    ]
    # defaults of ports are known too
    assert file.modules[0].ports[0].default == "1'b0"


def test_out_of_class_method():
    """Method Defined Outside Of Its Class."""
    file = parse_text("package p;\n  function int cls::method(int a);\n  endfunction\nendpackage\n")
    assert [function.name for function in file.packages[0].functions] == ["method"]


def test_broken():
    """Missing `endfunction`, Missing Name, Unclosed Arguments."""
    text = "package p;\n  function;\n  endfunction\n  function int f(int a;\nendpackage\nmodule top; endmodule\n"
    file = parse_text(text)
    assert [function.name for function in file.packages[0].functions] == ["f"]
    assert [diag.code for diag in file.diagnostics] == ["unbalanced-bracket"]
    assert [module.name for module in file.modules] == ["top"]


@mark.parametrize("path", CORPUS, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_corpus(path):
    """All Functions And Tasks Of Real Code Are Found, With Their Arguments."""
    text = path.read_text()
    file = parse_file(path)
    functions = [func for unit in (*file.packages, *file.interfaces, *file.modules) for func in unit.functions]
    # macro definitions are no functions
    code = re.sub(r"^`define.*?[^\\]$", "", text, flags=re.MULTILINE | re.DOTALL)
    expected = re.findall(r"^\s*(?:function|task)\b[^;(]*?(\w+)\s*[;(]", code, re.MULTILINE)
    assert [function.name for function in functions] == expected
    for function in functions:
        lines = text.split("\n")[function.loc.line - 1 : function.loc.end_line]
        assert lines[0].lstrip().startswith(function.kind)
        assert lines[-1].lstrip().startswith(f"end{function.kind}")
        assert function.name in "\n".join(lines)
        for arg in function.args:
            assert arg.direction in ("input", "output", "inout", "ref")
            assert re.search(rf"\b{re.escape(arg.name)}\b", text)


def test_corpus_has_functions():
    """The Corpus Covers Functions And Tasks."""
    files = [parse_file(path) for path in CORPUS]
    functions = [
        func for file in files for unit in (*file.packages, *file.interfaces, *file.modules) for func in unit.functions
    ]
    assert sum(function.kind == "function" for function in functions) >= 60
    assert sum(function.kind == "task" for function in functions) >= 10
    assert sum(len(function.args) for function in functions) >= 130
    assert sum(bool(function.rtype) for function in functions) >= 50
