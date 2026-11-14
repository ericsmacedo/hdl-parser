# SystemVerilog Test Corpus

Unmodified third-party SystemVerilog files used as a safety net for tokenizer and parser changes. Every `*.sv` file is
snapshot-tested (`tests/test_sv_corpus.py::test_corpus_snapshot`, reference data in
`tests/refdata/tests.test_sv_corpus/`) and checked against structural invariants (`tests/sv_invariants.py`).
Known parser bugs are tracked in `KNOWN_ISSUES` in `tests/test_sv_corpus.py` as strict xfails.

With macro expansion, the changes made by the preprocessor are compared with reference data too
(`tests/test_sv_corpus.py::test_corpus_expand` and `test_corpus_resolve`). The macro files of the projects are
located in the `include` directory of each project. They have been retrieved on 2026-11-14, from the same refs.

The files are kept byte-for-byte as downloaded, including their license headers, and are excluded from all
pre-commit hooks. Retrieval date for everything: 2026-11-13. The license text of each project is stored next to its files.

## common_cells

- URL: <https://github.com/pulp-platform/common_cells>
- Ref: tag `v1.37.0`
- License: Solderpad Hardware License v0.51 (`LICENSE`)
- Retrieved: 2026-11-13

| File | Size (bytes) | Upstream path |
|---|---|---|
| `common_cells/binary_to_gray.sv` | 904 | `src/binary_to_gray.sv` |
| `common_cells/cdc_2phase.sv` | 6450 | `src/cdc_2phase.sv` |
| `common_cells/cdc_fifo_gray.sv` | 10696 | `src/cdc_fifo_gray.sv` |
| `common_cells/clk_int_div.sv` | 16315 | `src/clk_int_div.sv` |
| `common_cells/counter.sv` | 1584 | `src/counter.sv` |
| `common_cells/delta_counter.sv` | 2789 | `src/delta_counter.sv` |
| `common_cells/edge_detect.sv` | 1298 | `src/edge_detect.sv` |
| `common_cells/exp_backoff.sv` | 3477 | `src/exp_backoff.sv` |
| `common_cells/fifo_v3.sv` | 6425 | `src/fifo_v3.sv` |
| `common_cells/gray_to_binary.sv` | 943 | `src/gray_to_binary.sv` |
| `common_cells/id_queue.sv` | 17858 | `src/id_queue.sv` |
| `common_cells/lzc.sv` | 4394 | `src/lzc.sv` |
| `common_cells/onehot_to_bin.sv` | 1559 | `src/onehot_to_bin.sv` |
| `common_cells/popcount.sv` | 1658 | `src/popcount.sv` |
| `common_cells/registers.svh` | 12202 | `include/common_cells/registers.svh` |
| `common_cells/rr_arb_tree.sv` | 15263 | `src/rr_arb_tree.sv` |
| `common_cells/rstgen.sv` | 1168 | `src/rstgen.sv` |
| `common_cells/rstgen_bypass.sv` | 2253 | `src/rstgen_bypass.sv` |
| `common_cells/shift_reg.sv` | 1277 | `src/shift_reg.sv` |
| `common_cells/spill_register.sv` | 1381 | `src/spill_register.sv` |
| `common_cells/stream_arbiter.sv` | 2062 | `src/stream_arbiter.sv` |
| `common_cells/stream_demux.sv` | 1543 | `src/stream_demux.sv` |
| `common_cells/stream_fifo.sv` | 2593 | `src/stream_fifo.sv` |
| `common_cells/stream_mux.sv` | 1778 | `src/stream_mux.sv` |
| `common_cells/stream_register.sv` | 1759 | `src/stream_register.sv` |
| `common_cells/sync.sv` | 1269 | `src/sync.sv` |

Macro files, for the macro expansion (include directory `common_cells/include`):

| File | Size (bytes) | Upstream path |
|---|---|---|
| `common_cells/include/common_cells/assertions.svh` | 9449 | `include/common_cells/assertions.svh` |

## axi

- URL: <https://github.com/pulp-platform/axi>
- Ref: tag `v0.39.6`
- License: Solderpad Hardware License v0.51 (`LICENSE`)
- Retrieved: 2026-11-13

| File | Size (bytes) | Upstream path |
|---|---|---|
| `axi/axi_cut.sv` | 8654 | `src/axi_cut.sv` |
| `axi/axi_demux.sv` | 11100 | `src/axi_demux.sv` |
| `axi/axi_err_slv.sv` | 8507 | `src/axi_err_slv.sv` |
| `axi/axi_id_prepend.sv` | 8484 | `src/axi_id_prepend.sv` |
| `axi/axi_to_axi_lite.sv` | 12317 | `src/axi_to_axi_lite.sv` |

Macro files, for the macro expansion (include directory `axi/include`):

| File | Size (bytes) | Upstream path |
|---|---|---|
| `axi/include/axi/assign.svh` | 43285 | `include/axi/assign.svh` |
| `axi/include/axi/typedef.svh` | 14368 | `include/axi/typedef.svh` |

## ibex

- URL: <https://github.com/lowRISC/ibex>
- Ref: commit `3d524f19ee8e464b3fb0e29c77dc9ff45934815a` (master at retrieval; the repository has no suitable release tag)
- License: Apache License 2.0 (`LICENSE`)
- Retrieved: 2026-11-13

