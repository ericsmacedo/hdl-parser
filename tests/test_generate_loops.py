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

"""Unrolled `for` Generate Constructs Of Real Designs (The Corpus)."""

from pytest import fixture, mark, raises

from hdl_parser import Project
from hdl_parser._conn import base_key

from .conftest import PRJ_PATH

CORPUS = PRJ_PATH / "tests" / "corpus"
REGFILE = "ibex_register_file_ff.g_plain_rf"


@fixture(scope="module")
def ibex() -> Project:
    """The ibex core."""
    return Project.from_dir(CORPUS / "sv" / "ibex")


@fixture(scope="module")
def common_cells() -> Project:
    """The common cells."""
    return Project.from_dir(CORPUS / "sv" / "common_cells")


@fixture(scope="module")
def surf() -> Project:
    """The SURF library."""
    return Project.from_dir(CORPUS / "vhdl" / "surf")


def _ranges(project: Project, top: str, params: dict, path: str, ctx: dict | None = None):
    conn = project._connectivity(params)
    return conn.loop_range(conn.top(top), path, ctx or {})


@mark.parametrize(
    ("corpus", "top", "params", "path", "ctx", "expected"),
    (
        # start at 1, a parameter as bound
        ("sv/ibex", "ibex_register_file_ff", {}, "g_plain_rf.g_rf_flops", {}, tuple(range(1, 32))),
        ("sv/ibex", "ibex_register_file_ff", {"RV32E": 1}, "g_plain_rf.g_rf_flops", {}, tuple(range(1, 16))),
        # start by an expression of parameters, nested in another loop
        ("sv/ibex", "ibex_pmp", {}, "g_addr_exp.g_bitmask", {"g_addr_exp": 0}, tuple(range(2, 34))),
        ("sv/ibex", "ibex_pmp", {"PMPGranularity": 3}, "g_addr_exp.g_bitmask", {}, tuple(range(5, 34))),
        ("sv/ibex", "ibex_pmp", {"PMPNumRegions": 16}, "g_addr_exp", {}, tuple(range(16))),
        ("sv/ibex", "ibex_pmp", {}, "g_access_check.g_regions", {"g_access_check": 1}, (0, 1, 2, 3)),
        # `i = i + 1`, bound by a conditional operator
        ("sv/ibex", "ibex_core", {}, "g_rvfi_stages", {}, (0,)),
        ("sv/ibex", "ibex_core", {"WritebackStage": 1}, "g_rvfi_stages", {}, (0, 1)),
        # a cast in the condition, the bound depends on the variable of the outer loop
        ("sv/common_cells", "lzc", {"WIDTH": 8}, "gen_lzc.g_levels", {}, (0, 1, 2)),
        ("sv/common_cells", "lzc", {"WIDTH": 8}, "gen_lzc.g_index_lut", {}, tuple(range(8))),
        *(
            (
                "sv/common_cells",
                "lzc",
                {"WIDTH": 8},
                "gen_lzc.g_levels.g_not_last_level.g_level",
                {"gen_lzc.g_levels": level},
                tuple(range(2**level)),
            )
            for level in range(3)
        ),
        ("sv/common_cells", "rr_arb_tree", {"NumIn": 8}, "gen_arbiter.gen_levels", {}, (0, 1, 2)),
        ("sv/common_cells", "cdc_fifo_gray_src", {"LOG_DEPTH": 4}, "gen_sync", {}, tuple(range(5))),
        ("sv/common_cells", "id_queue", {}, "gen_lookup.gen_mask", {}, tuple(range(32))),
        # `<=`
        ("sv/opentitan", "prim_arbiter_ppc", {"N": 4}, "gen_fairness", {}, (1, 2, 3, 4)),
        # VHDL: `to`, `downto`
        ("vhdl/potato", "pp_soc_gpio", {"NUM_GPIOS": 4}, "io_setup", {}, (0, 1, 2, 3)),
        ("vhdl/surf", "ClockManager7", {"NUM_CLOCKS_G": 3}, "rstoutgen", {}, (2, 1, 0)),
        ("vhdl/surf", "Jesd204bRx", {"L_G": 2}, "generaterxlanes", {}, (1, 0)),
        # bound by a constant computed by a function: not known
        ("vhdl/poc", "arith_addw", {}, "genblocks", {}, None),
    ),
)
def test_ranges(corpus, top, params, path, ctx, expected):  # noqa: PLR0913
    """Indices Of Real Loops."""
    project = Project.from_dir(CORPUS / corpus)
    assert _ranges(project, top, params, path, ctx) == expected


