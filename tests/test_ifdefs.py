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
"""Test Resolution Of `ifdef Conditions."""

from functools import partial

from pytest import mark, raises

import hdl_parser
from hdl_parser import Macro, MacroCall, parse_defines, parse_defines_text
from hdl_parser._sv.preproc import expand
from hdl_parser.cli import cli

parse_file = partial(hdl_parser.parse_file, expand_macros=True, resolve_ifdefs=True)
parse_text = partial(hdl_parser.parse_text, expand_macros=True, resolve_ifdefs=True)
resolve = partial(expand, resolve_ifdefs=True)


def _lines(text, **kwargs):
    """Resolve `text` and return all lines, which are not empty and no `define."""
    lines = (line.strip() for line in resolve(text, **kwargs).splitlines())
    return [line for line in lines if line and not line.startswith("`define")]


def _ports(text, **kwargs):
    """Parse `text` and return name and conditions of the ports of the first module."""
    return [(port.name, port.ifdefs) for port in parse_text(text, **kwargs).modules[0].ports]


BUS = """
`ifdef USE_AXI
    `define BUS_PORTS input awvalid, output awready
`else
    `define BUS_PORTS input psel, output pready
`endif
module m (`BUS_PORTS, input clk);
endmodule
"""


def test_select_macro():
    """A Define Selects The Definition Of Another Macro."""
    # known to be defined
    assert _ports("`define USE_AXI\n" + BUS) == [("awvalid", ()), ("awready", ()), ("clk", ())]
    # not known. this does not mean it is not defined.
    module = parse_text(BUS).modules[0]
    assert [port.name for port in module.ports] == ["clk"]
    assert module.unresolved_macros == (MacroCall(name="BUS_PORTS"),)
    # handed over. these macros are never touched
    macros = parse_defines_text("`define USE_AXI")
    assert _ports("`undef USE_AXI\n" + BUS, macros=macros) == [("awvalid", ()), ("awready", ()), ("clk", ())]
    # off by default
    module = hdl_parser.parse_text("`define USE_AXI\n" + BUS, expand_macros=True).modules[0]
    assert module.unresolved_macros == (MacroCall(name="BUS_PORTS"),)


def test_ports():
    """Conditions Around Ports."""
    text = """
`define A
module m (
`ifdef A
    input a,
`else
    input not_a,
`endif
`ifndef A
    input not_a2,
`else
    input a2,
`endif
`ifdef B
    input b,
`else
    input not_b,
`endif
    input z
);
endmodule
"""
    assert _ports(text) == [("a", ()), ("a2", ()), ("b", ("B",)), ("not_b", ("!B",)), ("z", ())]
    # off by default
    assert [port.name for port in hdl_parser.parse_text(text, expand_macros=True).modules[0].ports] == [
        "a",
        "not_a",
        "not_a2",
        "a2",
        "b",
        "not_b",
        "z",
    ]


@mark.parametrize(
    "text, lines",
    (
        # known
        ("`ifdef A\n1\n`elsif B\n2\n`else\n3\n`endif", ["1"]),
        ("`ifndef A\n1\n`elsif A\n2\n`else\n3\n`endif", ["2"]),
        ("`ifndef A\n1\n`else\n3\n`endif", ["3"]),
        # unknown
        ("`ifdef U\n1\n`elsif V\n2\n`else\n3\n`endif", ["`ifdef U", "1", "`elsif V", "2", "`else", "3", "`endif"]),
        ("`ifndef U\n1\n`else\n3\n`endif", ["`ifndef U", "1", "`else", "3", "`endif"]),
        # unknown, then known: the remaining branches are never compiled
        ("`ifdef U\n1\n`elsif A\n2\n`elsif V\n3\n`else\n4\n`endif", ["`ifdef U", "1", "`else", "2", "`endif"]),
        # known to be false, then unknown
        ("`ifndef A\n1\n`elsif U\n2\n`else\n3\n`endif", ["`ifdef U", "2", "`else", "3", "`endif"]),
        ("`ifndef A\n1\n`elsif U\n2\n`elsif V\n3\n`endif", ["`ifdef U", "2", "`elsif V", "3", "`endif"]),
        # nested
        ("`ifdef A\n`ifdef U\n1\n`else\n2\n`endif\n`else\n3\n`endif", ["`ifdef U", "1", "`else", "2", "`endif"]),
        ("`ifndef A\n`ifdef U\n1\n`elsif A\n2\n`endif\n`else\n3\n`endif", ["3"]),
        ("`ifdef U\n`ifdef A\n1\n`else\n2\n`endif\n`endif", ["`ifdef U", "1", "`endif"]),
        # broken code is kept
        (
            "`else\n1\n`elsif A\n2\n`endif\n`ifdef\n3\n`endif",
            ["`else", "1", "`elsif A", "2", "`endif", "`ifdef", "3", "`endif"],
        ),
        # comments and strings
        ('// `ifndef A\n"`ifndef A"\n1', ["// `ifndef A", '"`ifndef A"', "1"]),
    ),
)
def test_branches(text, lines):
    """All Kinds Of Branches. `A Is Defined, `U and `V Are Unknown."""
    assert _lines("`define A\n" + text) == lines
    # without resolution, the text is not touched
    assert expand(text) == text


