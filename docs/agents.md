# Guide For AI Agents

hdl-parser answers narrow questions on a SystemVerilog or VHDL design with small JSON answers, which point into
the source. It is meant to be called by AI agents and scripts: on the command line or as MCP server.

## Rules Of The Answers

* Every item has a **full identifier** `<file>:<id>` (`rtl/top.sv:top.u_sub`) and a **source line** `line`.
  The file is relative to the root of the project. An identifier can be handed to every query instead of a name.
* Answers are **compact**: the identifier of an item within another one is left out, if it is the one around
  followed by its name, and relative otherwise (`#always1`). A list of objects may be a **table**:
  `{"columns": [...], "rows": [[...]]}`, `null` for a field an item has not. `--full` (MCP: `detail: "full"`)
  gives every identifier, the location with columns (`loc`) and lists of objects.
* Every list is **limited** to 100 entries (`--limit`, `0` for no limit). What is left out is counted in
  `omitted`, the full number is `total`. Nothing is dropped silently.
* `--fields` selects fields, also of the items of a list (`ports.direction`), `--summary` gives names and counts
  only. Start small, then ask for more.
* **Problems are data**, not failures: see `diagnostics`. Standard error stays empty; `-v` traces them there.
* Code created by a macro points at the macro call: its `loc` names the `macro` (`--full`).
* Nothing is guessed: what cannot be known is left out or reported.

## Exit Codes

| Code | Meaning | Standard output |
| ---- | ------- | --------------- |
| 0 | Answer | The answer |
| 1 | Internal failure (a bug) | Nothing. The reason is on standard error. |
| 2 | Wrong command line, or bad argument of a query | Usage, or `{"error": {"code": "bad-argument", ...}}` |
| 3 | Name not found | `{"error": {"code": "not-found", "suggestions": [...]}}` |

## The Project

Every query reads the whole design. By default it is every SystemVerilog and VHDL file below the current
directory. Alternatively:

```bash
hdl-parser module top rtl/top.sv rtl/sub.sv     # these files
hdl-parser module top rtl --exclude 'models/*'  # all files below a directory
hdl-parser module top -f top.f -e               # a filelist, with macros expanded
```

`--cache` keeps the results in `.hdl_parser_cache` within the root: repeated queries on a large design parse
changed files only. The files are parsed by one process per CPU, `--jobs N` limits them.
`hdl-parser project` gives everything as one JSON document (see `hdl-parser schema`).

## Worked Examples

All examples are run within `tests/corpus/sv/ibex` of the repository, a RISC-V core.

### Where do I start? Which modules are on top?

Without `--top`, `hierarchy` gives the modules which are instantiated nowhere, the largest first (`insts`:
number of instances at all levels). Tops without instances (mostly unused library cells) are left out and
counted in `leaves`; `--leaves` returns them too. `--text` gives a tree as indented text, much smaller than JSON.

```bash
hdl-parser hierarchy
```

```json
{
  "query": "hierarchy",
  "result": [
    {
      "id": "ibex_top.sv:ibex_top",
      "kind": "module",
      "file": "ibex_top.sv",
      "name": "ibex_top",
      "line": 15,
      "insts": 85
    }
  ],
  "total": 1
}
```

### What does a module look like, in brief?

Names and counts only. Ask for the fields needed next.

```bash
hdl-parser module ibex_alu --summary
```

```json
{
  "query": "module",
  "result": {
    "id": "ibex_alu.sv:ibex_alu",
    "kind": "module",
    "name": "ibex_alu",
    "file": "ibex_alu.sv",
    "line": 9,
    "counts": {
      "params": 1,
      "ports": 11,
      "localparams": 4,
      "signals": 74,
      "processes": 21,
      "assigns": 60,
      "imports": 1
    }
  }
}
```

### Which ports does it have?

Two ports are returned as table, the other nine are counted in `omitted`. Lines start at 1. `--fields
ports.name,ports.direction` would return these columns only.

```bash
hdl-parser module ibex_alu --fields ports --limit 2
```

```json
{
  "query": "module",
  "result": {
    "id": "ibex_alu.sv:ibex_alu",
    "kind": "module",
    "name": "ibex_alu",
    "ports": {
      "columns": ["name", "direction", "ptype", "line", "dim"],
      "rows": [
        ["operator_i", "input", "ibex_pkg::alu_op_e", 12, null],
        ["operand_a_i", "input", "logic", 13, "[31:0]"]
      ]
    }
  },
  "omitted": {
    "ports": 9
  }
}
```

### What is instantiated below a module?