| File | Size (bytes) | Upstream path |
|---|---|---|
| `ibex/ibex_alu.sv` | 30480 | `rtl/ibex_alu.sv` |
| `ibex/ibex_branch_predict.sv` | 3351 | `rtl/ibex_branch_predict.sv` |
| `ibex/ibex_core.sv` | 111308 | `rtl/ibex_core.sv` |
| `ibex/ibex_counter.sv` | 3465 | `rtl/ibex_counter.sv` |
| `ibex/ibex_csr.sv` | 1289 | `rtl/ibex_csr.sv` |
| `ibex/ibex_dummy_instr.sv` | 5472 | `rtl/ibex_dummy_instr.sv` |
| `ibex/ibex_fetch_fifo.sv` | 10874 | `rtl/ibex_fetch_fifo.sv` |
| `ibex/ibex_multdiv_fast.sv` | 18521 | `rtl/ibex_multdiv_fast.sv` |
| `ibex/ibex_pkg.sv` | 24000 | `rtl/ibex_pkg.sv` |
| `ibex/ibex_pmp.sv` | 13587 | `rtl/ibex_pmp.sv` |
| `ibex/ibex_prefetch_buffer.sv` | 9716 | `rtl/ibex_prefetch_buffer.sv` |
| `ibex/ibex_register_file_ff.sv` | 12558 | `rtl/ibex_register_file_ff.sv` |
| `ibex/ibex_top.sv` | 67606 | `rtl/ibex_top.sv` |
| `ibex/ibex_wb_stage.sv` | 13833 | `rtl/ibex_wb_stage.sv` |

Macro files, for the macro expansion (include directory `ibex/include`):

| File | Size (bytes) | Upstream path |
|---|---|---|
| `ibex/include/dv_fcov_macros.svh` | 4202 | `vendor/lowrisc_ip/dv/sv/dv_utils/dv_fcov_macros.svh` |
| `ibex/include/prim_assert.sv` | 9966 | `vendor/lowrisc_ip/ip/prim/rtl/prim_assert.sv` |
| `ibex/include/prim_assert_dummy_macros.svh` | 1102 | `vendor/lowrisc_ip/ip/prim/rtl/prim_assert_dummy_macros.svh` |
| `ibex/include/prim_assert_sec_cm.svh` | 7571 | `vendor/lowrisc_ip/ip/prim/rtl/prim_assert_sec_cm.svh` |
| `ibex/include/prim_assert_standard_macros.svh` | 6761 | `vendor/lowrisc_ip/ip/prim/rtl/prim_assert_standard_macros.svh` |
| `ibex/include/prim_assert_yosys_macros.svh` | 2709 | `vendor/lowrisc_ip/ip/prim/rtl/prim_assert_yosys_macros.svh` |
| `ibex/include/prim_flop_macros.sv` | 3576 | `vendor/lowrisc_ip/ip/prim/rtl/prim_flop_macros.sv` |

## opentitan

- URL: <https://github.com/lowRISC/opentitan>
- Ref: tag `Earlgrey-PROD-M6-RC7`
- License: Apache License 2.0 (`LICENSE`)
- Retrieved: 2026-11-13

| File | Size (bytes) | Upstream path |
|---|---|---|
| `opentitan/prim_arbiter_ppc.sv` | 7782 | `hw/ip/prim/rtl/prim_arbiter_ppc.sv` |
| `opentitan/prim_edge_detector.sv` | 1297 | `hw/ip/prim/rtl/prim_edge_detector.sv` |
| `opentitan/prim_fifo_async.sv` | 9866 | `hw/ip/prim/rtl/prim_fifo_async.sv` |
| `opentitan/prim_fifo_sync.sv` | 4600 | `hw/ip/prim/rtl/prim_fifo_sync.sv` |
| `opentitan/prim_lfsr.sv` | 25251 | `hw/ip/prim/rtl/prim_lfsr.sv` |
| `opentitan/prim_packer.sv` | 11887 | `hw/ip/prim/rtl/prim_packer.sv` |
| `opentitan/prim_pulse_sync.sv` | 3245 | `hw/ip/prim/rtl/prim_pulse_sync.sv` |
| `opentitan/prim_subreg.sv` | 1841 | `hw/ip/prim/rtl/prim_subreg.sv` |
| `opentitan/prim_sync_reqack.sv` | 11858 | `hw/ip/prim/rtl/prim_sync_reqack.sv` |

Macro files, for the macro expansion (include directory `opentitan/include`):

| File | Size (bytes) | Upstream path |
|---|---|---|
| `opentitan/include/prim_assert.sv` | 9806 | `hw/ip/prim/rtl/prim_assert.sv` |
| `opentitan/include/prim_assert_dummy_macros.svh` | 1102 | `hw/ip/prim/rtl/prim_assert_dummy_macros.svh` |
| `opentitan/include/prim_assert_sec_cm.svh` | 4972 | `hw/ip/prim/rtl/prim_assert_sec_cm.svh` |
| `opentitan/include/prim_assert_standard_macros.svh` | 6614 | `hw/ip/prim/rtl/prim_assert_standard_macros.svh` |
| `opentitan/include/prim_assert_yosys_macros.svh` | 2709 | `hw/ip/prim/rtl/prim_assert_yosys_macros.svh` |
| `opentitan/include/prim_flop_macros.sv` | 3576 | `hw/ip/prim/rtl/prim_flop_macros.sv` |
