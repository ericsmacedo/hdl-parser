---
name: hdl-parser
description: Answer questions about a SystemVerilog or Verilog or VHDL design (RTL) with the hdl-parser CLI or its MCP server instead of grep - module ports and parameters, instance hierarchy, where a module is used, parameter values and port widths after elaboration, what drives or loads a signal across the hierarchy, and how one signal reaches another. Use it whenever a task needs to understand, navigate, review or modify HDL code (.sv, .v, .svh, .vhd, .vhdl), filelists (.f), or debug connectivity.
---

# hdl-parser

hdl-parser reads a whole design (every SystemVerilog and VHDL file, or a filelist) and answers narrow questions
with small JSON answers which point into the source. Prefer it over grep and over reading large files: it follows
signals through port renames across the hierarchy and evaluates parameterized widths, which is exactly where
guessing goes wrong.

Tools: the MCP tools `module`, `hierarchy`, `where_used`, `find`, `diagnostics`, `elaborate`, `evaluate`,
`drivers`, `loads`, `trace`, `reload` (if the server `hdl-parser` is connected), or the same queries on the
command line: `hdl-parser <query> ...` (`where-used` with a dash). Both give the same JSON.
See [reference.md](reference.md) for all arguments.

## 1. Set up the project once

Every query parses the project the same way. Get this right first - a wrong setup gives confident, wrong answers.

1. Look for `hdl-parser.toml` in the design (current directory or a parent). If it exists, the options are
   there: run the queries without any project options.
2. Otherwise find how the design is compiled: a filelist (`*.f`) used by lint, synthesis or simulation, its
   `+define+` / `-D` macros and include directories. Ask the user if unsure which filelist and defines are the
   real configuration.
3. Write `hdl-parser.toml` at the design root (paths relative to it), or pass the same options on every call:

   ```toml
   filelist = "path/to/list.f"   # or: paths = ["rtl"], exclude = ["models/*"]
   expand_macros = true          # -e: expand `define macros
   resolve_ifdefs = true         # -r: remove `ifdef branches which are not compiled
   closed_world = true           # macros defined nowhere are undefined, like a compiler
   defines = { SYNTHESIS = "" }  # -D, in addition to the +define+ of the filelist
   inc_dirs = ["include"]        # -I
   cache_dir = "~/.cache/hdl-parser/<design>"   # or: cache = true. Repeated queries parse changed files only
   blackbox = ["*_stdcell_*"]    # modules known to be missing (cells, hard macros)
   ```

   Use `closed_world = true` only if the filelist and defines are complete. Without it, an `` `ifdef `` on a
   macro that is never defined keeps **both** branches, so `drivers` and `trace` may report dead code.
4. Check: `hdl-parser diagnostics --group-by code`. Expect `undefined-module` for cells and blackboxes; add them
   to `blackbox`. Many `macro-not-expanded` or `include-not-found`: the defines or include directories are
   missing.

For the MCP server: `claude mcp add hdl-parser -- hdl-parser mcp` within the design (with `hdl-parser.toml`),
or with the options: `claude mcp add hdl-parser -- hdl-parser mcp -f list.f -e -r --closed-world -D SYNTHESIS
--cache-dir ~/.cache/hdl-parser/<design>`. The server keeps the design in memory and reads changed files again on
the next call; call `reload` after files were added.

## 2. Ask small, then narrow down

| Question | Query |
| -------- | ----- |
| Where do I start? Which modules are on top? | `hierarchy` (no top): tops, the largest first |
| What is below a module? | `hierarchy --top X --depth 1` (`--text` for a compact tree) |
| What does a module look like? | `module X --summary`, then `module X --fields ports,params` |
| Where is a module instantiated? | `where-used X` (also for undefined modules; `'BUFX*'` for all matching) |
| Where is a name defined? | `find pattern --kind port` (part of the name; `*` wildcards match the full identifier) |
| Which value does a parameter have, how wide is a port, in this instance? | `elaborate TOP --path u_a.u_b --name 'WIDTH*'` |
| What is `$clog2(DEPTH)+1` in this module? | `evaluate '$clog2(DEPTH)+1' MODULE -p DEPTH=40` |
| What drives this signal? What does it drive? | `drivers top.u_a.sig`, `loads top.u_a.sig` |
| How does A reach B? | `trace top.a top.u_x.b` (`--through-regs` to continue behind flip-flops; `--boundaries --text` for the module boundaries only) |
| Can I trust the answers? | `diagnostics --group-by code`, then `--code X` (`'macro-*'`) or `--file 'rtl/*'` |

