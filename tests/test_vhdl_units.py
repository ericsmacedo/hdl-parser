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

"""VHDL: Packages, Constants, Types, Subprograms, Components, Signals And Processes."""

import re

from pytest import mark

from hdl_parser import (
    Event,
    Function,
    Member,
    Module,
    Package,
    Param,
    Port,
    Process,
    Signal,
    Typedef,
    parse_file,
    parse_text,
)

from .conftest import PRJ_PATH, plain

CORPUS = tuple(sorted((PRJ_PATH / "tests" / "corpus" / "vhdl").glob("*/*.vhd*")))

PACKAGE = """\
library ieee;
-- Bus definitions
package bus_pkg is
  constant AW : natural := 32; -- address width
  constant C1, C2 : std_logic_vector(3 downto 0) := "0000";
  -- State of the bus
  type state_t is (IDLE, -- nothing to do
                   BUSY, DONE);
  type req_t is record
    addr : std_logic_vector(AW-1 downto 0); -- address
    we, re : std_logic;
  end record req_t;
  type word_array_t is array (natural range <>) of std_logic_vector(7 downto 0);
  subtype byte_t is std_logic_vector(7 downto 0);
  type incomplete_t;
  type prot_t is protected
    procedure inc;
  end protected;
  -- Number of bits
  function bits(value : natural; base : in positive := 2) return natural;
  pure function "+"(a, b : req_t) return req_t;
  procedure send(signal clk : in std_logic; variable data : out byte_t);
  component sub is
    generic (W : natural := 8);
    port (clk : in std_logic; q : out std_logic_vector(W-1 downto 0));
  end component sub;
end package bus_pkg;

package body bus_pkg is
  function bits(value : natural; base : in positive := 2) return natural is
    variable r : natural;
  begin
    if value > 0 then return 1; end if;
    return r;
  end function;
  function private_f return natural is begin return 0; end;
end package body;
"""

ARCHITECTURE = """\
entity top is
  port (clk, rst_n : in std_logic);
end entity;

architecture rtl of top is
  constant DEPTH : natural := 4;
  signal data_q, data_d : std_logic_vector(7 downto 0) := (others => '0'); -- data
  type mem_t is array (0 to DEPTH-1) of byte_t;
  signal mem : mem_t;
  component sub port (clk : in std_logic); end component;
  function f(x : natural) return natural is
    constant LOCAL : natural := 1;
    type local_t is (A, B);
  begin
    return x;
  end function f;
begin
  -- Data register
  p_reg : process (clk, rst_n)
    variable v : natural;
  begin
    if rst_n = '0' then
      data_q <= (others => '0');
    elsif rising_edge(clk) then
      data_q <= data_d;
    end if;
  end process p_reg;

  process (clk) begin
    if rising_edge(clk) then
      if rst_n = '0' then mem <= (others => (others => '0')); end if;
    end if;
  end process;
  process (all) begin data_d <= data_q; end process;
  process (clk, rst) begin
    if rst = '1' then x <= '0';
    elsif clk'event and clk = '0' then x <= y; end if;
  end process;
  process begin wait until rising_edge(clk); z <= y; end process;
  lbl : assert true;
  process (a, b) begin c <= a and b; end process;
  process (clk_a, clk_b) begin
    if rising_edge(clk_a) then q <= d; end if;
    if rising_edge(clk_b) then r <= d; end if;
  end process;
  g_a : if DEPTH > 2 generate
    signal gen_s : std_logic;
  begin
    p_gen : process (clk) begin if falling_edge(clk) then gen_s <= '1'; end if; end process;
  end generate;
  u0 : sub port map (clk => clk);
end architecture;
"""


def test_package():
    """Package With Constants, Types, Subprograms And Components."""
    file = parse_text(PACKAGE, lang="vhdl")
    assert file.modules == ()
    assert file.diagnostics == ()
    (package,) = file.packages
    byte4 = {"dtype": "std_logic_vector", "dim": "[3:0]", "default": '"0000"'}
    assert plain(package) == Package(
        name="bus_pkg",
        localparams=(
            Param(ptype="constant", dtype="natural", name="AW", default="32", comment=("-- address width",)),
            Param(ptype="constant", name="C1", **byte4),
            Param(ptype="constant", name="C2", **byte4),
        ),
        typedefs=(
            Typedef(
                name="state_t",
                kind="enum",
                members=(Member(name="IDLE", comment=("-- nothing to do",)), Member(name="BUSY"), Member(name="DONE")),
                comment=("-- State of the bus",),
            ),
            Typedef(
                name="req_t",
                kind="struct",
                members=(
                    Member(name="addr", dtype="std_logic_vector", dim="[AW-1:0]", comment=("-- address",)),
                    Member(name="we", dtype="std_logic"),
                    Member(name="re", dtype="std_logic"),
                ),
            ),
            Typedef(
                name="word_array_t", kind="alias", dtype="array (natural range <>) of std_logic_vector(7 downto 0)"
            ),
            Typedef(name="byte_t", kind="alias", dtype="std_logic_vector(7 downto 0)"),
            Typedef(name="prot_t", kind="alias", dtype="protected procedure inc; end protected"),
        ),
        functions=(
            Function(
                name="bits",
                kind="function",
                rtype="natural",
                args=(
                    Port(direction="in", dtype="natural", name="value"),
                    Port(direction="in", dtype="positive", name="base", default="2"),
                ),
                comment=("-- Number of bits",),
            ),
            Function(
                name='"+"',
                kind="function",
                rtype="req_t",
                args=(Port(direction="in", dtype="req_t", name="a"), Port(direction="in", dtype="req_t", name="b")),
            ),
            Function(
                name="send",
                kind="procedure",
                args=(
                    Port(direction="in", ptype="signal", dtype="std_logic", name="clk"),
                    Port(direction="out", ptype="variable", dtype="byte_t", name="data"),
                ),
            ),
        ),
        components=(
            Module(
                name="sub",
                params=(Param(dtype="natural", name="W", default="8"),),
                ports=(
                    Port(direction="in", dtype="std_logic", name="clk"),
                    Port(direction="out", dtype="std_logic_vector", name="q", dim="[W-1:0]"),
                ),
            ),
        ),
    )