def test_register_file(ibex):
    """Signals Declared Within A Loop: One Per Iteration, The Index Is Checked."""
    (reset, write) = ibex.drivers(f"{REGFILE}.g_rf_flops[5].rf_reg_q")
    assert (reset.kind, reset.nets) == ("ff", ())
    assert (write.kind, write.nets, write.multiple) == ("ff", ("ibex_register_file_ff.wdata_a_i",), False)
    assert write.conds == ("ibex_register_file_ff.rst_ni", f"{REGFILE}.we_a_dec")
    with raises(ValueError, match=r"has no index 0: the indices are 1\.\.31"):
        ibex.drivers(f"{REGFILE}.g_rf_flops[0].rf_reg_q")
    with raises(ValueError, match="has no index 32"):
        ibex.drivers(f"{REGFILE}.g_rf_flops[32].rf_reg_q")
    with raises(ValueError, match="has no index 16"):
        ibex.drivers(f"{REGFILE}.g_rf_flops[16].rf_reg_q", params={"RV32E": 1})
    # from the loop to the signal outside: one load per iteration
    assert [link.nets for link in ibex.loads(f"{REGFILE}.g_rf_flops[5].rf_reg_q")] == [(f"{REGFILE}.rf_reg",)]
    # into the loop from outside: all iterations, told apart
    (link,) = ibex.loads("ibex_register_file_ff.wdata_a_i")
    assert link.nets == tuple(f"{REGFILE}.g_rf_flops[{index}].rf_reg_q" for index in range(1, 32))
    assert not link.multiple
    (by_loop, _) = ibex.drivers(f"{REGFILE}.rf_reg")
    assert len(by_loop.nets) == 31
    assert [hop.net for hop in ibex.trace("ibex_register_file_ff.wdata_a_i", f"{REGFILE}.g_rf_flops[7].rf_reg_q")] == [
        "ibex_register_file_ff.wdata_a_i",
        f"{REGFILE}.g_rf_flops[7].rf_reg_q",
    ]
    # without index: all iterations at once
    (_, write) = ibex.drivers(f"{REGFILE}.g_rf_flops.rf_reg_q")
    assert write.multiple


@mark.parametrize(
    ("width", "expected"),
    (
        # last level: two inputs per node, the others: the nodes below
        (8, [("lzc.gen_lzc.in_tmp",), ("lzc.gen_lzc.sel_nodes",)]),
        # a single input left over: `g_base`
        (7, [("lzc.gen_lzc.in_tmp",), ("lzc.gen_lzc.in_tmp",), ("lzc.gen_lzc.sel_nodes",)]),
        # out of range: `g_out_of_range` assigns a constant
        (6, [("lzc.gen_lzc.in_tmp",), (), ("lzc.gen_lzc.sel_nodes",)]),
        # a single level: the last one only
        (2, [("lzc.gen_lzc.in_tmp",)]),
    ),
)
def test_conditions_by_iteration(common_cells, width, expected):
    """`if` Generate Constructs Within Nested Loops Depend On The Variables Of The Loops."""
    links = common_cells.drivers("lzc.gen_lzc.sel_nodes", params={"WIDTH": width})
    assert [link.nets for link in links] == expected


def test_instances_in_loop(common_cells):
    """Instances Within A Loop: One Per Iteration, Not Connected To Each Other."""
    src = "cdc_fifo_gray_src"
    (link,) = common_cells.drivers(f"{src}.rptr")
    assert link.nets == tuple(f"{src}.gen_sync[{index}].i_sync.serial_o" for index in range(4))
    (link,) = common_cells.drivers(f"{src}.rptr", params={"LOG_DEPTH": 1})
    assert len(link.nets) == 2
    hops = common_cells.trace(f"{src}.async_rptr_i", f"{src}.gen_sync[2].i_sync.serial_o", through_regs=True)
    assert [hop.net for hop in hops] == [
        f"{src}.async_rptr_i",
        f"{src}.gen_sync[2].i_sync.serial_i",
        f"{src}.gen_sync[2].i_sync.reg_q",
        f"{src}.gen_sync[2].i_sync.serial_o",
    ]
    other = f"{src}.gen_sync[0].i_sync.serial_o"
    assert common_cells.trace(f"{src}.gen_sync[1].i_sync.serial_i", other, through_regs=True) == ()
    (link,) = common_cells.drivers(f"{src}.gen_sync[3].i_sync.serial_i")
    assert (link.kind, link.nets) == ("port", (f"{src}.async_rptr_i",))
    with raises(ValueError, match=r"'cdc_fifo_gray_src\.gen_sync' has no index 9: the indices are 0\.\.3"):
        common_cells.drivers(f"{src}.gen_sync[9].i_sync.serial_o")


