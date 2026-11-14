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

from pytest import mark, raises

from hdl_parser import Module, ModuleInstance, Param, Port, parse_text
from hdl_parser._tokens import ID, KW, NUM, OP, STR
from hdl_parser._vhdl.tokenizer import tokenize
from hdl_parser.datamodel import Connection


def _parse(text: str) -> Module:
    (module,) = parse_text(text, lang="vhdl").modules
    return module


def _insts(text: str) -> list[tuple[str, str]]:
    module = _parse(f"architecture rtl of top is begin {text} end rtl;")
    return [(inst.module, inst.name) for inst in module.insts]


def _ports(text: str) -> tuple[Port, ...]:
    return _parse(f"entity top is port ({text}); end top;").ports


def _params(text: str) -> tuple[Param, ...]:
    return _parse(f"entity top is generic ({text}); end top;").params


def test_tokenize():
    """Tokens And Comments."""
    result = tokenize('ENTITY \\ext id\\ X"0F" 8sb"1" 16#F#E1 1.5e3 "a""b" := -- text\n/* block\n */ a')
    assert [(tok.kind, tok.text) for tok in result.tokens[:-1]] == [
        (KW, "entity"),
        (ID, "\\ext id\\"),
        (NUM, 'X"0F"'),
        (NUM, '8sb"1"'),
        (NUM, "16#F#E1"),
        (NUM, "1.5e3"),
        (STR, '"a""b"'),
        (OP, ":="),
        (ID, "a"),
    ]
    assert result.comments == {8: ["-- text", "/* block  */"]}


def test_tokenize_tick():
    """Character Literals, Attributes And Qualified Expressions."""
    result = tokenize("a'range t'('1') & '(' b(0)'length x.all'length")
    assert [(tok.kind, tok.text) for tok in result.tokens[:-1]] == [
        (ID, "a"),
        (OP, "'"),
        (KW, "range"),
        (ID, "t"),
        (OP, "'"),
        (OP, "("),
        (STR, "'1'"),
        (OP, ")"),
        (OP, "&"),
        (STR, "'('"),
        (ID, "b"),
        (OP, "("),
        (NUM, "0"),
        (OP, ")"),
        (OP, "'"),
        (ID, "length"),
        (ID, "x"),
        (OP, "."),
        (KW, "all"),
        (OP, "'"),
        (ID, "length"),
    ]


def test_ports():
    """Ports."""
    ports = _ports(
        """
        -- dropped
        signal a, b : in std_logic; -- first
        -- second
        c : OUT Std_Logic_Vector(W-1 DOWNTO 0) := (others => '0');
        d : inout work.pkg.rec_t;
        e : unsigned(f(3, 4) - 1 downto 0);
        f : buffer integer range 0 to 7 := 3;
        g : in t_arr(0 to 3)(7 downto 0) bus;
        h : out
        -- last
        """
    )
    assert ports == (
        Port(direction="in", ptype="signal", dtype="std_logic", name="a", comment=("-- first", "-- second")),
        Port(direction="in", ptype="signal", dtype="std_logic", name="b", comment=("-- first", "-- second")),
        Port(direction="out", dtype="std_logic_vector", name="c", dim="[W-1:0]"),
        Port(direction="inout", dtype="work.pkg.rec_t", name="d"),
        Port(direction="in", dtype="unsigned", name="e", dim="[f(3, 4) - 1:0]"),
        Port(direction="buffer", dtype="integer", name="f"),
        Port(direction="in", dtype="t_arr", name="g", dim="[0:3][7:0]"),
        Port(direction="out", name="h", comment=("-- last",)),
    )


def test_params():
    """Generics."""
    params = _params(
        """
        A : integer;
        constant B, C : natural range 0 to 3 := 2; -- two
        D : std_logic_vector(3 downto 0) := "00" & (others => '1');
        type data_t;
        function conv (a : data_t) return integer;
        E : string := ";"
        """
    )
    assert params == (
        Param(name="A"),
        Param(name="B", ptype="constant", default="2", comment=("-- two",)),
        Param(name="C", ptype="constant", default="2", comment=("-- two",)),
        Param(name="D", dim="[3:0]", default="\"00\" & (others => '1')"),
        Param(name="E", default='";"'),
    )