Two instances share a name, as they are located in different `generate` branches. Use `--depth` and `--limit` on large designs.

```bash
hdl-parser hierarchy --top ibex_ex_block --fields module,loc
```

```json
{
  "query": "hierarchy",
  "result": {
    "name": "ibex_ex_block",
    "module": "ibex_ex_block",
    "line": 11,
    "children": {
      "columns": ["name", "module", "line"],
      "rows": [
        ["alu_i", "ibex_alu", 110],
        ["multdiv_i", "ibex_multdiv_slow", 131],
        ["multdiv_i", "ibex_multdiv_fast", 156]
      ]
    }
  }
}
```

### Where is a module used?

The places to edit when a port of `ibex_alu` changes.

```bash
hdl-parser where-used ibex_alu
```

```json
{
  "query": "where-used",
  "result": [
    {
      "inst": "ibex_ex_block.sv:ibex_ex_block.alu_i",
      "module": "ibex_ex_block.sv:ibex_ex_block",
      "file": "ibex_ex_block.sv",
      "line": 110
    }
  ],
  "total": 1,
  "module": "ibex_alu.sv:ibex_alu"
}
```

### Where is a signal or port named like this?

Without wildcard the pattern is part of the name. With wildcards it matches the name or the full identifier: `find 'ibex_alu.sv:ibex_alu.*'`.

```bash
hdl-parser find operator --kind port --limit 2
```

```json
{
  "query": "find",
  "result": {
    "columns": ["id", "name", "kind", "file", "direction", "ptype", "line"],
    "rows": [
      ["ibex_alu.sv:ibex_alu.operator_i", "operator_i", "port", "ibex_alu.sv", "input", "ibex_pkg::alu_op_e", 12],
      ["ibex_decoder.sv:ibex_decoder.alu_operator_o", "alu_operator_o", "port", "ibex_decoder.sv", "output", "ibex_pkg::alu_op_e", 64]
    ]
  },
  "total": 11,
  "omitted": 9
}
```

### What drives this signal?

A signal is addressed by its instance path: the top, the instance names (with the labels of the generate blocks
around) and the signal. The index of a `for` generate block selects one iteration (`top.g_st[1].data`), it is
checked against the range of the loop. Every driver has its `kind` (`assign`, `comb`, `ff`, `latch`, `inst`,
`port`, `passthrough`, `unknown`), the signals it reads (`nets`) and the ones its conditions read (`conds`). Ask for their drivers to
go further. `loads` is the other direction: what the signal drives.

```bash
hdl-parser drivers ibex_top.u_ibex_core.if_stage_i.instr_rdata_id_o
```

```json
{
  "query": "drivers",
  "net": {
    "path": "ibex_top.u_ibex_core.if_stage_i.instr_rdata_id_o",
    "kind": "port",
    "direction": "output",
    "id": "ibex_if_stage.sv:ibex_if_stage.instr_rdata_id_o",
    "file": "ibex_if_stage.sv",
    "line": 72
  },
  "result": [
    {
      "kind": "ff",
      "nets": ["ibex_top.u_ibex_core.if_stage_i.instr_out"],
      "conds": ["ibex_top.u_ibex_core.if_stage_i.if_id_pipe_reg_we"],
      "clock": "ibex_top.u_ibex_core.if_stage_i.clk_i",
      "item": "ibex_if_stage.sv:ibex_if_stage.g_instr_rdata_nr.#always6",
      "file": "ibex_if_stage.sv",
      "line": 659
    }
  ],
  "total": 1
}
```

### How does this signal get there?

`trace` gives the shortest connection between two signals, hop by hop, data before conditions (`if`, `case`
and the select of `?:` are conditions). `counts` tells the hops, and how many of them are flip-flops or
conditions: judge the path by them. It stops behind flip-flops, unless `--through-regs` is given, and at
modules which are not defined (`stopped_at` names them). Wrappers of technology cells (one input, one output,
driven by undefined cells only) are passed through; give others with `--passthrough BUFX2:A->Y`.

```bash
hdl-parser trace ibex_top.rst_ni ibex_top.u_ibex_core.id_stage_i.controller_i.ctrl_fsm_cs --limit 3
```

```json
{
  "query": "trace",
  "result": [
    {
      "net": "ibex_top.rst_ni"
    },
    {
      "net": "ibex_top.u_ibex_core.rst_ni",
      "kind": "inst",
      "item": "ibex_top.sv:ibex_top.u_ibex_core",
      "file": "ibex_top.sv",
      "line": 412
    },
    {
      "net": "ibex_top.u_ibex_core.id_stage_i.rst_ni",
      "kind": "inst",
      "item": "ibex_core.sv:ibex_core.id_stage_i",
      "file": "ibex_core.sv",
      "line": 672
    }
  ],
  "total": 5,
  "omitted": 2,
  "found": true,
  "counts": {
    "hops": 4,
    "ff": 1,
    "control": 1
  }
}
```

