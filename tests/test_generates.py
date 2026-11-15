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

"""Generate Constructs Around Instances."""

from hdl_parser import Generate, parse_text


def _generates(text: str, **kwargs) -> dict[str, list[tuple[str, str, str]]]:
    """Generate constructs of all instances as `(kind, name, cond)`, by instance identifier."""
    (module,) = parse_text(text, **kwargs).modules
    return {inst.id: [(gen.kind, gen.name, gen.cond) for gen in inst.generates] for inst in module.insts}


def test_sv():
    """Blocks, Constructs Without `begin` And Their Nesting."""
    text = """\
module top;
  sub u0 ();
  generate
    if (A) begin : g_a
      sub u1 ();
    end else if (B) begin : g_b
      sub u1 ();
    end else sub u2 ();
    sub u3 ();
    for (genvar i = 0; i < N; i++) begin : g_for
      if (X) sub u4 (.a(a[i]));
      sub u5 ();
    end
    if (C) for (genvar j = 0; j < 2; j++) begin sub u6 (); end
    sub u7 ();
  endgenerate
  sub u8 ();
endmodule
"""
    loop = ("for", "g_for", "genvar i = 0; i < N; i++")
    assert _generates(text) == {
        "top.u0": [],
        "top.g_a.u1": [("if", "g_a", "A")],
        "top.g_b.u1": [("if", "g_b", "B")],
        "top.u2": [("else", "", "")],
        "top.u3": [],
        "top.g_for.u4": [loop, ("if", "", "X")],
        "top.g_for.u5": [loop],
        "top.u6": [("if", "", "C"), ("for", "", "genvar j = 0; j < 2; j++")],
        "top.u7": [],
        "top.u8": [],
    }


def test_sv_case():
    """Case Generate And Blocks On Their Own."""
    text = """\
module top;
  case (W)
    1: sub u0 ();
    pkg::TWO, 3: begin : g_c sub u1 (); end
    default: sub u2 ();
  endcase
  g_pre: begin sub u3 (); end
  begin : g_post sub u4 (); end
  sub u5 ();
endmodule
"""
    assert _generates(text) == {
        "top.u0": [("case", "", "W")],
        "top.g_c.u1": [("case", "", "W"), ("begin", "g_c", "")],
        "top.u2": [("case", "", "W")],
        "top.g_pre.u3": [("begin", "g_pre", "")],
        "top.g_post.u4": [("begin", "g_post", "")],
        "top.u5": [],
    }


def test_sv_else_block():
    """`else begin` Is A Block Of Its Own."""
    text = """\
module top;
  if (A) begin : g_a
    sub u ();
  end else begin : g_b
    sub u ();
  end
endmodule
"""
    assert _generates(text) == {"top.g_a.u": [("if", "g_a", "A")], "top.g_b.u": [("else", "g_b", "")]}


def test_sv_procedural_code():
    """Procedural Code Is No Generate Construct."""
    text = """\
module top;
  always_comb begin : p_comb
    if (a) begin b = 1; end else begin b = 0; end
    case (c) 1: d = 1; endcase
  end
  function automatic f(); for (int i = 0; i < 2; i++) begin end endfunction
  sub u0 ();
endmodule
"""
    assert _generates(text) == {"top.u0": []}


def test_sv_unbalanced():
    """Too Many `end` Are Ignored."""
    assert _generates("module top;\n  end\n  endcase\n  sub u0 ();\nendmodule\n") == {"top.u0": []}


def test_vhdl():
    """Generate Statements And Blocks."""
    text = """\
entity top is end;
architecture rtl of top is
begin
  u0 : sub port map (a);
  g_a : if A generate
    u1 : sub port map (a);
    G_For : for i in 0 to 3 generate
      u2 : sub port map (a);
    end generate;
  end generate g_a;
  g_c : case sel generate
    when 0 => u3 : sub port map (a);
  end generate;
  blk : block
  begin
    u4 : sub port map (a);
  end block;
  p : process begin end process;
  u5 : sub port map (a);
end;
"""
    assert _generates(text, lang="vhdl") == {
        "top.u0": [],
        "top.g_a.u1": [("if", "g_a", "A")],
        "top.g_a.g_for.u2": [("if", "g_a", "A"), ("for", "G_For", "i in 0 to 3")],
        "top.g_c.u3": [("case", "g_c", "sel")],
        "top.blk.u4": [("block", "blk", "")],
        "top.u5": [],
    }


def test_model():
    """Generate Constructs Are Part Of The Output."""
    file = parse_text("module top;\n  if (A) begin : g_a\n    sub u0 (.a(a));\n  end\nendmodule\n")
    inst = file.modules[0].insts[0]
    assert inst.generates == (Generate(kind="if", name="g_a", cond="A"),)
    assert inst.connections[0].id == "top.g_a.u0.a"
    assert file.find("top.g_a.u0") is inst
    assert '"generates"' in file.overview
