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

"""Project: All Files Of A Design."""

import logging
import re
from pathlib import Path

from pytest import fixture, mark, raises

from hdl_parser import HierarchyNode, Location, Module, Project, Use, parse_file
from hdl_parser import project as project_module

from .conftest import PRJ_PATH

CORPUS = PRJ_PATH / "tests" / "corpus"
IBEX = CORPUS / "sv" / "ibex"
PROJECT_DIRS = tuple(sorted(path for lang in ("sv", "vhdl") for path in (CORPUS / lang).iterdir() if path.is_dir()))

FILES = {
    "rtl/top.sv": """\
module top (input logic clk);
  mid u_mid (.clk(clk));
  for (genvar i = 0; i < 2; i++) begin : g_leaf
    leaf u_leaf (.clk(clk));
  end
  leaf u_arr [3:0] (.clk(clk));
  missing u_missing ();
endmodule
""",
    "rtl/mid.sv": "module mid (input logic clk);\n  leaf u_leaf (.clk(clk));\n  bus_if u_bus ();\nendmodule\n",
    "rtl/leaf.sv": "module leaf (input logic clk);\nendmodule\ninterface bus_if;\nendinterface\n",
    "rtl/pkg.sv": "package my_pkg;\n  localparam int W = 8;\nendpackage\n",
}


def _write(tmp_path, files) -> None:
    for name, text in files.items():
        path = tmp_path / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)


@fixture
def design(tmp_path):
    """Directory With A Small Design."""
    _write(tmp_path, FILES)
    return tmp_path


def _tree(node: HierarchyNode, indent: int = 0) -> list[str]:
    flags = "".join((" [multiple]" if node.multiple else "", " ..." if node.truncated else ""))
    lines = [f"{'  ' * indent}{node.name}: {node.definition or '?'}{flags}"]
    for child in node.children:
        lines += _tree(child, indent + 1)
    return lines


def _codes(project) -> list[tuple[str, str]]:
    return [(path, diag.code) for path, diag in project.iter_diagnostics()]


# ---------------------------------------------------------------------------------------------------------------------
# files and items
# ---------------------------------------------------------------------------------------------------------------------


def test_from_dir(design):
    """All Files Below A Directory. Paths And Identifiers Are Relative To It."""
    (design / ".git").mkdir()
    (design / ".git" / "hidden.sv").write_text("module hidden; endmodule\n")
    (design / "rtl" / "notes.txt").write_text("module text; endmodule\n")
    project = Project.from_dir(design)
    assert project.root == design
    assert [file.file_id for file in project.files] == ["rtl/leaf.sv", "rtl/mid.sv", "rtl/pkg.sv", "rtl/top.sv"]
    assert project.file("rtl/top.sv") is project.files[3]
    assert project.file("rtl/none.sv") is None
    port = project.find("rtl/top.sv:top.clk")
    assert port is project.files[3].modules[0].ports[0]
    assert project.find("rtl/top.sv:top.none") is None
    assert project.find("top.clk") is None


def test_from_dir_exclude(design):
    """Files Left Out By Pattern."""
    project = Project.from_dir(design, exclude=["*/pkg.sv", "rtl/m*"])
    assert [file.file_id for file in project.files] == ["rtl/leaf.sv", "rtl/top.sv"]


def test_from_files_root(design, monkeypatch):
    """The Root Is The Common Directory Of All Files, Or Given."""
    project = Project.from_files([design / "rtl" / "top.sv", design / "rtl" / "mid.sv"])
    assert project.root == design / "rtl"
    assert [file.file_id for file in project.files] == ["top.sv", "mid.sv"]
    project = Project.from_files([str(design / "rtl" / "top.sv")], root=design)
    assert [file.file_id for file in project.files] == ["rtl/top.sv"]
    # a file outside of the root: its path never depends on the current directory
    (design / "sim").mkdir()
    (design / "sim" / "leaf.sv").write_text("module leaf; endmodule\n")
    for cwd in (design, design / "rtl", design.parent):
        monkeypatch.chdir(cwd)
        project = Project.from_files(
            [design / "rtl" / "top.sv", design / "rtl" / "leaf.sv", design / "sim" / "leaf.sv"],
            root=design / "sim",
            prefer={"leaf": "../rtl/leaf.sv"},
        )
        assert [file.file_id for file in project.files] == ["../rtl/top.sv", "../rtl/leaf.sv", "leaf.sv"]
        assert project.file("../rtl/top.sv") is project.files[0]
        assert project.resolve("leaf").id == "../rtl/leaf.sv:leaf"
        assert Project.model_validate_json(project.model_dump_json()) == project
    assert Project.from_files([]).files == ()


def test_from_filelist(design):
    """Files And Include Directories Of A Filelist."""
    (design / "design.f").write_text("+incdir+inc\nrtl/pkg.sv\nrtl/leaf.sv\n../outside.sv\n")
    project = Project.from_filelist(design / "design.f", root=design, expand_macros=True)
    assert [file.file_id for file in project.files] == [
        "rtl/pkg.sv",
        "rtl/leaf.sv",
        "../outside.sv",
    ]
    assert project.settings.inc_dirs == ("inc",)
    assert project.settings.expand_macros


# ---------------------------------------------------------------------------------------------------------------------
# partial results
# ---------------------------------------------------------------------------------------------------------------------


def test_missing_and_unreadable_files(design, caplog):
    """A File Which Cannot Be Read Is Part Of The Project, With A Diagnostic. The Others Are Still There."""
    (design / "rtl" / "dir.sv").mkdir()
    paths = [design / "rtl" / "none.sv", design / "rtl" / "dir.sv", design / "rtl" / "leaf.sv", design / "x" / "a.vhd"]
    project = Project.from_files(paths, root=design)
    none, directory, leaf, vhdl = project.files
    assert [(diag.code, diag.severity) for diag in none.diagnostics] == [("file-not-found", "error")]
    assert [(diag.code, diag.severity) for diag in directory.diagnostics] == [("file-unreadable", "error")]
    assert none.modules == directory.modules == ()
    assert [module.name for module in leaf.modules] == ["leaf"]
    assert (vhdl.lang, vhdl.diagnostics[0].code) == ("vhdl", "file-not-found")
    assert {record.levelno for record in caplog.records} == {logging.DEBUG}
    assert "rtl/none.sv: file not found." in caplog.text