def test_not_compiled():
    """Code Which Is Not Compiled Is Ignored."""
    text = """
`define A
`define W 8
`ifndef A
    `define W 16
    `undef A
    `include "missing.svh"
    `UNKNOWN(
`endif
`ifdef A
`W
`endif
"""
    assert _lines(text) == ["8"]


def test_conditional():
    """Macros Defined Under Unknown Conditions Are Expanded, But Not Known To Be Defined."""
    text = """
`ifdef U
    `define C input c
`endif
`define D
`ifdef V
    `undef D
`endif
module m (
    `C,
`ifdef C
    input with_c,
`endif
`ifdef D
    input with_d,
`endif
    input z
);
endmodule
"""
    assert _ports(text) == [("c", ()), ("with_c", ("C",)), ("with_d", ("D",)), ("z", ())]

    macros = parse_defines_text("`ifdef U\n`define C\n`endif\n`define D\n", resolve_ifdefs=True)
    assert [(macro.name, macro.conditional) for macro in macros.values()] == [("C", True), ("D", False)]
    assert macros["C"] == Macro(name="C", body="")
    assert _lines("`ifdef C\n1\n`endif\n`ifdef D\n2\n`endif", macros=macros) == ["`ifdef C", "1", "`endif", "2"]


def test_conditional_conflict():
    """A Definition Under An Unknown Condition Conflicts With The One Before."""
    text = "`define W 8\n`ifdef U\n`define W 8\n`define X 1\n`endif\n`ifdef V\n`define W 16\n`define X 1\n`endif\n"
    macros = parse_defines_text(text + "`ifdef W\n`define W_IS_DEFINED\n`endif\n", resolve_ifdefs=True)
    assert [(macro.name, macro.conditional) for macro in macros.values()] == [("X", True), ("W_IS_DEFINED", True)]
    # a definition which is compiled for sure, ends the conflict
    assert tuple(parse_defines_text(text + "`define W 32\n", resolve_ifdefs=True)) == ("X", "W")
    assert tuple(parse_defines_text(text + "`undef W\n`undef X\n", resolve_ifdefs=True)) == ()


def test_guard(tmp_path):
    """Include Guards And Defaults Are Assumed To Be Compiled."""
    (tmp_path / "inc.svh").write_text(
        "`ifndef INC_SVH // guard\n"
        "/* guard */ `define INC_SVH\n"
        "`define USE_AXI\n"
        "`ifndef WIDTH\n`define WIDTH 8\n`else\n`define NO_DEFAULT\n`endif\n"
        "`ifndef OTHER\n`define NO_GUARD\n`endif\n"
        "`endif\n"
    )
    macros = parse_defines(tmp_path / "inc.svh", resolve_ifdefs=True)
    assert [(macro.name, macro.conditional) for macro in macros.values()] == [
        ("INC_SVH", False),
        ("USE_AXI", False),
        ("WIDTH", False),
        ("NO_DEFAULT", True),
        ("NO_GUARD", True),
    ]

    top = tmp_path / "top.sv"
    top.write_text(
        '`include "inc.svh"\n`define WIDTH 16\n`include "inc.svh"\n' + BUS.replace("clk", "[`WIDTH-1:0] clk")
    )
    module = parse_file(top).modules[0]
    assert [(port.name, port.dim) for port in module.ports] == [("awvalid", ""), ("awready", ""), ("clk", "[16-1:0]")]
    # the default is not used, if the macro is defined already
    module = parse_file(top, macros=parse_defines_text("`define WIDTH 4")).modules[0]
    assert module.ports[-1].dim == "[4-1:0]"
    # the directives of the guard are kept
    text = "`ifndef M_SV\n`define M_SV\nmodule m (input a);\nendmodule\n`endif\n"
    assert parse_text(text).modules[0].ifdefs == ("!M_SV",)