### Can I trust the answers? What is missing?

Modules which are not part of the project, macros which are not expanded, files which cannot be read: all are listed here, with location.
`file` and `line` are where the problem is. A problem within an included file is listed once, `parsed` names the
files including it.

```bash
hdl-parser diagnostics --severity warning --limit 1
```

```json
{
  "query": "diagnostics",
  "result": [
    {
      "file": "ibex_core.sv",
      "code": "undefined-module",
      "severity": "warning",
      "message": "module 'prim_buf' of instance 'u_fetch_enable_buf' is not defined in the project.",
      "line": 500,
      "item": "ibex_core.sv:ibex_core.g_core_busy_secure.u_fetch_enable_buf"
    }
  ],
  "total": 37,
  "omitted": 36,
  "counts": {
    "error": 0,
    "warning": 37,
    "info": 0
  }
}
```

### What if a name is wrong?

Exit code 3, an error object and similar names.

```bash
hdl-parser module ibex_alux
```

```json
{
  "error": {
    "code": "not-found",
    "message": "'ibex_alux' is not defined in the project.",
    "suggestions": ["ibex_alu"]
  }
}
```

## MCP Server

`hdl-parser mcp` serves the same queries as tools on standard input and output: `module`, `hierarchy`,
`where_used`, `find`, `diagnostics`, `elaborate`, `evaluate`, `drivers`, `loads`, `trace` and `reload`. It takes the
same options to create the project. The arguments of a tool are named like the options of its command
(`--exclude-file`: `exclude_file`); an option given multiple times is a list (`--kind`: `kind`).
Files which changed are read again on the next call, `reload` reads the project again (i.e. after files
were added). Answers are the same JSON, in `structuredContent` and as text. A failed query has `isError`.
All tools are read-only (`readOnlyHint`).

* `diagnostics` with `group_by` (`code`, `file`, `module`) gives counts first; `exclude_file` drops files by pattern,
  `blackbox` drops `undefined-module` for known blackboxes. `--blackbox PATTERN` applies to every call.
* `elaborate` gives the values of the parameters and the widths of the ports (bits) of one instance: `top`,
  `path` (`u_core.u_alu`), `param` of the top, `name` patterns, `unknown` for the values not known, with
  the reason. `evaluate` gives the value of an expression within a module or package. Same as
  `hdl-parser elaborate TOP --path ... -p W=8` and `hdl-parser evaluate EXPR SCOPE`.
* `where_used` works for modules which are not defined (blackboxes, hard macros): `defined` is `false` then.
* `drivers`, `loads` and `trace` take instance paths of signals (`top.u_core.result_o`), `param` of the top
  and `passthrough` cells. Generate constructs whose condition is false are left out. Labeled `for` generate
  constructs are unrolled (`top.g_st[1].data`); without index, and for instance arrays, an answer stands for
  all of them (`multiple`). The granularity is the whole signal: the select (`[3:0]`) is given as text.
  Procedural statements which are not understood (task calls) are reported as `statement-skipped`.
* `--cache-dir DIR` keeps the cache outside the root, i.e. outside a shared work area.

```json
{
  "mcpServers": {
    "hdl-parser": {"command": "hdl-parser", "args": ["mcp", "--cache", "-f", "top.f"]}
  }
}
```

For Claude Code:

```bash
claude mcp add hdl-parser -- hdl-parser mcp --cache
```

With a [configuration file](usage.md#configuration-file) `hdl-parser.toml` in the design, the options are kept
there and the server is started without any: `claude mcp add hdl-parser -- hdl-parser mcp`. Start it within the
design, or give `--config FILE` before `mcp`.

## Skill

The repository ships an [Agent Skill](https://github.com/ericsmacedo/hdl-parser/tree/main/skills/hdl-parser):
`SKILL.md` tells an agent when to use hdl-parser, how to set up the project, which query answers which question
and how to read the answers; `reference.md` lists every MCP tool argument, option and diagnostic code.
Install it for Claude Code, for one design or for all of them:

```bash
git clone https://github.com/ericsmacedo/hdl-parser
cp -r hdl-parser/skills/hdl-parser <design>/.claude/skills/   # or: ~/.claude/skills/
```

## Python

The same queries are available in Python: [hdl_parser.query][].