def test_parse_failed(design, monkeypatch):
    """A Bug Of The Parser Does Not Stop The Other Files."""
    original = project_module.parse_file

    def parse(path, **kwargs):
        if path.name == "mid.sv":
            raise RecursionError("too deep")
        return original(path, **kwargs)

    monkeypatch.setattr(project_module, "parse_file", parse)
    project = Project.from_dir(design)
    mid = project.file("rtl/mid.sv")
    assert [(diag.code, diag.severity, diag.message) for diag in mid.diagnostics] == [
        ("parse-failed", "error", "cannot parse file: RecursionError: too deep")
    ]
    assert [module.name for module in project.file("rtl/top.sv").modules] == ["top"]
    # the module of the broken file is not defined
    assert ("rtl/top.sv", "undefined-module") in _codes(project)


# ---------------------------------------------------------------------------------------------------------------------
# hierarchy
# ---------------------------------------------------------------------------------------------------------------------


def test_hierarchy(design):
    """Instance Tree, With And Without Depth Limit."""
    project = Project.from_dir(design)
    assert _tree(project.hierarchy("top")) == [
        "top: rtl/top.sv:top",
        "  u_mid: rtl/mid.sv:mid",
        "    u_leaf: rtl/leaf.sv:leaf",
        "    u_bus: rtl/leaf.sv:bus_if",
        "  u_leaf: rtl/leaf.sv:leaf [multiple]",
        "  u_arr: rtl/leaf.sv:leaf [multiple]",
        "  u_missing: ?",
    ]
    assert _tree(project.hierarchy("top", depth=1)) == [
        "top: rtl/top.sv:top",
        "  u_mid: rtl/mid.sv:mid ...",
        "  u_leaf: rtl/leaf.sv:leaf [multiple]",
        "  u_arr: rtl/leaf.sv:leaf [multiple]",
        "  u_missing: ?",
    ]
    assert _tree(project.hierarchy("top", depth=0)) == ["top: rtl/top.sv:top ..."]
    assert _tree(project.hierarchy("leaf", depth=0)) == ["leaf: rtl/leaf.sv:leaf"]
    assert _tree(project.hierarchy("rtl/mid.sv:mid", depth=0)) == ["mid: rtl/mid.sv:mid ..."]
    assert project.hierarchy("none") is None
    node = project.hierarchy("top").children[1]
    assert node == HierarchyNode(
        name="u_leaf", module="leaf", inst="rtl/top.sv:top.g_leaf.u_leaf", definition="rtl/leaf.sv:leaf", multiple=True
    )
    assert project.find(node.inst).name == "u_leaf"


def test_tops_and_where_used(design):
    """Modules Instantiated Nowhere, And The Instances Of A Module."""
    project = Project.from_dir(design)
    assert [top.id for top in project.tops()] == ["rtl/top.sv:top"]
    uses = project.where_used("leaf")
    # in the order of the files
    assert [(use.inst, use.module) for use in uses] == [
        ("rtl/mid.sv:mid.u_leaf", "rtl/mid.sv:mid"),
        ("rtl/top.sv:top.g_leaf.u_leaf", "rtl/top.sv:top"),
        ("rtl/top.sv:top.u_arr", "rtl/top.sv:top"),
    ]
    assert uses[0] == Use(inst=uses[0].inst, module="rtl/mid.sv:mid", loc=project.find(uses[0].inst).loc)
    assert [use.inst for use in project.where_used("bus_if")] == ["rtl/mid.sv:mid.u_bus"]
    assert [use.inst for use in project.where_used("rtl/mid.sv:mid")] == ["rtl/top.sv:top.u_mid"]
    assert project.where_used("top") == ()
    assert project.where_used("none") == ()


def test_undefined_module(design, caplog):
    """An Instance Of A Module Which Is Defined Nowhere."""
    project = Project.from_dir(design)
    assert _codes(project) == [("rtl/top.sv", "undefined-module")]
    (diag,) = project.file("rtl/top.sv").diagnostics
    assert (diag.severity, diag.loc.line, diag.item) == ("warning", 7, "top.u_missing")
    assert diag.message == "module 'missing' of instance 'u_missing' is not defined in the project."
    assert "rtl/top.sv:7:3: module 'missing' of instance 'u_missing' is not defined in the project." in caplog.text


def test_recursion(tmp_path):
    """A Module Containing Itself Does Not Hang."""
    _write(tmp_path, {"a.sv": "module a;\n  b u_b ();\nendmodule\n", "b.sv": "module b;\n  a u_a ();\nendmodule\n"})
    project = Project.from_dir(tmp_path)
    assert _tree(project.hierarchy("a")) == ["a: a.sv:a", "  u_b: b.sv:b", "    u_a: a.sv:a ..."]
    assert project.tops() == ()


# ---------------------------------------------------------------------------------------------------------------------
# definitions
# ---------------------------------------------------------------------------------------------------------------------

DUPLICATES = {
    "models/fifo.sv": "module fifo;\n  model_cell u_cell ();\nendmodule\nmodule model_cell; endmodule\n",
    "rtl/fifo.sv": "module fifo;\n  rtl_cell u_cell ();\nendmodule\nmodule rtl_cell; endmodule\n",
    "rtl/top.sv": "module top;\n  fifo u_fifo ();\nendmodule\n",
    "models/pkg.sv": "package p; endpackage\n",
    "rtl/pkg.sv": "package p; endpackage\n",
}


