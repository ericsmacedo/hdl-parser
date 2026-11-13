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

"""Test SystemVerilog Parser."""

from pytest import mark

from hdl_parser import Module, ModuleInstance, Param, Port, parse_text
from hdl_parser._sv.tokenizer import ID, KW, MACRO, tokenize
from hdl_parser.datamodel import Connection


def _parse(text: str) -> Module:
    (module,) = parse_text(text, lang="sv").modules
    return module


def _insts(text: str) -> list[tuple[str, str]]:
    return [(inst.module, inst.name) for inst in _parse(f"module top; {text} endmodule").insts]


def test_tokenize():
    """Tokens, Comments And Directives."""
    result = tokenize('`define FOO a \\\n  b\nmodule \\esc (* attr *) "module" `BAR 4\'hF // text\n')
    assert [(tok.kind, tok.text) for tok in result.tokens[:-1]] == [
        (KW, "module"),
        (ID, "\\esc"),
        ("str", '"module"'),
        (MACRO, "`BAR"),
        ("num", "4"),
        ("num", "'hF"),
    ]
    assert result.comments == {6: ["text"]}


def test_tokenize_ifdefs():
    """Conditions Of Tokens."""
    text = "a `ifdef A b `ifndef B c `elsif C d `else e `endif f `else g `endif h `endif `else `elsif X i"
    assert [(tok.text, tok.ifdefs) for tok in tokenize(text).tokens[:-1]] == [
        ("a", ()),
        ("b", ("A",)),
        ("c", ("A", "!B")),
        ("d", ("A", "B", "C")),
        ("e", ("A", "B", "!C")),
        ("f", ("A",)),
        ("g", ("!A",)),
        ("h", ()),
        ("i", ()),
    ]


def test_port_types():
    """User-Defined, Package-Scoped And Interface Port Types."""
    module = _parse("""
module top (
    input  my_t                 a_i,
    output pkg::data_t [1:0]    b_o [3],
    my_if.slave                 bus,
    input  var logic signed [3:0] c_i, d_i,
    input  cls#(8)::type_t      e_i,
    input  `MY_T                f_i,
    input  struct packed { logic x; logic y; } g_i,
    input  enum logic [1:0] {A, B} h_i,
    input  logic [W[0]-1:0]     i_i,
    input  type(i_i)            j_i,
    input  `TYPE(2) [1:0]       k_i,
    input  `WIDTH
);
endmodule
""")
    assert module.ports == (
        Port(direction="input", ptype="my_t", name="a_i"),
        Port(direction="output", ptype="pkg::data_t", name="b_o", dim="[1:0]", dim_unpacked="[3]"),
        Port(ptype="my_if.slave", name="bus"),
        Port(direction="input", ptype="logic", dtype="signed", name="c_i", dim="[3:0]"),
        Port(direction="input", ptype="logic", dtype="signed", name="d_i", dim="[3:0]"),
        Port(direction="input", ptype="cls#(8)::type_t", name="e_i"),
        Port(direction="input", ptype="`MY_T", name="f_i"),
        Port(direction="input", ptype="struct", name="g_i"),
        Port(direction="input", ptype="enum", name="h_i"),
        Port(direction="input", ptype="logic", name="i_i", dim="[W[0]-1:0]"),
        Port(direction="input", ptype="type", name="j_i"),
        Port(direction="input", ptype="`TYPE(2)", name="k_i", dim="[1:0]"),
    )


def test_port_inherit():
    """Direction Is Inherited Within ANSI Port List."""
    module = _parse("module top (input a, b, logic [1:0] c, output my_t d, e); endmodule")
    assert module.ports == (
        Port(direction="input", name="a"),
        Port(direction="input", name="b"),
        Port(direction="input", ptype="logic", name="c", dim="[1:0]"),
        Port(direction="output", ptype="my_t", name="d"),
        Port(direction="output", ptype="my_t", name="e"),
    )


def test_param_types():
    """Parameter Types And Defaults."""
    module = _parse("""
module top #(
    parameter type T = logic [7:0],
    parameter T [1:0] X = '{1, 2},
    parameter int unsigned Y = f(1, 2), Z = cond ? 3 : 4,
    my_pkg::enum_t E = my_pkg::A,
    localparam string S = ");,"
) ();
    localparam type U = struct packed { logic a; logic b; };
endmodule
""")
    assert module.params == (
        Param(ptype="type", name="T", default="logic [7:0]"),
        Param(ptype="T", name="X", dim="[1:0]", default="'{1, 2}"),
        Param(ptype="int", name="Y", default="f(1, 2)"),
        Param(ptype="int", name="Z", default="cond ? 3 : 4"),
        Param(ptype="my_pkg::enum_t", name="E", default="my_pkg::A"),
    )
    assert module.localparams == (
        Param(ptype="string", name="S", default='");,"'),
        Param(ptype="type", name="U", default="struct packed { logic a; logic b; }"),
    )


def test_instances():
    """Instance Arrays, Instance Lists And Nested Expressions."""
    module = _parse("""
module top;
    sub #(.P($clog2(N)), .T(logic [1:0])) u0 [3:0] (.a(b[1]), .c(f(d, e)), .g(), .h), u1 (i, {j, k}, l(1, 2));
endmodule
""")
    assert module.insts == (
        ModuleInstance(
            name="u0",
            module="sub",
            connections=(
                Connection(port="a", con="b[1]"),
                Connection(port="c", con="f(d, e)"),
                Connection(port="g"),
                Connection(port="h", con="h"),
            ),
        ),
        ModuleInstance(
            name="u1",
            module="sub",
            connections=(Connection(con="i"), Connection(con="{j, k}"), Connection(con="l(1, 2)")),
        ),
    )


