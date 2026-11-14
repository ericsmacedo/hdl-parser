# VHDL Test Corpus

Unmodified third-party VHDL files used as a safety net for tokenizer and parser changes. Every file is
snapshot-tested (`tests/test_vhdl_corpus.py::test_corpus_snapshot`, reference data in
`tests/refdata/tests.test_vhdl_corpus/`) and checked against structural invariants
(`tests/test_vhdl_corpus.py::test_corpus_invariants`).

The files are kept byte-for-byte as downloaded, including their license headers, and are excluded from all
pre-commit hooks. Retrieval date for everything: 2026-11-14. The license text of each project is stored next to its files.

## neorv32

- URL: <https://github.com/stnolting/neorv32>
- Ref: commit `bb5ea332d283a20b9d1d442fa5c6b0326d508eaa` (default branch at retrieval)
- License: BSD 3-Clause License (`LICENSE`, upstream `LICENSE`)
- Retrieved: 2026-11-14

| File | Size (bytes) | Upstream path |
|---|---|---|
| `neorv32/neorv32_cpu.vhd` | 32901 | `rtl/core/neorv32_cpu.vhd` |
| `neorv32/neorv32_cpu_alu.vhd` | 17555 | `rtl/core/neorv32_cpu_alu.vhd` |
| `neorv32/neorv32_cpu_pmp.vhd` | 15630 | `rtl/core/neorv32_cpu_pmp.vhd` |
| `neorv32/neorv32_prim.vhd` | 19375 | `rtl/core/neorv32_prim.vhd` |
| `neorv32/neorv32_bus.vhd` | 45473 | `rtl/core/neorv32_bus.vhd` |
| `neorv32/neorv32_pwm.vhd` | 10316 | `rtl/core/neorv32_pwm.vhd` |
| `neorv32/neorv32_clint.vhd` | 10457 | `rtl/core/neorv32_clint.vhd` |
| `neorv32/neorv32_sysinfo.vhd` | 12214 | `rtl/core/neorv32_sysinfo.vhd` |
| `neorv32/neorv32_trng.vhd` | 23330 | `rtl/core/neorv32_trng.vhd` |
| `neorv32/xbus2axi4_bridge.vhd` | 11600 | `rtl/system_integration/xbus2axi4_bridge.vhd` |

## microwatt

- URL: <https://github.com/antonblanchard/microwatt>
- Ref: commit `f341bed306a9a7281bf65200df8cc1f0a002617d` (default branch at retrieval)
- License: Creative Commons Attribution 4.0 (CC-BY 4.0) (`LICENSE`, upstream `LICENSE`)
- Retrieved: 2026-11-14

| File | Size (bytes) | Upstream path |
|---|---|---|
| `microwatt/core.vhdl` | 18897 | `core.vhdl` |
| `microwatt/soc.vhdl` | 42186 | `soc.vhdl` |
| `microwatt/multiply.vhdl` | 3083 | `multiply.vhdl` |
| `microwatt/xics.vhdl` | 18003 | `xics.vhdl` |
| `microwatt/spi_rxtx.vhdl` | 12606 | `spi_rxtx.vhdl` |
| `microwatt/cache_ram.vhdl` | 2768 | `cache_ram.vhdl` |
| `microwatt/bitsort.vhdl` | 5077 | `bitsort.vhdl` |
| `microwatt/xilinx-mult.vhdl` | 30924 | `xilinx-mult.vhdl` |
| `microwatt/top-genesys2.vhdl` | 13949 | `fpga/top-genesys2.vhdl` |
| `microwatt/sim_litedram.vhdl` | 7921 | `litedram/extras/sim_litedram.vhdl` |

## poc

- URL: <https://github.com/VLSI-EDA/PoC>
- Ref: commit `8c39b2407a97ec81b8601c4b64e4d2e2141ab9cf` (default branch at retrieval)
- License: Apache License 2.0 (`LICENSE`, upstream `LICENSE.md`)
- Retrieved: 2026-11-14