def test_include(tmp_path):
    """Included Files Are Processed At Their Position And Do Not Harm The Conditions Of The Including File."""
    (tmp_path / "a.svh").write_text("`ifdef BEFORE\n`define A input a\n`endif\n`ifdef U\n`ifdef V\n")
    top = tmp_path / "top.sv"
    top.write_text(
        '`define BEFORE\n`include "a.svh"\n`define AFTER\n'
        '`ifndef BEFORE\n`include "missing.svh"\n`endif\n'
        '`ifdef U\n`include "b.svh"\n`endif\n`include "b.svh"\n'
        "module m (`A, `B, input z);\nendmodule\n"
    )
    (tmp_path / "b.svh").write_text("`define B input b\n")
    module = parse_file(top).modules[0]
    assert [(port.name, port.ifdefs) for port in module.ports] == [("a", ()), ("b", ()), ("z", ())]
    assert tuple(parse_defines(top, resolve_ifdefs=True)) == ("BEFORE", "A", "AFTER", "B")


def test_macro_body():
    """Conditions And Defines Within Macros Are Handled At The Place Of Use."""
    text = """
`define PORTS \\
    input a, \\
`ifdef WITH_B \\
    input b, \\
`endif \\
`ifdef WITH_C \\
    input c, \\
`endif \\
    input z
`define ENABLE(name) `define WITH_``name
`define OPEN `ifdef WITH_B
module m (`PORTS);
endmodule
`ENABLE(B)
module n (
    `PORTS,
    `OPEN
        input in_b,
    `else
        input not_in_b,
    `endif
    input y
);
endmodule
"""
    modules = parse_text(text).modules
    assert [(port.name, port.ifdefs) for port in modules[0].ports] == [
        ("a", ()),
        ("b", ("WITH_B",)),
        ("c", ("WITH_C",)),
        ("z", ()),
    ]
    assert [(port.name, port.ifdefs) for port in modules[1].ports] == [
        ("a", ()),
        ("b", ()),
        ("c", ("WITH_C",)),
        ("z", ()),
        ("in_b", ()),
        ("y", ()),
    ]


def test_module():
    """Conditions Around Modules And Within The Body."""
    text = """
`define SYNTHESIS
`ifndef SYNTHESIS
module tb;
endmodule
`endif
module m (input a);
`ifdef SYNTHESIS
    ram u_ram (.a(a));
`else
    ram_model u_ram (.a(a));
`endif
`ifdef DEBUG
    dbg u_dbg (.a(a));
`endif
endmodule
"""
    modules = parse_text(text).modules
    assert [module.name for module in modules] == ["m"]
    assert [(inst.module, inst.ifdefs) for inst in modules[0].insts] == [("ram", ()), ("dbg", ("DEBUG",))]


def test_requires_expand_macros():
    """Conditions Are Resolved By The Macro Expansion."""
    with raises(ValueError, match="'resolve_ifdefs' requires 'expand_macros=True'"):
        hdl_parser.parse_text("module m; endmodule", resolve_ifdefs=True)


@mark.parametrize("cmd", ("json", "info", "gen-sv-instance"))
def test_cli(runner, tmp_path, cmd):
    """Command Line Option --resolve-ifdefs."""
    top = tmp_path / "top.sv"
    top.write_text("`define USE_AXI\n" + BUS)
    macro_file = tmp_path / "macros.svh"
    macro_file.write_text("`define USE_AXI\n" + BUS.partition("module")[0])
    plain = tmp_path / "plain.sv"
    plain.write_text("module m (`BUS_PORTS, input clk);\nendmodule\n")

    result = runner.invoke(cli, [cmd, "--expand-macros", str(top)])
    assert result.exit_code == 0
    assert "awvalid" not in result.output

    for args in (
        ("--resolve-ifdefs", str(top)),
        ("-r", "--macro-file", str(macro_file), str(plain)),
    ):
        result = runner.invoke(cli, [cmd, "--expand-macros", *args])
        assert result.exit_code == 0
        assert "awvalid" in result.output
        assert "psel" not in result.output
        assert "clk" in result.output

    result = runner.invoke(cli, [cmd, "--resolve-ifdefs", str(top)])
    assert result.exit_code == 2
    assert "'--resolve-ifdefs' requires '--expand-macros'" in result.output
