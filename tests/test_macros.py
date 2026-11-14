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
"""Test Macro Expansion."""

import logging

from pytest import mark

from hdl_parser import Macro, MacroCall, Port, parse_defines, parse_defines_text, parse_file, parse_text
from hdl_parser._sv.preproc import expand
from hdl_parser.cli import cli

from .conftest import EXAMPLES_PATH

MACROS_SVH = EXAMPLES_PATH / "sv" / "macros.svh"
MACRO_PORTS_SV = EXAMPLES_PATH / "sv" / "macro_ports.sv"


def _ports(text, **kwargs):
    """Parse `text` and return port overview of first module."""
    module = parse_text(text, **kwargs).modules[0]
    return [" ".join(filter(None, (port.direction, port.ptype, port.dim, port.name))) for port in module.ports]


# ---------------------------------------------------------------------------------------------------------------------
# `define collection
# ---------------------------------------------------------------------------------------------------------------------


def test_define_object_like():
    """Macro Without Arguments."""
    macros = parse_defines_text("`define WIDTH 8\n`define EMPTY\n`define EXPR (WIDTH + 1) // comment\n")
    assert macros == {
        "WIDTH": Macro(name="WIDTH", body="8"),
        "EMPTY": Macro(name="EMPTY", body=""),
        # the parenthesis is not directly behind the name, so these are no arguments
        "EXPR": Macro(name="EXPR", body="(WIDTH + 1)"),
    }


def test_define_function_like():
    """Macro With Arguments."""
    macros = parse_defines_text('`define PORT(name, width=8, msg="a,b") input [width-1:0] name\n`define NOARGS() x\n')
    assert macros == {
        "PORT": Macro(
            name="PORT", body="input [width-1:0] name", params=(("name", None), ("width", "8"), ("msg", '"a,b"'))
        ),
        "NOARGS": Macro(name="NOARGS", body="x", params=()),
    }


def test_define_multiline():
    """Line Continuation And Comments."""
    macros = parse_defines_text(
        "`define PORTS \\\n"
        "    input  a, // line comment \\\n"
        "    output b  /* block comment */\n"
        "wire not_part_of_macro;\n"
    )
    assert macros["PORTS"].body == "input  a, \n    output b  /* block comment */"


def test_define_in_comment_or_string():
    """Defines Within Comments Or Strings Are No Defines."""
    macros = parse_defines_text(
        '// `define A 1\n/*\n`define B 2\n*/\ninitial $display("`define C 3");\n`define D "//"\n'
    )
    assert macros == {"D": Macro(name="D", body='"//"')}


def test_define_conflict(caplog):
    """Macros With Conflicting Definitions Are Skipped."""
    text = (
        "`ifdef FPGA\n`define W 8\n`else\n`define W 16\n`endif\n`define W 32\n`define SAME 1\n`define SAME 1 // again\n"
    )
    macros = parse_defines_text(text)
    assert macros == {"SAME": Macro(name="SAME", body="1")}
    assert "macro `W has conflicting definitions" in caplog.text


def test_define_broken(caplog):
    """Defines Which Cannot Be Parsed Are Skipped."""
    assert parse_defines_text("`define A(x y\n`define B(1) y\n`define C 1\n") == {"C": Macro(name="C", body="1")}
    assert "cannot parse definition of macro `A" in caplog.text
    assert "cannot parse definition of macro `B" in caplog.text


def test_parse_defines(tmp_path):
    """Read Defines From Multiple Files."""
    one = tmp_path / "one.svh"
    one.write_text("`define ONE 1")
    two = tmp_path / "two.svh"
    two.write_text("`define TWO 2\n")
    assert parse_defines() == {}
    assert parse_defines(one, str(two)) == {"ONE": Macro(name="ONE", body="1"), "TWO": Macro(name="TWO", body="2")}


def test_parse_defines_example():
    """Include Guard Does Not Harm."""
    macros = parse_defines(MACROS_SVH)
    assert tuple(macros) == ("MACROS_SVH", "CLK_RST_PORTS", "STREAM_PORTS")
    assert macros["STREAM_PORTS"].params == (("prefix", None), ("dir_req", None), ("dir_rsp", None), ("width", "8"))