| File | Size (bytes) | Upstream path |
|---|---|---|
| `poc/arith_addw.vhdl` | 11925 | `src/arith/arith_addw.vhdl` |
| `poc/arith_counter_bcd.vhdl` | 3119 | `src/arith/arith_counter_bcd.vhdl` |
| `poc/uart_fifo.vhdl` | 10227 | `src/io/uart/uart_fifo.vhdl` |
| `poc/io_FanControl.vhdl` | 9791 | `src/io/io_FanControl.vhdl` |
| `poc/fifo_cc_got.vhdl` | 13089 | `src/fifo/fifo_cc_got.vhdl` |
| `poc/cache_mem.vhdl` | 13363 | `src/cache/cache_mem.vhdl` |
| `poc/sync_Bits_Xilinx.vhdl` | 5613 | `src/misc/sync/sync_Bits_Xilinx.vhdl` |
| `poc/sortnet_Stream_Adapter2.vhdl` | 12576 | `src/sort/sortnet/sortnet_Stream_Adapter2.vhdl` |
| `poc/udp_RX.vhdl` | 16195 | `src/net/udp/udp_RX.vhdl` |
| `poc/xil_ChipScopeICON.vhdl` | 7927 | `src/xil/xil_ChipScopeICON.vhdl` |

## surf

- URL: <https://github.com/slaclab/surf>
- Ref: tag `v2.78.0` (commit `6b787eea6a52ae4f9ff381e7a6562f1e9fc9dffc`)
- License: SLAC BSD-style license (`LICENSE`, upstream `LICENSE.txt`)
- Retrieved: 2026-11-14

| File | Size (bytes) | Upstream path |
|---|---|---|
| `surf/RstSync.vhd` | 3066 | `base/sync/rtl/RstSync.vhd` |
| `surf/LutRam.vhd` | 15544 | `base/ram/inferred/LutRam.vhd` |
| `surf/Jesd204bRx.vhd` | 13295 | `protocols/jesd204b/rtl/Jesd204bRx.vhd` |
| `surf/JesdRxReg.vhd` | 21397 | `protocols/jesd204b/rtl/JesdRxReg.vhd` |
| `surf/AxiAds42lb69Pll.vhd` | 9206 | `devices/Ti/ads42lb69/rtl/AxiAds42lb69Pll.vhd` |
| `surf/AxiResizeIpIntegrator.vhd` | 11068 | `axi/axi4/ip_integrator/AxiResizeIpIntegrator.vhd` |
| `surf/AxiLiteCrossbarIpIntegrator.vhd` | 7687 | `axi/axi-lite/ip_integrator/AxiLiteCrossbarIpIntegrator.vhd` |
| `surf/XadcSimpleCore.vhd` | 19212 | `xilinx/7Series/xadc/rtl/XadcSimpleCore.vhd` |
| `surf/ClockManager7.vhd` | 17219 | `xilinx/7Series/general/rtl/ClockManager7.vhd` |

## potato

- URL: <https://github.com/skordal/potato>
- Ref: commit `404e6bb26f38931d6c6982ba4631dc7724f15409` (default branch at retrieval)
- License: BSD 3-Clause License (`LICENSE`, upstream `LICENSE`)
- Retrieved: 2026-11-14

| File | Size (bytes) | Upstream path |
|---|---|---|
| `potato/pp_core.vhd` | 15290 | `src/pp_core.vhd` |
| `potato/pp_execute.vhd` | 14208 | `src/pp_execute.vhd` |
| `potato/pp_potato.vhd` | 5309 | `src/pp_potato.vhd` |
| `potato/pp_csr_unit.vhd` | 9328 | `src/pp_csr_unit.vhd` |
| `potato/pp_memory.vhd` | 4770 | `src/pp_memory.vhd` |
| `potato/pp_decode.vhd` | 3947 | `src/pp_decode.vhd` |
| `potato/pp_writeback.vhd` | 1900 | `src/pp_writeback.vhd` |
| `potato/pp_icache.vhd` | 6426 | `src/pp_icache.vhd` |
| `potato/pp_fifo.vhd` | 2129 | `soc/pp_fifo.vhd` |
| `potato/pp_soc_intercon.vhd` | 5854 | `soc/pp_soc_intercon.vhd` |
| `potato/pp_soc_gpio.vhd` | 3350 | `soc/pp_soc_gpio.vhd` |
| `potato/toplevel.vhd` | 17660 | `example/toplevel.vhd` |