def test_generate():
    """Instances Within Generate Constructs."""
    assert _insts("""
    generate
        if (A) begin : g_a
            sub u0 ();
        end else if (B) begin : g_b
            sub u1 ();
        end else sub u2 ();
        for (genvar i = 0; i < N; i++) begin : g_for
            sub u3 (.a(a[i]));
        end
        case (W)
            1: sub u4 ();
            pkg::TWO, 3: begin : g_c sub u5 (); end
            default: sub u6 ();
        endcase
    endgenerate
    """) == [("sub", f"u{idx}") for idx in range(7)]


@mark.parametrize(
    "text",
    [
        "always @(posedge clk) if (a) begin foo x (); end else foo y ();",
        "always_comb case (a) 1: foo x (); default: begin foo y (); end endcase",
        "always @* a = b; always #5 clk = ~clk; initial #5 foo x ();",
        "initial begin : blk fork foo x (); join_any wait fork; do foo y (); while (a); end : blk",
        "initial for (int i = 0; i < 4; i++) forever @(a or b) unique if (c) foo x (); else foo y ();",
        "function automatic int f (int a); foo x (); endfunction task t; foo x (); endtask",
        'lbl: assert property (@(posedge clk) a |-> b) else $error("e"); assert final (a); cover property (p);',
        "always_comb begin assert (a) foo x (); else foo y (); assert #0 (b) else foo z (); end",
        "default clocking cb @(posedge clk); endclocking default disable iff (rst); default clocking cb;",
        "typedef struct packed { logic a; } my_t; my_t foo = bar ? baz : '0; wire [1:0] w = f(1); and g (a, b, c);",
        '`ASSERT(Name, a |-> b) `PLAIN $info("sub u (a);"); (weird) 1 + 2; import pkg::*;',
        "initial fork foo x (); join initial do foo x (); while (a); initial wait (a) foo x (); initial wait fork;",
        "initial disable fork; initial ; initial if (a) ; else return; and #5 g (a, b); foo #5 x ();",
        "property p; foo x (); endproperty covergroup cg; foo x (); endgroup class c; foo x (); endclass",
    ],
)
def test_skip(text):
    """Code Without Instances Does Not Hide The Instances Around."""
    assert _insts(f"sub u0 (); {text} sub u1 ();") == [("sub", "u0"), ("sub", "u1")]


def test_module_header():
    """Module Header Variants."""
    module = _parse("""
(* top *) module automatic top import pkg::*; import other::t;
    #(A = 1, parameter B = 2, localparam C = 3) ((* mark *) input a, .b(c), 4, output d);
endmodule : top
""")
    assert [param.name for param in module.params] == ["A", "B"]
    assert [param.name for param in module.localparams] == ["C"]
    assert [port.name for port in module.ports] == ["a", "d"]

    module = _parse("extern module ext (input a); module top (a, b); input a; output reg [1:0] b = 0, c; endmodule")
    assert module.ports == (
        Port(direction="input", name="a"),
        Port(direction="output", ptype="reg", name="b", dim="[1:0]"),
        Port(direction="output", ptype="reg", name="c", dim="[1:0]"),
    )


def test_comments():
    """Comments Within Expressions Are Removed And Assigned."""
    module = _parse("""
module top #(parameter A = 1 /* one */ + 2 // two
) (input a /* port */);
    sub u0 (// before
        .a(a /* in */ + 1), // con
        .*,
        .b(b));
endmodule
""")
    assert module.params == (Param(name="A", default="1  + 2", comment=("one", "two")),)
    assert module.ports == (Port(direction="input", name="a", comment=("port",)),)
    assert module.insts[0].connections == (
        Connection(port="a", con="a  + 1", comment=("in", "con")),
        Connection(port="b", con="b"),
    )


@mark.parametrize(
    "text, names",
    [
        ("module a (input x); sub u (\nmodule b (output y); endmodule", ["a", "b"]),
        ("module a (input x, module b; endmodule", ["a", "b"]),
        ("module a #(parameter P = (1 module b; endmodule", ["a", "b"]),
        ("module a; always begin module b; endmodule", ["a", "b"]),
        ("module a; function f; module b; endmodule", ["a", "b"]),
        ("module a; ) ] } end endcase join sub u (); endmodule", ["a"]),
        ("module a; sub u (.a(b), ., .(c), d e, );", ["a"]),
        ("module a; sub #(", ["a"]),
        ("module a (input", ["a"]),
        ("module a #(parameter A =", ["a"]),
        ("module a; assert", ["a"]),
        ("module a; if", ["a"]),
        ("module a; `FOO", ["a"]),
        ("module a; initial", ["a"]),
        ("module a; initial begin", ["a"]),
        ("module a (input enum", ["a"]),
        ("module a (input pkg::", ["a"]),
        ("module; module 1; module a", ["a"]),
    ],
)
def test_broken(text, names):
    """Broken Code Does Not Break The Parser And Is Never Skipped Beyond The Next Module."""
    assert [module.name for module in parse_text(text, lang="sv").modules] == names