# ---------------------------------------------------------------------------------------------------------------------
# Expansion
# ---------------------------------------------------------------------------------------------------------------------


def test_same_file():
    """Macro Defined In The Same File."""
    text = """
`define CLK_RST input logic clk, input logic rst_n
module m (
    `CLK_RST,
    output logic [7:0] q
);
endmodule
"""
    assert _ports(text) == ["input logic clk", "input logic rst_n", "output logic [7:0] q"]
    assert parse_text(text).modules[0].unresolved_macros == ()


def test_define_after_use():
    """Definition Order Does Not Matter."""
    text = "module m (`PORTS);\nendmodule\n`define PORTS input a, output b\n"
    assert _ports(text) == ["input a", "output b"]


def test_external_macros():
    """Macros Handed Over."""
    macros = parse_defines_text("`define PORTS(n) input logic n``_i, output logic n``_o")
    text = "module m (`PORTS(a), `PORTS( b ));\nendmodule\n"
    assert _ports(text, macros=macros) == ["input logic a_i", "output logic a_o", "input logic b_i", "output logic b_o"]


def test_external_macros_precedence():
    """Macros Handed Over Take Precedence Over Macros In File."""
    text = "`define PORTS input a\nmodule m (`PORTS);\nendmodule\n"
    assert _ports(text) == ["input a"]
    assert _ports(text, macros=parse_defines_text("`define PORTS input b")) == ["input b"]


def test_args():
    """Arguments: Nested Parenthesis, Strings, Defaults, Empty."""
    text = """
`define P(dir, name, width=8, type=logic) dir type [width-1:0] name
module m (
    `P(input, a),
    `P(input, b, $clog2(f(3, 4))),
    `P(input, c, , wire),
    `P ( output , d , W[1] , ),
    `P(output, e, {2{2'd1, 2'd2}}),
    `P(output, f, g(")"))
);
endmodule
"""
    header = expand(text).partition("module m")[2]
    assert [line.strip() for line in header.splitlines()[1:-2]] == [
        "input logic [8-1:0] a,",
        "input logic [$clog2(f(3, 4))-1:0] b,",
        "input wire [8-1:0] c,",
        "output logic [W[1]-1:0] d,",
        "output logic [{2{2'd1, 2'd2}}-1:0] e,",
        'output logic [g(")")-1:0] f',
    ]


def test_arg_is_not_replaced_in_string():
    """Arguments Are Replaced In Stringification Only."""
    macros = parse_defines_text('`define M(x) parameter string A = "x", parameter string B = `"x``_y`"')
    file = parse_text("module m #(`M(foo)) ();\nendmodule\n", macros=macros)
    assert [(param.name, param.default) for param in file.modules[0].params] == [("A", '"x"'), ("B", '"foo_y"')]


def test_nested():
    """Macros Using Macros."""
    text = """
`define WIDTH 4
`define VEC(name) logic [`WIDTH-1:0] name
`define PORTS(a, b) input `VEC(a``_i), output `VEC(b``_o)
module m (`PORTS(x, y));
endmodule
"""
    assert _ports(text) == ["input logic [4-1:0] x_i", "output logic [4-1:0] y_o"]


def test_recursive(caplog):
    """Recursive Macros Do Not Hang."""
    text = "`define A input a, `B\n`define B input b, `A\nmodule m (`A);\nendmodule\n"
    assert _ports(text) == ["input a", "input b"]
    assert "recursive macro `A is not expanded" in caplog.text
    assert parse_text(text).modules[0].unresolved_macros == (MacroCall(name="A"),)


def test_params_and_dims():
    """Macros In Parameter Lists, Default Values And Dimensions."""
    text = """
`define W 8
`define PARAMS parameter int A = `W, parameter int B = 2
module m #(`PARAMS, parameter int C = `W + `UNKNOWN) (
    input logic [`W-1:0] d,
    input logic [`UNKNOWN-1:0] e
);
endmodule
"""
    module = parse_text(text).modules[0]
    assert [(param.name, param.default) for param in module.params] == [("A", "8"), ("B", "2"), ("C", "8 + `UNKNOWN")]
    assert [(port.name, port.dim) for port in module.ports] == [("d", "[8-1:0]"), ("e", "[`UNKNOWN-1:0]")]
    # unknown macros within values and dimensions are kept as they are, there is nothing missing
    assert module.unresolved_macros == ()