def test_duplicates(tmp_path):
    """The First Definition Is Used. All Are Reported And Can Be Addressed."""
    _write(tmp_path, DUPLICATES)
    project = Project.from_dir(tmp_path)
    assert [definition.id for definition in project.definitions("fifo")] == ["models/fifo.sv:fifo", "rtl/fifo.sv:fifo"]
    assert project.resolve("fifo").id == "models/fifo.sv:fifo"
    assert project.resolve("rtl/fifo.sv:fifo").id == "rtl/fifo.sv:fifo"
    assert project.resolve_package("p").id == "models/pkg.sv:p"
    assert project.resolve_package("none") is None
    assert project.resolve("none") is None
    assert project.definitions("none") == ()
    # a name which is not found as it is, is not case sensitive
    assert [definition.id for definition in project.definitions("FIFO")] == ["models/fifo.sv:fifo", "rtl/fifo.sv:fifo"]
    assert _tree(project.hierarchy("top")) == [
        "top: rtl/top.sv:top",
        "  u_fifo: models/fifo.sv:fifo",
        "    u_cell: models/fifo.sv:model_cell",
    ]
    # the definition which is not used can still be looked at
    assert _tree(project.hierarchy("rtl/fifo.sv:fifo")) == ["fifo: rtl/fifo.sv:fifo", "  u_cell: rtl/fifo.sv:rtl_cell"]
    assert _codes(project) == [
        ("models/fifo.sv", "duplicate-definition"),
        ("models/pkg.sv", "duplicate-definition"),
        ("rtl/fifo.sv", "duplicate-definition"),
        ("rtl/pkg.sv", "duplicate-definition"),
    ]
    used, other = project.file("models/fifo.sv").diagnostics[0], project.file("rtl/fifo.sv").diagnostics[0]
    assert used.message == "module 'fifo' is defined in 'rtl/fifo.sv' too. This one is used."
    assert other.message == "module 'fifo' is defined in 'models/fifo.sv' too, which is used."
    assert (other.loc.line, other.item) == (1, "fifo")
    assert "package 'p'" in project.file("rtl/pkg.sv").diagnostics[0].message
    # the module which is not used is instantiated nowhere
    assert [top.id for top in project.tops()] == ["rtl/fifo.sv:fifo", "rtl/top.sv:top"]
    assert [use.inst for use in project.where_used("fifo")] == ["rtl/top.sv:top.u_fifo"]
    assert project.where_used("rtl/fifo.sv:fifo") == ()


def test_duplicates_prefer(tmp_path):
    """The Definition To Be Used, By Name."""
    _write(tmp_path, DUPLICATES)
    project = Project.from_dir(tmp_path, prefer={"fifo": "rtl/fifo.sv", "p": "rtl/pkg.sv"})
    assert project.resolve("fifo").id == "rtl/fifo.sv:fifo"
    assert project.resolve_package("p").id == "rtl/pkg.sv:p"
    assert _tree(project.hierarchy("top"))[1:] == ["  u_fifo: rtl/fifo.sv:fifo", "    u_cell: rtl/fifo.sv:rtl_cell"]
    assert project.file("rtl/fifo.sv").diagnostics[0].message.endswith("This one is used.")


def test_duplicates_exclude(tmp_path):
    """Leaving The Other Definition Out."""
    _write(tmp_path, DUPLICATES)
    project = Project.from_dir(tmp_path, exclude=["models/*"])
    assert project.resolve("fifo").id == "rtl/fifo.sv:fifo"
    assert _codes(project) == []


# ---------------------------------------------------------------------------------------------------------------------
# VHDL and mixed language
# ---------------------------------------------------------------------------------------------------------------------

MIXED = {
    "top.vhd": """\
entity Top is end;
architecture rtl of top is
begin
  u_sv : entity work.SV_LEAF port map (clk => clk);
  u_vhdl : VHDL_Leaf port map (clk => clk);
end;
""",
    "vhdl_leaf_ent.vhd": "entity vhdl_leaf is port (clk : in std_logic); end;\n",
    "vhdl_leaf_rtl.vhd": """\
architecture rtl of VHDL_LEAF is
begin
  u_sub : entity work.sub port map (clk => clk);
end;
""",
    "vhdl_leaf_sim.vhd": "architecture sim of vhdl_leaf is\nbegin\n  u_model : model port map (clk => clk);\nend;\n",
    "sv_leaf.sv": (
        "module sv_leaf (input clk);\n  Vhdl_Leaf u_up ();\n  SV_LEAF u_case ();\nendmodule\nmodule sub; endmodule\n"
    ),
}


def test_mixed_language(tmp_path):
    """VHDL Names Are Not Case Sensitive. An Entity And Its Architectures May Be Located In Different Files."""
    _write(tmp_path, MIXED)
    project = Project.from_dir(tmp_path)
    assert _tree(project.hierarchy("TOP")) == [
        "Top: top.vhd:top",
        "  u_sv: sv_leaf.sv:sv_leaf",
        # SystemVerilog refers to VHDL by any case
        "    u_up: vhdl_leaf_ent.vhd:vhdl_leaf",
        "      u_sub: sv_leaf.sv:sub",
        "      u_model: ?",
        # but to SystemVerilog by the exact name
        "    u_case: ?",
        "  u_vhdl: vhdl_leaf_ent.vhd:vhdl_leaf",
        "    u_sub: sv_leaf.sv:sub",
        "    u_model: ?",
    ]
    # the architectures in other files are no modules on their own
    assert [definition.id for definition in project.definitions("vhdl_leaf")] == ["vhdl_leaf_ent.vhd:vhdl_leaf"]
    assert [top.id for top in project.tops()] == ["top.vhd:top"]
    assert _codes(project) == [("sv_leaf.sv", "undefined-module"), ("vhdl_leaf_sim.vhd", "undefined-module")]
    assert [use.module for use in project.where_used("sub")] == ["vhdl_leaf_ent.vhd:vhdl_leaf"]
    assert [use.inst for use in project.where_used("sub")] == ["vhdl_leaf_rtl.vhd:vhdl_leaf.u_sub"]
    # the identifier of an architecture stands for its entity
    assert project.resolve("vhdl_leaf_rtl.vhd:vhdl_leaf").id == "vhdl_leaf_ent.vhd:vhdl_leaf"
    assert project.resolve("vhdl_leaf_rtl.vhd:vhdl_leaf.u_sub") is None


