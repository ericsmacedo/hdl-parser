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
"""Test Parser."""

from pathlib import Path

from hdl_parser import parse_filelist
from hdl_parser.filelistparser import read_filelist

from .conftest import PRJ_PATH


def test_filelistparser(examples):
    """Test FileList Parser."""
    filelist = examples / "sv" / "filelist.f"
    filepaths = []
    incdirs = []
    parse_filelist(filepaths, incdirs, filelist)
    assert filepaths == [
        examples / "sv" / "adder.sv",
        examples / "sv" / "instances_example.sv",
        examples / "sv" / "packed_unpacked.sv",
        examples / "sv" / "bcd_adder.sv",
    ]
    assert incdirs == [examples / "sv" / "inc"]


def test_filelistparser_rel(examples):
    """Test FileList Parser."""
    examples = examples.relative_to(Path().resolve())
    filelist = examples / "sv" / "filelist.f"
    filepaths = []
    incdirs = []
    parse_filelist(filepaths, incdirs, filelist)
    assert filepaths == [
        examples / "sv" / "adder.sv",
        examples / "sv" / "instances_example.sv",
        examples / "sv" / "packed_unpacked.sv",
        examples / "sv" / "bcd_adder.sv",
    ]
    assert incdirs == [examples / "sv" / "inc"]


FILELISTS = PRJ_PATH / "tests" / "corpus" / "filelists"
IBEX = PRJ_PATH / "tests" / "corpus" / "sv" / "ibex"


def _codes(filelist) -> list[tuple[str, int]]:
    return [(diag.code, diag.loc.line if diag.loc else 0) for diag in filelist.diagnostics]


def test_read_filelist(tmp_path):
    """Files, Include Directories, Macros And Libraries."""
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "sub.f").write_text("sub.sv\n+incdir+inc\n-F ../design.f\n")
    (tmp_path / "design.f").write_text(
        """\
// comment
# comment
rtl/top.sv   // trailing comment
"rtl/with space.sv"
rtl/top.sv
+incdir+inc1+inc2
-incdir inc3
-I inc1
+define+SYNTHESIS+WIDTH=8+EXPR=(1+2)
-define TECH=generic
-D EMPTY
-sv rtl/sv.sv -v2k
-v lib/cells.v
-y lib/dir -y lib/other
+libext+.v+.sv+
-f sub/sub.f
"""
    )
    filelist = read_filelist(tmp_path / "design.f")
    assert filelist.files == [
        tmp_path / "rtl" / "top.sv",
        tmp_path / "rtl" / "with space.sv",
        tmp_path / "rtl" / "sv.sv",
        tmp_path / "sub" / "sub.sv",
    ]
    assert filelist.inc_dirs == [tmp_path / "inc1", tmp_path / "inc2", tmp_path / "inc3", tmp_path / "sub" / "inc"]
    # a `+` ends a value
    assert filelist.defines == {"SYNTHESIS": "", "WIDTH": "8", "EXPR": "(1", "2)": "", "TECH": "generic", "EMPTY": ""}
    assert filelist.lib_files == [tmp_path / "lib" / "cells.v"]
    assert filelist.lib_dirs == [tmp_path / "lib" / "dir", tmp_path / "lib" / "other"]
    assert filelist.lib_exts == [".v", ".sv"]
    # a filelist naming itself is read once
    assert filelist.diagnostics == []


def test_read_filelist_variables(tmp_path):
    """Environment Variables. A Variable Which Is Not Defined Is Reported Once."""
    (tmp_path / "design.f").write_text(
        "$ROOT/a.sv\n${ROOT}/b.sv\n$(ROOT)/c.sv\n$NONE/d.sv\n+incdir+${NONE}/inc\n$OTHER/e.sv\n"
    )
    filelist = read_filelist(tmp_path / "design.f", env={"ROOT": "/root"})
    assert [path.as_posix() for path in filelist.files] == ["/root/a.sv", "/root/b.sv", "/root/c.sv"]
    assert filelist.inc_dirs == []
    assert _codes(filelist) == [("filelist-variable", 4), ("filelist-variable", 6)]
    diag = filelist.diagnostics[0]
    assert diag.message == "environment variable 'NONE' is not defined. All lines using it are skipped."
    assert (diag.severity, diag.file, diag.loc.end_col) == ("warning", str(tmp_path / "design.f"), 11)