def test_comments_and_ifdefs():
    """Comments And Conditions Within Macros Are Kept."""
    text = """
`define PORTS \\
    input  logic a, /* Port A */ \\
`ifdef WITH_B \\
    input  logic b, /* Port B */ \\
`endif \\
    output logic c  /* Port C */
module m (
`ifdef WITH_PORTS
    `PORTS,
`endif
    output logic d
);
endmodule
"""
    assert parse_text(text).modules[0].ports == (
        Port(direction="input", ptype="logic", name="a", comment=("Port A",), ifdefs=("WITH_PORTS",)),
        Port(direction="input", ptype="logic", name="b", comment=("Port B",), ifdefs=("WITH_PORTS", "WITH_B")),
        Port(direction="output", ptype="logic", name="c", comment=("Port C",), ifdefs=("WITH_PORTS",)),
        Port(direction="output", ptype="logic", name="d"),
    )


def test_module_by_macro():
    """Macro Creates Module Header Or The Entire Module."""
    text = """
`define HEADER(name) module name (input logic clk);
`define MODULE(name) `HEADER(name) endmodule
`HEADER(m)
endmodule
`MODULE(n)
"""
    modules = parse_text(text).modules
    assert [module.name for module in modules] == ["m", "n"]
    assert [[port.name for port in module.ports] for module in modules] == [["clk"], ["clk"]]


def test_body():
    """Macros Are Expanded In The Module Body Too."""
    text = """
`define SIG logic sig
`define PORT input `SIG
`define W 4
`define INST(name) sub name (.a(sig), .b(`W));
module m (a, b, sig);
    `PORT;
    input [`W-1:0] a;
    output b;
    localparam int L = `W;
    `INST(u_sub0)
    `INST(u_sub1)
    `UNKNOWN(sig)
    `UNKNOWN
endmodule
"""
    assert expand(text).partition("module m")[2].count("`") == 2
    module = parse_text(text).modules[0]
    assert _ports(text) == ["input logic sig", "input [4-1:0] a", "output b"]
    assert [(param.name, param.default) for param in module.localparams] == [("L", "4")]
    assert [inst.name for inst in module.insts] == ["u_sub0", "u_sub1"]
    assert [(con.port, con.con) for con in module.insts[0].connections] == [("a", "sig"), ("b", "4")]
    # unknown macros in the module body are not reported
    assert module.unresolved_macros == ()


def test_untouched():
    """Text Without Macros Is Not Modified."""
    text = "module m (input a);\nendmodule\n"
    assert expand(text) is text
    text = "`ifdef A\nmodule m (input a);\nendmodule\n`endif\n"
    assert expand(text) is text
    # usage in comments and strings
    text = '`define A input b\nmodule m #(parameter string S = "`A") (/* `A */ input a // `A\n);\nendmodule\n'
    assert expand(text) == text


# ---------------------------------------------------------------------------------------------------------------------
# Unresolved Macros
# ---------------------------------------------------------------------------------------------------------------------


def test_unresolved(caplog):
    """Unknown Macros Are Reported."""
    text = """
module m #(
    parameter int A = 1,
    `PARAMS(A, f(1, 2))
) (
    `CLK_RST,
`ifdef AXI
    `AXI_PORTS(s_axi, 32),
`endif
    `EMPTY_ARGS (),
    output logic q
);
    `BODY_MACRO(q)
endmodule
"""
    with caplog.at_level(logging.WARNING):
        module = parse_text(text, file_path="file.sv").modules[0]
    assert module.unresolved_macros == (
        MacroCall(name="PARAMS", args=("A", "f(1, 2)")),
        MacroCall(name="CLK_RST"),
        MacroCall(name="AXI_PORTS", args=("s_axi", "32"), ifdefs=("AXI",)),
        MacroCall(name="EMPTY_ARGS", args=()),
    )
    assert _ports(text) == ["output logic q"]
    assert [param.name for param in module.params] == ["A"]
    assert "file.sv: module 'm': unknown macro `AXI_PORTS in module header." in caplog.text