def test_architecture_without_entity(tmp_path):
    """Architectures Without Entity Stand For Their Module."""
    _write(tmp_path, {name: text for name, text in MIXED.items() if name != "vhdl_leaf_ent.vhd"})
    project = Project.from_dir(tmp_path)
    assert [definition.id for definition in project.definitions("vhdl_leaf")] == ["vhdl_leaf_rtl.vhd:vhdl_leaf"]
    assert _tree(project.hierarchy("vhdl_leaf")) == [
        "VHDL_LEAF: vhdl_leaf_rtl.vhd:vhdl_leaf",
        "  u_sub: sv_leaf.sv:sub",
        "  u_model: ?",
    ]


# ---------------------------------------------------------------------------------------------------------------------
# settings and output
# ---------------------------------------------------------------------------------------------------------------------


def test_defines(tmp_path):
    """Macros Defined For All Files."""
    text = "module top (\n`ifdef WITH_A\n  input logic [`WIDTH-1:0] a,\n`endif\n  input logic b\n);\nendmodule\n"
    _write(tmp_path, {"top.sv": text})
    plain = Project.from_dir(tmp_path, defines={"WITH_A": "", "WIDTH": "8"})
    assert [(port.name, port.dim, port.ifdefs) for port in plain.files[0].modules[0].ports] == [
        ("a", "[`WIDTH-1:0]", ("WITH_A",)),
        ("b", "", ()),
    ]
    project = Project.from_dir(tmp_path, defines={"WITH_A": "", "WIDTH": "8"}, expand_macros=True, resolve_ifdefs=True)
    assert [(port.name, port.dim, port.ifdefs) for port in project.files[0].modules[0].ports] == [
        ("a", "[8-1:0]", ()),
        ("b", "", ()),
    ]
    assert project.settings.defines == {"WITH_A": "", "WIDTH": "8"}
    assert project.diagnostics == ()


@mark.parametrize(
    "defines, message",
    (
        ({"P(": "1"}, "'P(' of 'defines' is no macro name."),
        ({"1X": "2"}, "'1X' of 'defines' is no macro name."),
        ({"A": "1\n`define B"}, "value of 'A' of 'defines' has more than one line."),
    ),
)
def test_defines_invalid(tmp_path, defines, message):
    """Defines Which Cannot Be Defined Are An Error, Like Other Invalid Settings."""
    with raises(ValueError, match=re.escape(message)):
        Project.from_dir(tmp_path, defines=defines)


def test_defines_function_like(tmp_path):
    """A Function-Like Macro Is Defined By Its Name With Parameters."""
    _write(tmp_path, {"top.sv": "module top (input [`MAX(3, 7):0] a);\nendmodule\n"})
    project = Project.from_dir(tmp_path, defines={"MAX(a, b)": "b"}, expand_macros=True)
    assert project.files[0].modules[0].ports[0].dim == "[7:0]"
    assert project.diagnostics == ()


def test_filelist_bad_define(tmp_path):
    """A Define Of A Filelist Without Valid Name Is A Problem Of The Filelist."""
    _write(tmp_path, {"top.sv": "module top;\nendmodule\n"})
    (tmp_path / "design.f").write_text("top.sv\n+define+1X=2\n")
    project = Project.from_filelist(tmp_path / "design.f", expand_macros=True)
    assert project.settings.defines == {}
    assert [(diag.code, diag.message, diag.loc, diag.file) for diag in project.diagnostics] == [
        (
            "macro-bad-define",
            "cannot parse definition '1X=2'. Skipped.",
            Location(line=2, col=1, end_line=2, end_col=13),
            "design.f",
        )
    ]


def test_include_diagnostics_relative(tmp_path, caplog):
    """The Included File Of A Diagnostic Is Relative To The Root, Like The Log Message."""
    _write(
        tmp_path, {"rtl/top.sv": '`include "inc.svh"\nmodule top;\nendmodule\n', "rtl/inc.svh": '`include "nope.svh"\n'}
    )
    project = Project.from_dir(tmp_path, expand_macros=True)
    top = next(file for file in project.files if file.file_id == "rtl/top.sv")
    assert [(diag.code, diag.file) for diag in top.diagnostics] == [("include-not-found", "rtl/inc.svh")]
    messages = [record.getMessage() for record in caplog.records if record.name == "hdl_parser._diagnostics"]
    assert "rtl/top.sv: rtl/inc.svh:1:1: included file 'nope.svh' not found. Its macros are unknown." in messages


def test_json(design):
    """One Document For All Files, With Version. It Can Be Loaded Again."""
    project = Project.from_dir(design)
    overview = project.overview
    assert f'"schema_version": {project_module.SCHEMA_VERSION}' in overview
    assert '"rtl/top.sv"' in overview
    loaded = Project.model_validate_json(project.model_dump_json())
    assert loaded == project
    assert _tree(loaded.hierarchy("top")) == _tree(project.hierarchy("top"))
    assert "schema_version" in Project.model_json_schema()["required"]


# ---------------------------------------------------------------------------------------------------------------------
# real code
# ---------------------------------------------------------------------------------------------------------------------