def test_read_filelist_environment(tmp_path, monkeypatch):
    """The Environment Of The Process Is Used By Default."""
    monkeypatch.setenv("HDL_PARSER_TEST_ROOT", "/from/env")
    (tmp_path / "design.f").write_text("$HDL_PARSER_TEST_ROOT/a.sv\n")
    assert read_filelist(tmp_path / "design.f").files == [Path("/from/env/a.sv")]


def test_read_filelist_problems(tmp_path, caplog):
    """Everything Which Is Not Understood Is Reported."""
    (tmp_path / "design.f").write_text(
        '-timescale 1ns/1ps\n+nowarn+ABC\n-work lib a.sv\n-unknown\n-f none.f\n"unbalanced a.sv\n-top top b.sv -x +y\n'
    )
    filelist = read_filelist(tmp_path / "design.f")
    # the argument of an option which is not known is no file, unless it looks like one
    assert [path.name for path in filelist.files] == ["a.sv", '"unbalanced', "b.sv"]
    assert _codes(filelist) == [
        ("filelist-unknown", 1),
        ("filelist-unknown", 2),
        ("filelist-unknown", 3),
        ("filelist-unknown", 4),
        ("filelist-not-found", 5),
        ("filelist-unknown", 7),
        ("filelist-unknown", 7),
        ("filelist-unknown", 7),
    ]
    assert filelist.diagnostics[0].message == "option '-timescale' is not understood."
    assert filelist.diagnostics[4].severity == "error"
    assert "design.f:1:1: " in caplog.text
    missing = read_filelist(tmp_path / "none.f")
    assert _codes(missing) == [("filelist-not-found", 0)]
    assert missing.files == []


def test_veer_filelist():
    """A Real Filelist With Macros, Include Directories, Library Files And Directories."""
    filelist = read_filelist(FILELISTS / "veer_el2" / "flist", env={"RV_ROOT": "/veer"})
    assert filelist.diagnostics == []
    assert len(filelist.files) == 52
    assert filelist.files[0] == Path("/veer/design/lib/el2_assert.sv")
    assert filelist.defines == {"RV_OPENSOURCE": ""}
    assert filelist.inc_dirs == [Path("/veer/testbench"), Path("/veer/design/include")]
    assert [path.name for path in filelist.lib_files] == [
        "beh_lib.sv",
        "mem_lib.sv",
        "axi_lsu_dma_bridge.sv",
        "user_cells.sv",
    ]
    assert filelist.lib_dirs == [Path("/veer/design/lib")]
    assert filelist.lib_exts == [".v", ".sv"]
    # the library directory within a comment is none
    assert "SYNOPSYS_SYN_ROOT" in (FILELISTS / "veer_el2" / "flist").read_text()

    undefined = read_filelist(FILELISTS / "veer_el2" / "flist", env={})
    assert _codes(undefined) == [("filelist-variable", 4)]
    assert undefined.files == []
    assert undefined.defines == {"RV_OPENSOURCE": ""}


def test_cva6_filelist():
    """A Real Filelist Naming Another One, Which Is Not There."""
    env = {"CVA6_REPO_DIR": "/cva6", "TARGET_CFG": "cv64a6", "HPDCACHE_DIR": "/hpdcache"}
    filelist = read_filelist(FILELISTS / "cva6" / "Flist.cva6", env=env)
    assert len(filelist.files) == 131
    assert len(filelist.inc_dirs) == 5
    assert Path("/cva6/core/include/cv64a6_config_pkg.sv") in filelist.files
    assert _codes(filelist) == [("filelist-not-found", 162)]
    assert "/hpdcache/rtl/hpdcache.Flist" in filelist.diagnostics[0].message


def test_ibex_filelists():
    """Real Filelists: Plain Names, And Variables With Include Directories."""
    core = read_filelist(IBEX / "ibex_core.f")
    assert core.diagnostics == []
    assert len(core.files) == 17
    assert all(path.is_file() for path in core.files)
    dv = read_filelist(IBEX / "ibex_dv.f", env={"PRJ_DIR": "/ibex", "LOWRISC_IP_DIR": "/lowrisc"})
    assert dv.diagnostics == []
    assert (len(dv.files), len(dv.inc_dirs)) == (114, 18)
    assert dv.files[0] == Path("/lowrisc/ip/prim_generic/rtl/prim_pkg.sv")