Signals are addressed by **instance path**: top module, instance names (with the labels of generate blocks), signal:
`top.u_core.g_lane[1].data`. `hierarchy` names instances with their labels (`g_lane.u_sub`); `elaborate` unrolls
loops (`--path 'g_lane[1].u_sub'`). A select (`top.data[5]`) keeps the drivers, loads, and
trace ends of bit 5; selects within loops are evaluated per iteration (see Limits). Modules by name or full identifier `<file>:<id>` (`rtl/top.sv:top`). Every item in
an answer has `line` (and `file`), so open the source at that line only when needed.

To follow a signal step by step: `drivers` returns the signals each driver reads (`nets`) and its conditions
(`conds`); ask for their drivers next. `trace` does the search for you and gives `counts` (hops, flip-flops,
conditions) - judge a path by these.

## 3. Read the answers right

- **Limited lists:** every list holds 100 entries at most. `omitted` counts what was left out (`module`,
  `elaborate`: by field in `omitted_by`), `total` the full number. Never conclude "there is no X" while something is `omitted`: raise `--limit` (0: all) or filter.
- **Shape:** a list of objects is always a table `{"columns": [...], "rows": [[...]]}`, even if it is empty;
  `null` marks a field an item does not have (its default). Lists are there, even if empty. `--full` (MCP: `detail: "full"`) gives full identifiers, `loc` with columns, and lists
  of objects.
- **Unknown is not zero:** `elaborate` and `evaluate` never guess. A value which cannot be computed (constant
  functions, assignment patterns `'{...}`) has `unknown` with the reason. Report it as unknown, or compute it
  from the source yourself and say so.
- **`ifdef`:** code under an unresolved condition is tagged `ifdefs` (`["!FOO"]` means "FOO not defined"), see
  `module X --fields assigns,insts`. `drivers` and `trace` do not show it: if a hop lands inside an `` `ifdef ``
  region and the project does not use `closed_world`, check the source.
- **`multiple-drivers`** in `diagnostics`: a signal driven by more than one assignment or process. A real bug,
  or both branches of an unresolved `` `ifdef `` - check before reporting.
- **Errors:** exit code 3 / `{"error": {"code": "not-found", "suggestions": [...]}}` - retry with a suggestion.
  Exit code 2 / `bad-argument`: fix the call. Problems of the design are data in `diagnostics`, never failures.
- **Macros:** without `expand_macros`, `` `MACRO `` calls are kept as text and ports created by macros are
  missing (`macro-not-expanded`).

## 4. Limits

The tool is not a full elaborator. Where it stops, check the source:

- **Bits:** a select (`top.data[5]`) filters by bit only on instance connections. Assignments read names, not
  bits: such rows come back with `bits: "unchecked"` and may not touch bit 5. `trace` hops do not carry the
  marker.
- **Generate loops:** only labeled `for` loops with a constant range are unrolled (`g[1].u`). Unlabeled loops
  and loops with a range that cannot be evaluated stay one node with `multiple: true`.
- **`ifdef`:** without `closed_world`, both branches are kept; instances and drivers of both appear.
- **Port widths:** in `elaborate`, a port's `value` is its number of bits; `expr` is its type and dimensions.

## 5. Command line tips

- `-n N` limits lists, `-F a,b` selects fields (also `ports.name`), `-s` summary, `-c` one line JSON.
- Files given on the command line replace the ones of `hdl-parser.toml`; `--no-config` ignores it,
  `--config FILE` names another one (before the query: `hdl-parser --config FILE module top`).
- `hdl-parser project > design.json` dumps everything (large; prefer queries). `hdl-parser schema` is its format.
- In Python: `from hdl_parser import Project, query`; `prj = Project.from_filelist("list.f", expand_macros=True)`;
  `query.drivers(prj, "top.u_a.sig")` returns the same dictionaries.