def test_vhdl(surf):
    """VHDL: Indices In Parentheses, `downto`, Instances Of Undefined Entities."""
    with raises(ValueError, match=r"has no index 2: the indices are 0\.\.1"):
        surf.drivers("Jesd204bRx.generateRxLanes(2).JesdRx_INST.nSync_o", params={"L_G": 2})
    (link,) = surf.drivers("Jesd204bRx.s_nSyncVecEn", params={"L_G": 2})
    assert link.nets == ("Jesd204bRx.s_nSyncVec", "Jesd204bRx.s_enableRx")
    # the bound is a generic without default: an index which cannot be checked is taken
    poc = Project.from_dir(CORPUS / "vhdl" / "poc")
    (link,) = poc.drivers("arith_addw.genBlocks(5).aa")
    assert link.nets == ("arith_addw.a",)
    with raises(ValueError, match=r"has no index 4: the indices are 1\.\.3"):
        poc.drivers("arith_addw.genBlocks(4).aa", params={"K": 4, "N": 32})


def test_vhdl_instances_in_loop():
    """The Variable Of The Loop Is Handed To The Instance Of Every Iteration (microwatt: One Core Per CPU)."""
    project = Project.from_dir(CORPUS / "vhdl" / "microwatt")
    conn = project._connectivity({"NCPUS": 2})
    for index in (0, 1):
        inst, _ = conn.locate(f"soc.processors({index}).core.clk")
        assert inst.path == f"soc.processors[{index}].core"
        assert inst.scope.value_of("CPU_INDEX").value == index
        assert not inst.multiple
    with raises(ValueError, match=r"'soc\.processors' has no index 2: the indices are 0\.\.1"):
        project.drivers("soc.processors(2).msgin", params={"NCPUS": 2})
    (link,) = project.drivers("soc.processors(1).msgin", params={"NCPUS": 2})
    assert link.nets == ("soc.processors[1].#process2.m",)
    (link,) = project.drivers("soc.processors(1).core.rst", params={"NCPUS": 2})
    assert (link.kind, link.nets) == ("port", ("soc.rst_core",))


def _loop_signals(project: Project):
    """Signals of the corpus, which are located in labeled loops: definition, base key and loop paths."""
    for definition in project._all_modules:
        graph = project._graph(definition)
        for key, net in graph.nets.items():
            loops = [path for path in graph.loops if key.startswith(f"{path}.")]
            if net.kind == "signal" and net.unrolled and loops:
                yield definition, key, loops


# Values of generics without default
_PARAMS = {"arith_addw": {"K": 4, "N": 32}, "arith_counter_bcd": {"DIGITS": 3}}


@mark.parametrize(
    ("corpus", "number"),
    (("sv/ibex", 9), ("sv/common_cells", 3), ("sv/opentitan", 2), ("vhdl/poc", 8), ("vhdl/microwatt", 1)),
)
def test_all_loops(corpus, number):
    """Every Signal Within A Loop Of The Corpus: The First Iteration, Without Index, Drivers And Loads."""
    project = Project.from_dir(CORPUS / corpus)
    checked = 0
    for definition, key, loops in _loop_signals(project):
        conn = project._connectivity(_PARAMS.get(definition.unit.name, {}))
        top = conn.top(definition.id)
        graph = conn.graph(definition)
        ctx: dict[str, int] = {}
        for path in loops:
            found = conn.loop_range(top, path, ctx)
            if not found:
                break
            ctx[path] = found[0]
        else:
            name = graph.nets[key].name
            indexed = conn.concrete(top, key, ctx)
            node = conn.locate(f"{definition.id}.{_with_indices(name, indexed)}")
            assert node[1] == indexed
            assert not conn.multiple(node)
            for step in (*conn.drivers(node), *conn.loads(node)):
                conn.link(node, step, driver=True)
            # the same signal without index stands for all iterations
            unindexed = conn.locate(f"{definition.id}.{name}")
            assert base_key(unindexed[1]) == key
            assert conn.multiple(unindexed)
            list(conn.drivers(unindexed))
            list(conn.loads(unindexed))
            checked += 1
    assert checked == number


def _with_indices(name: str, key: str) -> str:
    """`name` with the indices of `key`: `g[0].data`."""
    return ".".join(
        part + key_part[len(part) :] if key_part.lower().startswith(part.lower()) else part
        for part, key_part in zip(name.split("."), key.split("."), strict=True)
    )