@mark.parametrize(
    "use, message",
    (
        ("`P", "macro `P requires arguments"),
        ("`P(a, b, c)", "macro `P is used with wrong number of arguments"),
        ("`P(a)", "macro `P is used with wrong number of arguments"),
    ),
)
def test_wrong_usage(caplog, use, message):
    """Macros Which Are Used Wrong Are Not Expanded."""
    text = f"`define P(name, width) input [width-1:0] name\nmodule m ({use}, input z);\nendmodule\n"
    module = parse_text(text).modules[0]
    assert [macro.name for macro in module.unresolved_macros] == ["P"]
    assert _ports(text) == ["input z"]
    assert message in caplog.text


def test_single_arg():
    """Macro With One Argument Accepts Empty Argument."""
    text = "`define P(name) input a``name\nmodule m (`P(), `P(_b));\nendmodule\n"
    assert _ports(text) == ["input a", "input a_b"]


def test_overview():
    """Unresolved Macros Are Part Of Overview."""
    file = parse_text("module m (`PORTS(a));\nendmodule\n")
    assert '"unresolved_macros"' in file.overview
    file = parse_text("module m (input a);\nendmodule\n")
    assert "unresolved_macros" not in file.overview


# ---------------------------------------------------------------------------------------------------------------------
# Example and Command Line Interface
# ---------------------------------------------------------------------------------------------------------------------

EXAMPLE_PORTS = [
    "input logic clk_i",
    "input logic rst_ni",
    "input logic in_valid",
    "input logic [IN_WIDTH-1:0] in_data",
    "output logic in_ready",
    "output logic out_valid",
    "output logic [8-1:0] out_data",
    "input logic out_ready",
    "output logic busy_o",
]


def test_example():
    """Example With Included Macro File."""
    module = parse_file(MACRO_PORTS_SV).modules[0]
    assert [param.name for param in module.params] == ["IN_WIDTH", "OUT_WIDTH"]
    assert module.unresolved_macros == ()
    assert _ports(MACRO_PORTS_SV.read_text(), file_path=MACRO_PORTS_SV) == EXAMPLE_PORTS
    assert module.ports[0].comment == ("Clock",)
    assert module.ports[-1].comment == ("Busy",)

    # text only: the included file cannot be located
    text = MACRO_PORTS_SV.read_text()
    module = parse_text(text).modules[0]
    assert [port.name for port in module.ports] == ["busy_o"]
    assert [macro.name for macro in module.unresolved_macros] == ["CLK_RST_PORTS", "STREAM_PORTS", "STREAM_PORTS"]
    assert _ports(text, macros=parse_defines(MACROS_SVH)) == EXAMPLE_PORTS
    assert _ports(text, inc_dirs=[MACROS_SVH.parent]) == EXAMPLE_PORTS


@mark.parametrize("cmd", ("json", "info", "gen-sv-instance"))
def test_cli(runner, tmp_path, cmd):
    """Command Line Options --macro-file and --incdir."""
    top = tmp_path / "top.sv"
    top.write_text('`include "macros.svh"\nmodule top (`CLK_RST_PORTS, input logic a_i);\nendmodule\n')
    filelist = tmp_path / "filelist.f"
    filelist.write_text(f"+incdir+{MACROS_SVH.parent}\n")

    result = runner.invoke(cli, [cmd, str(top)])
    assert result.exit_code == 0
    assert "a_i" in result.output
    assert "clk_i" not in result.output

    for options in (
        ("--macro-file", str(MACROS_SVH)),
        ("--incdir", str(MACROS_SVH.parent)),
        ("--filelist", str(filelist)),
    ):
        result = runner.invoke(cli, [cmd, *options, str(top)])
        assert result.exit_code == 0
        for name in ("clk_i", "rst_ni", "a_i"):
            assert name in result.output


# ---------------------------------------------------------------------------------------------------------------------
# `include
# ---------------------------------------------------------------------------------------------------------------------


