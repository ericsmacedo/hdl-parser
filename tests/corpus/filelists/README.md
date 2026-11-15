# Filelist Test Corpus

Unmodified third-party filelists, used to test the filelist parser and the project database
(`tests/test_filelistparser.py`, `tests/test_project.py`). The files they name are not part of this corpus: a
project created from them reports each of them as missing.

The files are kept byte-for-byte as downloaded and are excluded from all pre-commit hooks. The license text of each
project is stored next to its file. Retrieved on 2026-11-15.

Two more filelists are located next to the files they name: `../sv/ibex/ibex_core.f` and `../sv/ibex/ibex_dv.f`.

| File | Size (bytes) | Project | Ref | Upstream path | License | Covers |
|---|---|---|---|---|---|---|
| `veer_el2/flist` | 2288 | <https://github.com/chipsalliance/Cores-VeeR-EL2> | commit `4e975c5a344a46f43903c6cb27b2a1dfc2c0f1ae` (`main` at retrieval) | `testbench/flist` | Apache License 2.0 | `+libext+`, `+define+`, `+incdir+`, `-v`, `-y`, `$VAR` |
| `cva6/Flist.cva6` | 8854 | <https://github.com/openhwgroup/cva6> | tag `v5.1.0` | `core/Flist.cva6` | Solderpad Hardware License v0.51 | `${VAR}`, `+incdir+`, `-F`, comments |