def test_entity():
    """Entity With Generics, Ports And Declarations."""
    module = _parse(
        """
        entity top is
            generic (W : natural := 8);
            port (a : in std_logic);
            constant C : natural := f(W);
        begin
            assert W > 0;
        end entity top;
        """
    )
    assert module == Module(
        name="top",
        params=(Param(name="W", default="8"),),
        ports=(Port(direction="in", dtype="std_logic", name="a"),),
    )


@mark.parametrize(
    "text",
    [
        "port (a : in std_logic)",
        "port (a : in std_logic); end",
        "port (a : in std_logic; ]",
        "port (a : in std_logic; ()",
        "port (a : in std_logic; : b",
        "port (a : in std_logic; b",
        "(x) port (a : in std_logic);",
    ],
)
def test_entity_incomplete(text):
    """Incomplete Entities."""
    module = _parse(f"entity top is {text}")
    assert [port.name for port in module.ports] == ["a"]


def test_instances():
    """Instances."""
    module = _parse(
        """
        architecture rtl of top is
        begin
            u0 : entity work.sub(rtl)
                generic map (W => 8)
                port map (
                    a => a, -- first
                    b(3 downto 0) => to_sl(b),
                    c => open,
                    d => (others => '0')
                    -- last
                );
            u1 : component sub port map (a, b & c, f(x, y));
            u2 : sub generic map (W => 8);
            u3 : lib.pkg.sub port map (a => a);
            u4 : configuration work.sub_cfg port map (a => a);
        end architecture rtl;
        """
    )
    assert module.insts == (
        ModuleInstance(
            name="u0",
            module="sub",
            connections=(
                Connection(port="a", con="a", comment=("-- first",)),
                Connection(port="b(3 downto 0)", con="to_sl(b)"),
                Connection(port="c", con="open"),
                Connection(port="d", con="(others => '0')", comment=("-- last",)),
            ),
        ),
        ModuleInstance(
            name="u1",
            module="sub",
            connections=(Connection(con="a"), Connection(con="b & c"), Connection(con="f(x, y)")),
        ),
        ModuleInstance(name="u2", module="sub"),
        ModuleInstance(name="u3", module="sub", connections=(Connection(port="a", con="a"),)),
        ModuleInstance(name="u4", module="sub_cfg", connections=(Connection(port="a", con="a"),)),
    )


@mark.parametrize(
    "text",
    [
        "x <= a;",
        "lbl : x <= a when b = '1' else c;",
        "lbl : proc(a, b);",
        "lbl : proc;",
        "proc(a, b);",
        "(x, y) <= a;",
        "with sel select x <= a when '0', b when others;",
        'lbl : assert a = b report "msg" severity error;',
        "lbl : process (clk) begin if rising_edge(clk) then x <= a; end if; end process lbl;",
        "postponed process begin wait; end postponed process;",
        "lbl : entity;",
        "lbl : entity port map (a => a);",
    ],
)
def test_no_instances(text):
    """Statements Which Are No Instances."""
    assert _insts(f"{text} u0 : sub port map (a => a);") == [("sub", "u0")]


@mark.parametrize(
    "text",
    [
        "port map (a => a",
        "port map (a => a,",
        "port map (a => ",
        "port map (a",
        "port map (] a => a);",
        "port map",
        "generic map",
        "port map (a => a) generic map (W => 8)",
    ],
)
def test_instances_incomplete(text):
    """Incomplete Instances."""
    assert _insts(f"u0 : sub {text}") == [("sub", "u0")]


