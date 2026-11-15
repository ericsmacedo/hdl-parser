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

"""Interfaces And Modports."""

import re

from pytest import mark

from hdl_parser import Interface, Modport, Port, parse_file, parse_text

from .conftest import PRJ_PATH, plain

CORPUS = tuple(sorted((PRJ_PATH / "tests" / "corpus" / "sv").glob("*/*.sv")))

TEXT = """\
interface bus_if #(
  parameter int AW = 32
) (
  input logic clk_i
);
  typedef logic [AW-1:0] addr_t;
  addr_t addr;
  logic  req, ack;

  // Driver
  modport master (output addr, req, input ack, import task send(input addr_t a), clocking cb);
  modport slave (input addr, req, output ack),
          monitor (input addr, req, ack, .alias(req & ack));
endinterface : bus_if

module top (
  bus_if.master bus,
  interface     any
);
  virtual interface bus_if vif;
  bus_if #(.AW(16)) u_bus (.clk_i(clk));
endmodule
"""


def test_interface():
    """Interface With Parameters, Ports, Types And Modports."""
    file = parse_text(TEXT)
    assert file.diagnostics == ()
    (intf,) = file.interfaces
    assert isinstance(intf, Interface)
    assert intf.name == "bus_if"
    assert [param.name for param in intf.params] == ["AW"]
    assert [port.name for port in intf.ports] == ["clk_i"]
    assert [typedef.name for typedef in intf.typedefs] == ["addr_t"]
    assert plain(intf.modports) == (
        Modport(
            name="master",
            ports=(
                Port(direction="output", name="addr"),
                Port(direction="output", name="req"),
                Port(direction="input", name="ack"),
            ),
            comment=("Driver",),
        ),
        Modport(
            name="slave",
            ports=(
                Port(direction="input", name="addr"),
                Port(direction="input", name="req"),
                Port(direction="output", name="ack"),
            ),
        ),
        Modport(
            name="monitor",
            ports=(
                Port(direction="input", name="addr"),
                Port(direction="input", name="req"),
                Port(direction="input", name="ack"),
            ),
        ),
    )


def test_module_next_to_interface():
    """The Module Behind The Interface, Using It."""
    file = parse_text(TEXT)
    (module,) = file.modules
    assert module.name == "top"
    assert [(port.ptype, port.name) for port in module.ports] == [("bus_if.master", "bus"), ("interface", "any")]
    assert [(inst.module, inst.name) for inst in module.insts] == [("bus_if", "u_bus")]


def test_ids_and_locations():
    """Identifiers And Source Locations."""
    file = parse_text(TEXT)
    ids = [item.id for item in file.iter_items()]
    assert ids[:11] == [
        "bus_if",
        "bus_if.AW",
        "bus_if.clk_i",
        "bus_if.addr",
        "bus_if.req",
        "bus_if.ack",
        "bus_if.addr_t",
        "bus_if.master",
        "bus_if.master.addr",
        "bus_if.master.req",
        "bus_if.master.ack",
    ]
    lines = TEXT.split("\n")
    intf = file.interfaces[0]
    assert (intf.loc.line, intf.loc.end_line) == (1, 14)
    master = file.find("bus_if.master")
    assert lines[master.loc.line - 1].strip().startswith("modport master")
    ack = file.find("bus_if.master.ack")
    assert lines[ack.loc.line - 1][ack.loc.col - 1 : ack.loc.end_col - 1] == "ack"
    # modports declared together share their location
    assert file.find("bus_if.slave").loc == file.find("bus_if.monitor").loc
    assert '"interfaces"' in file.overview


def test_interface_class():
    """An Interface Class Is No Interface."""
    file = parse_text("interface class ic; endclass\ninterface i; endinterface\n")
    assert [intf.name for intf in file.interfaces] == ["i"]


def test_broken():
    """Missing `endinterface`, Unclosed Modport."""
    file = parse_text("interface i;\n  modport m (input a;\nmodule top; endmodule\n")
    assert [(diag.code, diag.loc.line, diag.item) for diag in file.diagnostics] == [
        ("missing-end", 1, "i"),
        ("unbalanced-bracket", 2, "i"),
    ]
    assert "interface 'i' has no 'endinterface'" in file.diagnostics[0].message
    assert [module.name for module in file.modules] == ["top"]


def test_no_module_diagnostic():
    """A File With Interfaces Only Is Fine."""
    assert parse_text("interface i; endinterface").diagnostics == ()


@mark.parametrize("path", CORPUS, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_corpus(path):
    """All Interfaces And Modports Of Real Code Are Found."""
    text = path.read_text()
    file = parse_file(path)
    assert [intf.name for intf in file.interfaces] == re.findall(r"^interface\s+(?!class)(\w+)", text, re.MULTILINE)
    modports = [modport for intf in file.interfaces for modport in intf.modports]
    assert [modport.name for modport in modports] == re.findall(r"^\s*modport\s+(\w+)", text, re.MULTILINE)
    for modport in modports:
        assert modport.ports
        assert all(port.direction in ("input", "output", "inout", "ref") for port in modport.ports)


def test_corpus_has_interfaces():
    """The Corpus Covers Interfaces And Modports."""
    files = [parse_file(path) for path in CORPUS]
    interfaces = [intf for file in files for intf in file.interfaces]
    assert len(interfaces) >= 10
    assert sum(len(intf.modports) for intf in interfaces) >= 15
    axi = next(intf for intf in interfaces if intf.name == "AXI_BUS")
    assert [modport.name for modport in axi.modports] == ["Master", "Slave", "Monitor"]
    assert axi.modports[0].ports[0] == axi.modports[0].ports[0].model_copy(update={"direction": "output"})