def test_include(tmp_path, caplog):
    """Macros Of Included Files Are Known."""
    inc = tmp_path / "inc"
    inc.mkdir()
    (tmp_path / "local.svh").write_text('`include "common.svh"\n`define A input a\n')
    (inc / "common.svh").write_text('`include "local.svh" // cyclic\n`include "common.svh"\n`define B input b\n')
    top = tmp_path / "top.sv"
    top.write_text(
        '`include "local.svh"\n'
        '`include "top.sv"\n'
        '`include "missing.svh"\n'
        '// `include "comment.svh"\n'
        "`include `MACRO\n"
        "module top (`A, `B);\n"
        "endmodule\n"
    )
    (tmp_path / "comment.svh").write_text("`define A input not_included\n")

    # 'common.svh' is not found
    with caplog.at_level(logging.INFO):
        module = parse_file(top).modules[0]
    assert [port.name for port in module.ports] == ["a"]
    assert module.unresolved_macros == (MacroCall(name="B"),)
    assert "included file 'missing.svh' not found" in caplog.text
    assert "local.svh: included file 'common.svh' not found" in caplog.text

    for inc_dirs in ([inc], [str(inc)], [tmp_path / "missing", inc]):
        module = parse_file(top, inc_dirs=inc_dirs).modules[0]
        assert [port.name for port in module.ports] == ["a", "b"]
        assert module.unresolved_macros == ()

    assert tuple(parse_defines(top, inc_dirs=[inc])) == ("B", "A")
    assert tuple(parse_defines_text(top.read_text(), inc_dirs=[tmp_path, inc])) == ("B", "A")
    assert parse_defines_text(top.read_text()) == {}


def test_include_precedence(tmp_path):
    """Included Macros Conflicting With Local Ones Are Ambiguous, Macros Handed Over Win."""
    (tmp_path / "inc.svh").write_text("`define P input a\n`define Q input q\n")
    top = tmp_path / "top.sv"
    top.write_text('`include "inc.svh"\n`define P input b\nmodule top (`P, `Q);\nendmodule\n')
    module = parse_file(top).modules[0]
    assert [port.name for port in module.ports] == ["q"]
    assert module.unresolved_macros == (MacroCall(name="P"),)
    module = parse_file(top, macros=parse_defines_text("`define P input c")).modules[0]
    assert [port.name for port in module.ports] == ["c", "q"]


def test_include_unreadable(tmp_path, caplog):
    """Included Files Which Cannot Be Read Are Skipped."""
    (tmp_path / "inc.svh").write_bytes(b"`define P input \xff\xfe\n")
    top = tmp_path / "top.sv"
    top.write_text('`include "inc.svh"\nmodule top (`P);\nendmodule\n')
    module = parse_file(top).modules[0]
    assert module.unresolved_macros == (MacroCall(name="P"),)
    assert "cannot read included file" in caplog.text


def test_conflict_is_reported_on_use(caplog):
    """Conflicting Definitions Within The Parsed File Are Reported If The Macro Is Used."""
    text = (
        "`define W 8\n`define W 16\n`define X 1\n`define X 2\nmodule m (input [`W:0] a, input [`W:0] b);\nendmodule\n"
    )
    assert _ports(text) == ["input [`W:0] a", "input [`W:0] b"]
    assert caplog.text.count("macro `W has conflicting definitions. Not expanded.") == 1
    assert "`X" not in caplog.text


def test_unresolved_multiline_args():
    """Arguments Of Unknown Macros May Span Lines."""
    text = "module m (\n    `PORTS\n    (\n        a, // first\n        b\n    ),\n    input z\n);\nendmodule\n"
    module = parse_text(text).modules[0]
    assert module.unresolved_macros == (MacroCall(name="PORTS", args=("a", "b")),)
    assert _ports(text) == ["input z"]


def test_type_macro_is_resolved():
    """Unknown Macros Used As Type Are Kept As Type And Not Reported."""
    text = "module m (input `MY_T a, `MY_T(3) b, `PORTS input c);\nendmodule\n"
    module = parse_text(text).modules[0]
    assert _ports(text) == ["input `MY_T a", "input `MY_T(3) b", "input c"]
    assert module.unresolved_macros == (MacroCall(name="PORTS"),)