@mark.parametrize(
    "text",
    [
        "signal s : std_logic;",
        "constant C : std_logic_vector(3 downto 0) := (others => '0');",
        "component sub is port (a : in std_logic); end component sub;",
        "component sub port (a : in std_logic); end component;",
        "type state_t is (IDLE, RUN);",
        "type rec_t is record a : std_logic; b : std_logic; end record rec_t;",
        "type dist_t is range 0 to 100 units um; mm = 1000 um; end units dist_t;",
        "type prot_t is protected procedure inc; impure function get return integer; end protected prot_t;",
        "type prot_t is protected body procedure inc is begin v := v + 1; end; end protected body;",
        "function f (a : integer) return integer;",
        "function f (a : integer) return integer is begin return a; end;",
        "pure function f return integer is begin return 1; end function f;",
        'function "+" (a, b : t) return t is begin return a; end "+";',
        "procedure p (signal a : out std_logic) is begin if c then a <= '1'; end if; end procedure;",
        "procedure p is procedure q; procedure q is begin null; end q; function r is new g; begin q; end p;",
        "function f is new g generic map (t => integer);",
        "for all : sub use entity work.sub(rtl);",
        "for all : sub use entity work.sub(rtl); end for;",
        "attribute keep of s : signal is true;",
        "use work.pkg.all;",
        "function f return integer is begin return 1;",
        "function f (",
    ],
)
def test_declarations(text):
    """Architecture Declarations."""
    module = _parse(f"architecture rtl of top is {text} begin u0 : sub port map (a => a); end rtl;")
    expected = [] if text.endswith(("return 1;", "(")) else [("sub", "u0")]
    assert [(inst.module, inst.name) for inst in module.insts] == expected


def test_generate():
    """Instances Within Generates And Blocks."""
    insts = _insts(
        """
        g0 : for i in 0 to 3 generate
            signal s : std_logic;
        begin
            u0 : sub0 port map (a => a(i));
            g1 : if i = 0 generate
                u1 : sub1 port map (a => a);
            end generate;
        end generate g0;
        g2 : if a0 : W = 0 generate
            u2 : sub2 port map (a => a);
        elsif a1 : W = 1 generate
        begin
            u3 : sub3 port map (a => a);
        end a1;
        else generate
            u4 : sub4 port map (a => a);
        end;
        end generate;
        g3 : case W generate
            when 0 => u5 : sub5 port map (a => a);
            when others => u6 : sub6 port map (a => a);
        end generate;
        b0 : block (guard) is
        begin
            b1 : block
            begin
                u7 : sub7 port map (a => a);
            end block;
        end block b0;
        end generate;
        u8 : sub8 port map (a => a);
        """
    )
    assert insts == [(f"sub{idx}", f"u{idx}") for idx in range(9)]


@mark.parametrize("text", ["if", "elsif", "else", "when", "for", "case"])
def test_generate_incomplete(text):
    """Incomplete Generates."""
    assert _insts(f"{text} a; u0 : sub port map (a => a);") == [("sub", "u0")]
    assert _insts(f"u0 : sub port map (a => a); {text} a") == [("sub", "u0")]


def test_units():
    """Entities And Architectures."""
    file = parse_text(
        """
        entity One is port (a : in std_logic); end;
        architecture a0 of ONE is begin u0 : sub0 port map (a => a); end;
        entity two is end entity;
        architecture a1 of one is begin u1 : sub1 port map (a => a); end architecture a1;
        u2 : sub2 port map (a => a);
        architecture a2 of three is begin u3 : entity work.sub3; end a2;
        """,
        lang="vhdl",
    )
    assert [(mod.name, [inst.name for inst in mod.insts]) for mod in file.modules] == [
        ("One", ["u0", "u1"]),
        ("two", []),
        ("three", ["u3"]),
    ]


@mark.parametrize("text", ["", "entity", "entity top", "library ieee; package p is end;"])
def test_no_module(text):
    """Nothing To Find."""
    with raises(RuntimeError):
        parse_text(text, lang="vhdl")


@mark.parametrize(
    "text",
    [
        "entity top is",
        "architecture rtl of top",
        "architecture rtl of top is ) ( ]",
        "architecture rtl of top is function f return integer is begin",
    ],
)
def test_empty(text):
    """Empty Units."""
    assert _parse(text) == Module(name="top")