def test_ibex_filelist():
    """The Core Of Ibex, From Its Own Filelist."""
    project = Project.from_filelist(IBEX / "ibex_core.f")
    assert project.root == IBEX
    assert len(project.files) == 17
    assert [file.file_id for file in project.files[:2]] == ["ibex_pkg.sv", "ibex_alu.sv"]
    assert not [diag for _, diag in project.iter_diagnostics() if diag.severity == "error"]
    assert project.resolve_package("ibex_pkg").id == "ibex_pkg.sv:ibex_pkg"
    assert "ibex_core.sv:ibex_core" in [top.id for top in project.tops()]

    tree = project.hierarchy("ibex_core")
    children = {node.name: node for node in tree.children}
    assert children["if_stage_i"].definition == "ibex_if_stage.sv:ibex_if_stage"
    assert children["id_stage_i"].definition == "ibex_id_stage.sv:ibex_id_stage"
    assert children["ex_block_i"].definition == "ibex_ex_block.sv:ibex_ex_block"
    assert children["cs_registers_i"].definition == "ibex_cs_registers.sv:ibex_cs_registers"
    assert [(node.name, node.definition) for node in children["ex_block_i"].children] == [
        ("alu_i", "ibex_alu.sv:ibex_alu"),
        ("multdiv_i", "ibex_multdiv_slow.sv:ibex_multdiv_slow"),
        ("multdiv_i", "ibex_multdiv_fast.sv:ibex_multdiv_fast"),
    ]
    # the filelist of the project does not name everything
    assert children["wb_stage_i"].definition == ""
    assert children["u_fetch_enable_buf"].definition == ""

    uses = project.where_used("ibex_counter")
    assert [use.module for use in uses] == ["ibex_cs_registers.sv:ibex_cs_registers"] * 3
    assert [project.find(use.inst).name for use in uses] == [
        "mcycle_counter_i",
        "minstret_counter_i",
        "mcounters_variable_i",
    ]
    text = (IBEX / "ibex_cs_registers.sv").read_text().split("\n")
    assert all("ibex_counter" in text[use.loc.line - 1] for use in uses)


def test_ibex_dir():
    """All Files Of Ibex Within The Corpus."""
    project = Project.from_dir(IBEX)
    assert [top.unit.name for top in project.tops()] == ["ibex_top"]
    tree = project.hierarchy("ibex_top")
    core = next(node for node in tree.children if node.name == "u_ibex_core")
    assert core.definition == "ibex_core.sv:ibex_core"
    names = {node.module for node in core.children if node.definition}
    assert {
        "ibex_if_stage",
        "ibex_id_stage",
        "ibex_ex_block",
        "ibex_cs_registers",
        "ibex_wb_stage",
        "ibex_pmp",
    } <= names
    undefined = {
        diag.message.split("'")[1] for _, diag in project.iter_diagnostics() if diag.code == "undefined-module"
    }
    assert {"prim_buf", "prim_flop", "prim_clock_gating"} <= undefined
    assert not undefined & {module.name for file in project.files for module in file.modules}


def test_potato():
    """A Real VHDL Project."""
    project = Project.from_dir(CORPUS / "vhdl" / "potato")
    assert {top.unit.name for top in project.tops()} == {"pp_fifo", "toplevel"}
    assert _tree(project.hierarchy("toplevel", depth=3))[3:11] == [
        "  processor: pp_potato.vhd:pp_potato",
        "    processor: pp_core.vhd:pp_core",
        "      csr_unit: pp_csr_unit.vhd:pp_csr_unit ...",
        "      regfile: ?",
        "      fetch: ?",
        "      decode: pp_decode.vhd:pp_decode ...",
        "      execute: pp_execute.vhd:pp_execute ...",
        "      memory: pp_memory.vhd:pp_memory",
    ]
    assert [use.inst for use in project.where_used("PP_CORE")] == ["pp_potato.vhd:pp_potato.processor"]
    assert project.resolve_package("pp_types").id == "pp_types.vhd:pp_types"


def test_microwatt_duplicates():
    """Real Duplicates: A Generic And A Vendor Specific Implementation."""
    path = CORPUS / "vhdl" / "microwatt"
    project = Project.from_dir(path)
    assert [definition.id for definition in project.definitions("multiply")] == [
        "multiply.vhdl:multiply",
        "xilinx-mult.vhdl:multiply",
    ]
    duplicates = [(file, diag.item) for file, diag in project.iter_diagnostics() if diag.code == "duplicate-definition"]
    assert duplicates == [
        ("multiply.vhdl", "multiply"),
        ("multiply.vhdl", "short_multiply"),
        ("xilinx-mult.vhdl", "multiply"),
        ("xilinx-mult.vhdl", "short_multiply"),
    ]
    project = Project.from_dir(path, prefer={"multiply": "xilinx-mult.vhdl"})
    assert project.resolve("multiply").id == "xilinx-mult.vhdl:multiply"
    assert project.resolve("short_multiply").id == "multiply.vhdl:short_multiply"
    project = Project.from_dir(path, exclude=["xilinx-*"])
    assert "duplicate-definition" not in [code for _, code in _codes(project)]


def _nodes(node: HierarchyNode):
    yield node
    for child in node.children:
        yield from _nodes(child)