def test_package_ids_and_locations():
    """Identifiers Are Lower Case. Locations Span The Declarations."""
    file = parse_text(PACKAGE, lang="vhdl")
    ids = [item.id for item in file.iter_items()]
    assert len(ids) == len(set(ids))
    assert ids[:9] == [
        "bus_pkg",
        "bus_pkg.aw",
        "bus_pkg.c1",
        "bus_pkg.c2",
        "bus_pkg.state_t",
        "bus_pkg.state_t.idle",
        "bus_pkg.state_t.busy",
        "bus_pkg.state_t.done",
        "bus_pkg.req_t",
    ]
    assert {"bus_pkg.bits.base", 'bus_pkg."+".a', "bus_pkg.sub", "bus_pkg.sub.w", "bus_pkg.sub.q"} <= set(ids)
    lines = PACKAGE.split("\n")
    package = file.packages[0]
    assert (package.loc.line, package.loc.end_line) == (3, 27)
    req = file.find("bus_pkg.req_t")
    assert lines[req.loc.line - 1].strip() == "type req_t is record"
    assert lines[req.loc.end_line - 1].strip() == "end record req_t;"
    sub = file.find("bus_pkg.sub")
    assert (sub.loc.line, sub.loc.end_line) == (23, 26)
    assert '"packages"' in file.overview


def test_architecture():
    """Constants, Signals, Types, Subprograms And Components Of An Architecture."""
    file = parse_text(ARCHITECTURE, lang="vhdl")
    assert file.diagnostics == ()
    (module,) = file.modules
    data = {"dtype": "std_logic_vector", "dim": "[7:0]", "default": "(others => '0')", "comment": ("-- data",)}
    assert plain(module.localparams) == (Param(ptype="constant", dtype="natural", name="DEPTH", default="4"),)
    assert [signal.id for signal in module.signals] == ["top.data_q", "top.data_d", "top.mem", "top.g_a.gen_s"]
    assert plain(module.signals[:3]) == (
        Signal(name="data_q", **data),
        Signal(name="data_d", **data),
        Signal(dtype="mem_t", name="mem"),
    )
    assert module.signals[3].generates[0].name == "g_a"
    # the declarations within subprograms and processes are local
    assert [typedef.name for typedef in module.typedefs] == ["mem_t"]
    assert [(function.name, function.rtype, len(function.args)) for function in module.functions] == [
        ("f", "natural", 1)
    ]
    assert plain(module.components) == (
        Module(name="sub", ports=(Port(direction="in", dtype="std_logic", name="clk"),)),
    )
    assert [inst.id for inst in module.insts] == ["top.u0"]


def test_processes():
    """Sensitivity List, Clock And Reset Of Processes."""
    (module,) = parse_text(ARCHITECTURE, lang="vhdl").modules
    overview = [
        (
            proc.id,
            [event.signal for event in proc.events],
            f"{proc.clock_edge} {proc.clock}".strip(),
            f"{proc.reset_edge} {proc.reset}".strip(),
        )
        for proc in module.processes
    ]
    assert overview == [
        ("top.p_reg", ["clk", "rst_n"], "posedge clk", "negedge rst_n"),
        # a reset behind the clock is synchronous: a condition like any other
        ("top.#process2", ["clk"], "posedge clk", ""),
        ("top.#process3", [], "", ""),
        ("top.#process4", ["clk", "rst"], "negedge clk", "posedge rst"),
        ("top.#process5", [], "posedge clk", ""),
        # the label of the assertion in front is not the label of the process
        ("top.#process6", ["a", "b"], "", ""),
        # two clocks: the clock is not known
        ("top.#process7", ["clk_a", "clk_b"], "", ""),
        ("top.g_a.p_gen", ["clk"], "negedge clk", ""),
    ]
    proc = module.processes[0]
    assert [(assign.target, assign.reads, assign.conds, assign.blocking) for assign in proc.assigns] == [
        ("data_q", (), ("rst_n",), False),
        ("data_q", ("data_d",), ("rst_n", "rising_edge", "clk"), False),
    ]
    assert plain(proc).model_copy(update={"assigns": ()}) == Process(
        name="p_reg",
        kind="process",
        events=(Event(signal="clk"), Event(signal="rst_n")),
        clock="clk",
        clock_edge="posedge",
        reset="rst_n",
        reset_edge="negedge",
        comment=("-- Data register",),
    )
    assert (proc.loc.line, proc.loc.end_line) == (19, 27)