@mark.parametrize("path", PROJECT_DIRS, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_corpus(path):
    """Real Projects: The Model Of The Project Is Consistent With Its Files."""
    logging.disable(logging.WARNING)
    try:
        project = Project.from_dir(path)
    finally:
        logging.disable(logging.NOTSET)
    assert project.files
    assert not [diag for _, diag in project.iter_diagnostics() if diag.severity == "error"]
    # the files are the ones parsed on their own
    for file in project.files[:5]:
        alone = parse_file(path / file.path)
        assert [module.id for module in file.modules] == [module.id for module in alone.modules]

    modules = [module for file in project.files for module in (*file.modules, *file.interfaces)]
    insts = [inst for module in modules for inst in module.insts]
    undefined = [diag for _, diag in project.iter_diagnostics() if diag.code == "undefined-module"]
    uses = [
        use for file in project.files for module in file.modules for use in project.where_used(file.full_id(module))
    ]
    # every instance is either resolved or reported
    assert len({use.inst for use in uses} | {diag.item for diag in undefined}) <= len(insts)
    for use in uses:
        inst = project.find(use.inst)
        assert inst.loc == use.loc
        assert isinstance(project.find(use.module), Module)

    tops = project.tops()
    assert tops
    for top in tops:
        assert project.where_used(top.id) == ()
        for node in _nodes(project.hierarchy(top.id)):
            if node.inst:
                assert project.find(node.inst).name == node.name
            if node.definition:
                definition = project.find(node.definition)
                assert definition.name.lower() == node.module.lower()
                text = (path / node.definition.split(":")[0]).read_text(errors="replace")
                assert re.search(rf"\b{re.escape(definition.name)}\b", text)
            else:
                assert not node.children


# ---------------------------------------------------------------------------------------------------------------------
# filelists
# ---------------------------------------------------------------------------------------------------------------------

LIBRARY = {
    "design.f": "+define+WITH_B\n+incdir+inc\nrtl/top.sv\n-v lib/cells.v\n-y lib/dir\n+libext+.sv\n-unknown\n",
    "rtl/top.sv": """\
module top (
`ifdef WITH_B
  input logic b,
`endif
  input logic a
);
  cell_a u_a ();
  searched u_searched ();
  nowhere u_nowhere ();
  local_cell u_local ();
endmodule
module local_cell; endmodule
""",
    "lib/cells.v": "module cell_a; endmodule\nmodule local_cell; endmodule\nmodule unused; endmodule\n",
    "lib/dir/searched.sv": "module searched;\n  deeper u_deeper ();\nendmodule\n",
    "lib/dir/deeper.sv": "module deeper; endmodule\n",
    "lib/dir/not_needed.sv": "module not_needed; endmodule\n",
    "lib/dir/nowhere.v": "module nowhere; endmodule\n",
}


def test_filelist_libraries(tmp_path):
    """Library Files And Directories Of A Filelist."""
    _write(tmp_path, LIBRARY)
    project = Project.from_filelist(tmp_path / "design.f")
    assert project.root == tmp_path
    # the files of the library directory are found by the name of the modules, which are not defined
    assert [file.file_id for file in project.files] == [
        "rtl/top.sv",
        "lib/cells.v",
        "lib/dir/searched.sv",
        "lib/dir/deeper.sv",
    ]
    assert project.libraries == ("lib/cells.v", "lib/dir/searched.sv", "lib/dir/deeper.sv")
    assert project.settings.lib_dirs == ("lib/dir",)
    assert project.settings.lib_exts == (".sv",)
    assert _tree(project.hierarchy("top")) == [
        "top: rtl/top.sv:top",
        "  u_a: lib/cells.v:cell_a",
        "  u_searched: lib/dir/searched.sv:searched",
        "    u_deeper: lib/dir/deeper.sv:deeper",
        # the extension `.v` is not one of the library
        "  u_nowhere: ?",
        # a module of the design is used, before the one of a library
        "  u_local: rtl/top.sv:local_cell",
    ]
    assert _codes(project) == [
        ("", "filelist-unknown"),
        ("rtl/top.sv", "undefined-module"),
        ("rtl/top.sv", "duplicate-definition"),
        ("lib/cells.v", "duplicate-definition"),
    ]
    assert project.diagnostics[0].file == "design.f"
    assert project.diagnostics[0].loc.line == 7


def test_filelist_library_order(tmp_path):
    """A Library Named First Is Still A Library."""
    _write(tmp_path, {**LIBRARY, "design.f": "-v lib/cells.v\nrtl/top.sv\n"})
    project = Project.from_filelist(tmp_path / "design.f")
    assert [file.file_id for file in project.files] == ["rtl/top.sv", "lib/cells.v"]
    assert project.resolve("local_cell").id == "rtl/top.sv:local_cell"
    assert project.settings.lib_exts == (".v", ".sv")


def test_filelist_defines(tmp_path):
    """The Macros Of A Filelist Are Used By Macro Expansion."""
    _write(tmp_path, LIBRARY)
    project = Project.from_filelist(tmp_path / "design.f", expand_macros=True, resolve_ifdefs=True, defines={"X": "1"})
    assert project.settings.defines == {"WITH_B": "", "X": "1"}
    assert project.settings.inc_dirs == ("inc",)
    assert [(port.name, port.ifdefs) for port in project.files[0].modules[0].ports] == [("b", ()), ("a", ())]
    # without, the condition is kept
    project = Project.from_filelist(tmp_path / "design.f")
    assert [(port.name, port.ifdefs) for port in project.files[0].modules[0].ports] == [("b", ("WITH_B",)), ("a", ())]


def test_filelist_not_found(tmp_path):
    """A Filelist Which Is Not There Is A Project Without Files, With A Diagnostic."""
    project = Project.from_filelist(tmp_path / "none.f")
    assert project.files == ()
    assert [(diag.code, diag.severity) for diag in project.diagnostics] == [("filelist-not-found", "error")]


def test_veer_filelist():
    """A Real Filelist, Without Its Files: Every File Is Part Of The Project, With A Diagnostic."""
    path = CORPUS / "filelists" / "veer_el2" / "flist"
    project = Project.from_filelist(path, env={"RV_ROOT": "/veer"})
    assert project.root == Path(path.anchor) / "veer"
    assert len(project.files) == 56
    assert len(project.libraries) == 4
    assert project.files[0].file_id == "design/lib/el2_assert.sv"
    assert project.settings.defines == {"RV_OPENSOURCE": ""}
    assert project.settings.inc_dirs == ("testbench", "design/include")
    assert project.settings.lib_dirs == ("design/lib",)
    assert {code for _, code in _codes(project)} == {"file-not-found"}
    assert project.tops() == ()

    project = Project.from_filelist(path, env={})
    assert project.files == ()
    assert [(diag.code, diag.loc.line) for diag in project.diagnostics] == [("filelist-variable", 4)]


def test_ibex_dv_filelist(tmp_path):
    """A Real Filelist With Variables: The Files Which Are There Are Parsed, The Others Are Reported."""
    project = Project.from_filelist(IBEX / "ibex_dv.f", env={"PRJ_DIR": str(tmp_path), "LOWRISC_IP_DIR": str(tmp_path)})
    assert len(project.files) == 114
    assert {code for _, code in _codes(project)} == {"file-not-found"}
    # with the directory of the files
    rtl = tmp_path / "rtl"
    rtl.symlink_to(IBEX, target_is_directory=True)
    project = Project.from_filelist(IBEX / "ibex_dv.f", env={"PRJ_DIR": str(tmp_path), "LOWRISC_IP_DIR": str(tmp_path)})
    found = [file for file in project.files if not any(diag.code == "file-not-found" for diag in file.diagnostics)]
    assert len(found) == 24
    assert project.resolve("ibex_core").id == "rtl/ibex_core.sv:ibex_core"
    tree = project.hierarchy("ibex_top", depth=1)
    assert "rtl/ibex_core.sv:ibex_core" in [node.definition for node in tree.children]


# ---------------------------------------------------------------------------------------------------------------------
# cache
# ---------------------------------------------------------------------------------------------------------------------

CACHED = {
    "inc/defs.svh": "`define WIDTH 8\n",
    "rtl/top.sv": (
        '`include "defs.svh"\n`include "later.svh"\nmodule top (input [`WIDTH-1:0] a);\n  leaf u_leaf ();\nendmodule\n'
    ),
    "rtl/leaf.sv": "module leaf; endmodule\n",
}


@fixture
def parsed(monkeypatch):
    """Names Of The Files Which Are Parsed."""
    names = []
    original = project_module.parse_file

    def parse(path, **kwargs):
        names.append(path.name)
        return original(path, **kwargs)

    monkeypatch.setattr(project_module, "parse_file", parse)
    return names


def _cached(tmp_path, **kwargs):
    return Project.from_dir(tmp_path, expand_macros=True, inc_dirs=[tmp_path / "inc"], cache=True, **kwargs)


def test_cache(tmp_path, parsed):
    """Files Are Parsed Once. The Result Is The Same."""
    _write(tmp_path, CACHED)
    plain = Project.from_dir(tmp_path, expand_macros=True, inc_dirs=[tmp_path / "inc"])
    assert plain.file("rtl/top.sv").includes == ("inc/defs.svh",)
    parsed.clear()
    cold = _cached(tmp_path)
    assert parsed == ["leaf.sv", "top.sv"]
    warm = _cached(tmp_path)
    assert parsed == ["leaf.sv", "top.sv"]
    assert plain == cold == warm
    assert warm.file("rtl/top.sv").modules[0].ports[0].dim == "[8-1:0]"
    # the cache is located in the root of the project and never committed
    cache = tmp_path / project_module.CACHE_DIR
    assert (cache / ".gitignore").read_text() == "*\n"
    assert len(list(cache.glob("*.json"))) == 2
    # the cache is no part of the project
    assert [file.file_id for file in warm.files] == ["rtl/leaf.sv", "rtl/top.sv"]


def test_cache_changed_file(tmp_path, parsed):
    """A File Which Changed Is Parsed Again. Just This One."""
    _write(tmp_path, CACHED)
    _cached(tmp_path)
    parsed.clear()
    (tmp_path / "rtl" / "leaf.sv").write_text("module leaf (input a); endmodule\n")
    project = _cached(tmp_path)
    assert parsed == ["leaf.sv"]
    assert [port.name for port in project.file("rtl/leaf.sv").modules[0].ports] == ["a"]
    _cached(tmp_path)
    assert parsed == ["leaf.sv"]


def test_cache_changed_include(tmp_path, parsed):
    """A File Is Parsed Again, If A File It Includes Changed, Or Is There Now."""
    _write(tmp_path, CACHED)
    project = _cached(tmp_path)
    assert [diag.code for diag in project.file("rtl/top.sv").diagnostics] == ["include-not-found"]
    parsed.clear()
    (tmp_path / "inc" / "defs.svh").write_text("`define WIDTH 16\n")
    project = _cached(tmp_path)
    assert parsed == ["top.sv"]
    assert project.file("rtl/top.sv").modules[0].ports[0].dim == "[16-1:0]"
    # the included file which has not been found
    (tmp_path / "inc" / "later.svh").write_text("`undef WIDTH\n`define WIDTH 32\n")
    project = _cached(tmp_path)
    assert parsed == ["top.sv", "top.sv"]
    assert project.file("rtl/top.sv").modules[0].ports[0].dim == "[32-1:0]"
    assert project.file("rtl/top.sv").includes == ("inc/defs.svh", "inc/later.svh")
    assert project.file("rtl/top.sv").diagnostics == ()
    _cached(tmp_path)
    assert parsed == ["top.sv", "top.sv"]


def test_cache_changed_settings(tmp_path, parsed):
    """All Files Are Parsed Again, If They Are Parsed In Another Way."""
    _write(tmp_path, CACHED)
    _cached(tmp_path)
    parsed.clear()
    _cached(tmp_path, defines={"X": "1"})
    assert parsed == ["leaf.sv", "top.sv"]
    _cached(tmp_path, defines={"X": "2"})
    assert parsed == ["leaf.sv", "top.sv"] * 2
    Project.from_dir(tmp_path, cache=True)
    assert parsed == ["leaf.sv", "top.sv"] * 3
    # each way has its own results
    _cached(tmp_path)
    _cached(tmp_path, defines={"X": "1"})
    assert parsed == ["leaf.sv", "top.sv"] * 3


def test_cache_broken(tmp_path, parsed):
    """A Broken Cache Is No Cache. Files Which Cannot Be Read Are Not Kept."""
    _write(tmp_path, CACHED)
    cache = tmp_path / "my-cache"
    paths = [tmp_path / "rtl" / "leaf.sv", tmp_path / "rtl" / "none.sv"]
    project = Project.from_files(paths, root=tmp_path, cache=cache)
    assert parsed == ["leaf.sv", "none.sv"]
    assert len(list(cache.glob("*.json"))) == 1
    next(cache.glob("*.json")).write_text("{ broken")
    assert Project.from_files(paths, root=tmp_path, cache=str(cache)) == project
    assert parsed == ["leaf.sv", "none.sv"] * 2
    damaged = ("[1]", '{"file": {"path": "rtl/leaf.sv"}, "depends": 1}', '{"file": 1, "depends": {}}')
    for number, text in enumerate(damaged):
        next(cache.glob("*.json")).write_text(text)
        assert Project.from_files(paths, root=tmp_path, cache=cache) == project
        assert parsed == ["leaf.sv", "none.sv"] * (number + 3)
    # a directory which cannot be created
    (tmp_path / "file").write_text("")
    assert Project.from_files(paths, root=tmp_path, cache=tmp_path / "file" / "cache") == project


def test_cache_parser_version(tmp_path, parsed, monkeypatch):
    """A Change Of The Parser Makes All Results Invalid."""
    _write(tmp_path, CACHED)
    _cached(tmp_path)
    parsed.clear()
    monkeypatch.setattr(project_module, "_parser_version", lambda: "another")
    _cached(tmp_path)
    assert parsed == ["leaf.sv", "top.sv"]


@mark.parametrize("path", PROJECT_DIRS, ids=lambda path: f"{path.parent.name}/{path.name}")
def test_cache_corpus(tmp_path, path, parsed):
    """Real Projects: The Result From The Cache Is The Same, With And Without Macro Expansion."""
    logging.disable(logging.WARNING)
    try:
        for kwargs in (
            {},
            {"expand_macros": True, "resolve_ifdefs": True, "inc_dirs": [path.parent, path / "include"]},
        ):
            plain = Project.from_dir(path, **kwargs)
            parsed.clear()
            assert Project.from_dir(path, cache=tmp_path, **kwargs) == plain
            assert len(parsed) == len(plain.files)
            assert Project.from_dir(path, cache=tmp_path, **kwargs) == plain
            assert len(parsed) == len(plain.files)
    finally:
        logging.disable(logging.NOTSET)


# ---------------------------------------------------------------------------------------------------------------------
# jobs
# ---------------------------------------------------------------------------------------------------------------------


def _many(tmp_path) -> None:
    """Enough Files For Several Processes. With Diagnostics And An Include."""
    files = {f"rtl/mod{idx}.sv": f"module mod{idx} (input logic clk);\nendmodule\n" for idx in range(30)}
    files["rtl/top.sv"] = '`include "defs.svh"\n`include "nowhere.svh"\nmodule top (input [`WIDTH-1:0] a);\nendmodule\n'
    files["rtl/empty.sv"] = "// nothing\n"
    files["inc/defs.svh"] = "`define WIDTH 8\n"
    _write(tmp_path, files)


def _jobs(tmp_path, jobs, **kwargs):
    """Project Of All Files, And One Which Is Not There."""
    paths = [*sorted(tmp_path.glob("rtl/*.sv")), tmp_path / "rtl" / "missing.sv"]
    kwargs.update(root=tmp_path, expand_macros=True, inc_dirs=[tmp_path / "inc"], jobs=jobs)
    return Project.from_files(paths, **kwargs)


def _messages(caplog) -> list[tuple[int, str]]:
    records = caplog.records
    return [(record.levelno, record.getMessage()) for record in records if record.name == "hdl_parser._diagnostics"]


@mark.parametrize("jobs", (2, None))
def test_jobs(tmp_path, caplog, monkeypatch, jobs):
    """Several Processes Give The Same Result And The Same Messages."""
    monkeypatch.setattr(project_module, "_cpu_count", lambda: 3)
    _many(tmp_path)
    with caplog.at_level(logging.DEBUG, logger="hdl_parser._diagnostics"):
        serial = _jobs(tmp_path, 1)
    expected = _messages(caplog)
    assert any("nowhere.svh" in message for _, message in expected)
    assert any(message == "rtl/missing.sv: file not found." for _, message in expected)
    caplog.clear()

    pools = []
    original = project_module.ProcessPoolExecutor

    def executor(*args, **kwargs):
        pools.append(args[0])
        return original(*args, **kwargs)

    monkeypatch.setattr(project_module, "ProcessPoolExecutor", executor)
    with caplog.at_level(logging.DEBUG, logger="hdl_parser._diagnostics"):
        parallel = _jobs(tmp_path, jobs)
    assert pools == [jobs or 3]
    assert parallel == serial
    assert _messages(caplog) == expected


def test_jobs_few_files(tmp_path, monkeypatch):
    """A Few Files Are Parsed By This Process."""
    monkeypatch.setattr(project_module, "ProcessPoolExecutor", None)
    _write(tmp_path, FILES)
    assert len(Project.from_dir(tmp_path, jobs=8).files) == len(FILES)


def test_jobs_cache(tmp_path, parsed):
    """Files Parsed By Several Processes Are Kept. The Next Run Needs None."""
    _many(tmp_path)
    cold = _jobs(tmp_path, 2, cache=True)
    assert parsed == []  # parsed by the other processes
    warm = _jobs(tmp_path, 2, cache=True)
    # the file which is not there is never kept
    assert parsed == ["missing.sv"]
    assert cold == warm == _jobs(tmp_path, 1)


def test_jobs_no_processes(tmp_path, monkeypatch):
    """Without Processes The Files Are Parsed By This One."""

    def executor(*args, **kwargs):
        raise OSError("no processes")

    monkeypatch.setattr(project_module, "ProcessPoolExecutor", executor)
    _many(tmp_path)
    assert _jobs(tmp_path, 2) == _jobs(tmp_path, 1)


def test_cpu_count(monkeypatch):
    """Number Of CPUs."""
    assert project_module._cpu_count() >= 1
    monkeypatch.delattr(project_module.os, "sched_getaffinity", raising=False)
    monkeypatch.setattr(project_module.os, "cpu_count", lambda: None)
    assert project_module._cpu_count() == 1