def test_package_instance_and_body():
    """A Package Body And A Package Instance Are No Packages."""
    text = "package p is new work.generic_pkg generic map (W => 8);\npackage body q is end;\n"
    file = parse_text(text, lang="vhdl")
    assert file.packages == ()
    assert [diag.code for diag in file.diagnostics] == ["no-module"]


def test_broken():
    """Missing End, Unclosed Enumeration, Incomplete Declarations."""
    text = "package p is\n  type t is (A, B;\n  constant C : natural := 1;\n  function return natural;\n  component;\n"
    file = parse_text(text, lang="vhdl")
    (package,) = file.packages
    assert [diag.code for diag in file.diagnostics] == ["missing-end", "unbalanced-bracket"]
    assert package.name == "p"


def _units(file):
    return (*file.packages, *file.modules)


@mark.parametrize("path", CORPUS, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_corpus(path):
    """Real Code: Everything Declared Is Found, Where It Points To."""
    text = path.read_text(errors="replace")
    lines = text.split("\n")
    file = parse_file(path)
    ids = [item.id for item in file.iter_items()]
    assert len(ids) == len(set(ids))

    code = re.sub(r"--.*", "", text)
    packages = re.findall(r"^\s*package\s+(\w+)\s+is\b(?!\s+new)", code, re.MULTILINE | re.IGNORECASE)
    assert [package.name for package in file.packages] == packages
    processes = [proc for module in file.modules for proc in module.processes]
    ends = re.findall(r"\bend\s+(?:postponed\s+)?process\b", code, re.IGNORECASE)
    assert len(processes) == len(ends)

    for unit in _units(file):
        for item in (
            *unit.localparams,
            *unit.typedefs,
            *unit.functions,
            *unit.components,
            *getattr(unit, "signals", ()),
        ):
            declaration = "\n".join(lines[item.loc.line - 1 : item.loc.end_line])
            assert item.name.lower() in declaration.lower(), item
        for typedef in unit.typedefs:
            assert typedef.kind == "alias" or typedef.members, typedef
        for function in unit.functions:
            assert lines[function.loc.line - 1].lower().count(function.kind), function
            assert bool(function.rtype) == (function.kind == "function"), function
    for proc in processes:
        assert "process" in "\n".join(lines[proc.loc.line - 1 : proc.loc.line + 1]).lower()
        signals = {event.signal.lower() for event in proc.events}
        if proc.reset:
            assert proc.clock
            assert proc.reset.lower() in signals
            assert proc.reset.lower() != proc.clock.lower()
        if proc.clock:
            assert proc.clock_edge in ("posedge", "negedge")
            assert re.search(rf"\b{re.escape(proc.clock)}\b", text)


def test_corpus_has_everything():
    """The Corpus Covers Packages, Constants, Types, Subprograms, Components, Signals And Processes."""
    files = [parse_file(path) for path in CORPUS]
    units = [unit for file in files for unit in _units(file)]
    modules = [module for file in files for module in file.modules]
    typedefs = [typedef for unit in units for typedef in unit.typedefs]
    functions = [function for unit in units for function in unit.functions]
    processes = [proc for module in modules for proc in module.processes]
    assert sum(len(file.packages) for file in files) >= 14
    assert sum(len(unit.localparams) for unit in units) >= 900
    assert sum(typedef.kind == "enum" for typedef in typedefs) >= 40
    assert sum(typedef.kind == "struct" for typedef in typedefs) >= 90
    assert sum(typedef.kind == "alias" for typedef in typedefs) >= 90
    assert sum(len(typedef.members) for typedef in typedefs) >= 1200
    assert sum(function.kind == "function" for function in functions) >= 220
    assert sum(function.kind == "procedure" for function in functions) >= 30
    assert sum(len(function.args) for function in functions) >= 490
    assert sum(len(unit.components) for unit in units) >= 30
    assert sum(len(module.signals) for module in modules) >= 1000
    assert len(processes) >= 170
    assert sum(bool(proc.clock) for proc in processes) >= 120
    assert sum(bool(proc.reset) for proc in processes) >= 35
    assert sum(bool(proc.name) for proc in processes) >= 140


def test_tolerant():
    """Declarations Without Name And Clocks Without Level."""
    text = """\
package p is
  component;
  end component;
  function return natural;
  constant C : natural := 1;
end;
entity top is end;
architecture rtl of top is
begin
  process (clk) begin
    if clk'event then q <= d; end if;
  end process;
end;
"""
    file = parse_text(text, lang="vhdl")
    assert [item.id for item in file.iter_items()] == ["p", "p.c", "top", "top.#process1"]
    # an event without level does not tell the edge
    assert file.modules[0].processes[0].clock == ""
