# Usage

There are two major use-cases:

* **Command Line**: See [Command Line Interface](cli.md)
* **Python**: See [API](api.md)

## Command Line Examples

### Markdown

!!! example "Generate Markdown Table"

    ```bash
    hdl-parser info -s examples/sv/adder.sv > examples/sv/adder.md
    ```

??? info "Markdown Table Code"

    ``` title="examples/sv/adder.md"
    --8<-- "examples/sv/adder.md"
    ```

??? info "Markdown Table"

    {%
        include-markdown "../examples/sv/adder.md"
    %}

### JSON

!!! example "Generate JSON"

    ```bash
    hdl-parser json examples/sv/adder.sv > examples/sv/adder.json
    ```

??? info "JSON File"

    ``` title="examples/sv/adder.json"
    --8<-- "examples/sv/adder.json"
    ```

## Packages And Types

SystemVerilog packages are listed in `packages` of the file, with their parameters and types.
Enumerations list their members, structs and unions their fields:

```python
>>> import hdl_parser
>>> file = hdl_parser.parse_text("""
... package bus_pkg;
...   localparam int AW = 32;
...   typedef enum logic [1:0] {IDLE, BUSY = 2} state_t;
...   typedef struct packed { logic [AW-1:0] addr; logic we; } req_t;
... endpackage
... """)
>>> for typedef in file.packages[0].typedefs:
...     print(typedef.id, typedef.kind, [(member.name, member.dtype, member.dim, member.value) for member in typedef.members])
bus_pkg.state_t enum [('IDLE', '', '', ''), ('BUSY', '', '', '2')]
bus_pkg.req_t struct [('addr', 'logic', '[AW-1:0]', ''), ('we', 'logic', '', '')]

```

Types declared within a module are listed in `typedefs` of the module.

## What Is Extracted

A file lists its `modules`, `interfaces` and `packages`. VHDL entities are modules, with the content of their
architectures.

| Attribute      | Of                           | Content                                                            |
| -------------- | ---------------------------- | ------------------------------------------------------------------ |
| `params`       | modules, interfaces, packages| Parameters (VHDL: generics)                                        |
| `localparams`  | modules, interfaces, packages| Local parameters (VHDL: constants)                                 |
| `ports`        | modules, interfaces          | Ports                                                              |
| `signals`      | modules, interfaces          | Nets and variables (VHDL: signals)                                 |
| `typedefs`     | modules, interfaces, packages| Types: enumerations, structs (VHDL: records) and aliases           |
| `functions`    | modules, interfaces, packages| Signatures of functions and tasks (VHDL: procedures)               |
| `processes`    | modules, interfaces          | `always` blocks (VHDL: processes) with clock, reset and assignments|
| `assigns`      | modules, interfaces          | Continuous assignments (VHDL: concurrent signal assignments)       |
| `insts`        | modules, interfaces          | Instances with parameter values, connections and generate blocks   |
| `modports`     | interfaces                   | Modports with the direction of their signals                       |
| `components`   | modules, packages            | Component declarations (VHDL)                                      |

Every item has an `id` and a source location `loc`. `file.iter_items()` walks all of them, `file.find(id)`
returns one:

```python
>>> file = hdl_parser.parse_text("""
... module top (input logic clk_i, input logic rst_ni);
...   logic [7:0] data_q;
...   always_ff @(posedge clk_i or negedge rst_ni) begin : p_data
...     if (!rst_ni) data_q <= '0;
...     else data_q <= data_q + 1;
...   end
... endmodule
... """)
>>> [item.id for item in file.iter_items()]
['top', 'top.clk_i', 'top.rst_ni', 'top.data_q', 'top.p_data']
>>> process = file.find("top.p_data")
>>> process.clock, process.clock_edge, process.reset, process.reset_edge
('clk_i', 'posedge', 'rst_ni', 'negedge')

```

Clock and reset of a block are never guessed: they are empty, if the code does not tell them.

Every assignment knows its target, the names it reads and the names read by the conditions around:

```python
>>> [(assign.target, assign.reads, assign.conds, assign.blocking) for assign in process.assigns]
[('data_q', (), ('rst_ni',), False), ('data_q', ('data_q',), ('rst_ni',), False)]

```

A statement which is not understood (i.e. a task call) is reported as `statement-skipped`.

## Projects

A project is the model of all files of a design. It is created from a filelist, a directory or single files,
and answers questions about the design instead of single files:

```python
>>> from hdl_parser import Project
>>> project = Project.from_filelist("tests/corpus/sv/ibex/ibex_core.f")
>>> len(project.files)
17
>>> project.resolve("ibex_alu").id
'ibex_alu.sv:ibex_alu'
>>> [use.inst for use in project.where_used("ibex_alu")]
['ibex_ex_block.sv:ibex_ex_block.alu_i']
>>> tree = project.hierarchy("ibex_ex_block")
>>> [(node.name, node.module, node.definition) for node in tree.children]  # doctest: +NORMALIZE_WHITESPACE
[('alu_i', 'ibex_alu', 'ibex_alu.sv:ibex_alu'),
 ('multdiv_i', 'ibex_multdiv_slow', 'ibex_multdiv_slow.sv:ibex_multdiv_slow'),
 ('multdiv_i', 'ibex_multdiv_fast', 'ibex_multdiv_fast.sv:ibex_multdiv_fast')]
>>> project.find("ibex_alu.sv:ibex_alu.operator_i").ptype
'ibex_pkg::alu_op_e'

```

* The paths of the files, and therefore the full identifiers of all items, are relative to the root of the project.
* A file which cannot be read or parsed is part of the project with a diagnostic. The other files are still there.
* Instances of modules which are defined nowhere are reported as `undefined-module`.
* A module which is defined more than once is reported as `duplicate-definition`. The first definition is used,
  unless `prefer={"fifo": "rtl/fifo.sv"}` names another one, or `exclude` leaves files of a directory out.
* A filelist contributes its macros (`+define+`), include directories and libraries (`-v`, `-y`).
* `cache=True` keeps the result of every file in `.hdl_parser_cache` within the root of the project.
  A file is parsed again only if it changed, a file it includes changed, or it is parsed in another way.
* `jobs=None` parses the files by one process per CPU, `jobs=4` by four. The result is the same. A script
  using it has to protect its entry point by `if __name__ == "__main__":`. The command line does so by default
  (`--jobs`).
* `project.overview` is one JSON document for all files, with a `schema_version`.

On the command line, `hdl-parser project` prints this document, for files, a directory or a filelist:

```bash
hdl-parser project rtl/top.sv rtl/fifo.sv
hdl-parser project rtl --exclude 'models/*'
hdl-parser project -f top.f --expand-macros -D SYNTHESIS -D WIDTH=8 --cache
```

Its format is the JSON Schema printed by `hdl-parser schema`, which is also published as
[schema/project.schema.json](schema/project.schema.json) (`Project.json_schema()` in Python).
`schema_version` is incremented on every change which is not backward compatible.
Problems are part of the document: in `diagnostics` of the project and of every file, with code, severity,
message and location. Standard error stays empty; `-v` traces the diagnostics there.

The commands for humans (`info`, `json`, `gen-sv-instance`) print warnings and errors on standard error, infos with
`-v`. The library never prints a diagnostic: every one is returned and logged at DEBUG level only. The problems of a
file are in its `diagnostics`, the ones of a filelist or the defines in `diagnostics` of the project (and of the
results of `read_filelist` and `parse_defines`), located within their `file`.

### Configuration File

The options which create the project can be kept in a file `hdl-parser.toml`, so they are not repeated on every
call. It is searched in the current directory and its parents; `--config FILE` names another one, `--no-config`
ignores it. Paths are relative to the directory of the file, `~` is expanded:

```toml
filelist = "sim/lint/list.f"     # or: paths = ["rtl"], with exclude = ["models/*"]
expand_macros = true
resolve_ifdefs = true
closed_world = true
defines = { SYNTHESIS = "", WIDTH = 8 }
inc_dirs = ["include"]
cache_dir = "~/.cache/hdl-parser/my_design"   # or: cache = true
jobs = 8
root = "."
blackbox = ["*_cell_*"]          # --blackbox of 'diagnostics' and 'mcp'
passthrough = ["buf_wrap"]       # --passthrough of 'drivers', 'loads' and 'trace'
exclude_problems = ["lib/*"]     # --exclude-file of 'diagnostics'
```

It applies to the commands working on a project (`project`, `module`, ..., `mcp`), not to the ones parsing single
files (`json`, `info`, `gen-sv-instance`). The command line takes precedence: an option given there replaces
the value of the file (`-D` replaces all `defines`), and files given there replace `filelist` and `paths`.

Narrow questions with small answers (`hdl-parser module`, `hierarchy`, `where-used`, `find`, `diagnostics`)
and the MCP server (`hdl-parser mcp`) are described in the [Guide for AI Agents](agents.md).

### Values Of Parameters

`elaborate` is the hierarchy with the values of all parameters and the number of bits of all ports, per instance.
The values given by an instance (`#(.WIDTH(8))`, `generic map (WIDTH => 8)`) are applied down the hierarchy.
Names are resolved across files: parameters, local parameters, enumerations and packages.

```python
>>> project = Project.from_dir("tests/corpus/sv/ibex")
>>> tree = project.elaborate("ibex_cs_registers", params={"PMPNumRegions": 8}, depth=1)
>>> tree.params["PMPNumRegions"].value, tree.params["PMPAddrWidth"]
(8, Value(expr='(PMPGranularity > 0) ? PMP_ADDR_MSB - PMPGranularity : 32', value=32, unknown=''))
>>> tree.ports["csr_addr_i"]
Value(expr='ibex_pkg::csr_num_e', value=12, unknown='')
>>> counter = next(node for node in tree.children if node.name == "minstret_counter_i")
>>> counter.inst, counter.params["CounterWidth"].value, counter.ports["counter_val_o"].value
('ibex_cs_registers.sv:ibex_cs_registers.minstret_counter_i', 64, 64)
>>> project.evaluate("$bits(alu_op_e) + PMP_MAX_REGIONS", "ibex_pkg").value
23

```

Nothing is ever guessed. What cannot be evaluated for sure has no value, but the reason:

```python
>>> tree.params["PMPRstCfg"]
Value(expr='ibex_pkg::PmpCfgRst', value=None, unknown="'ibex_pkg::PmpCfgRst' is not known: assignment pattern '{...}")

```

### Connectivity

`drivers` and `loads` tell what drives a signal and what it drives, `trace` how one signal reaches another one.
A signal is addressed by its instance path below a top: `top.u_core.u_alu.result_o`. Generate constructs whose
condition is false for the parameter values are left out.

```python
>>> [(link.kind, link.nets) for link in project.drivers("ibex_top.u_ibex_core.if_stage_i.instr_rdata_id_o")]
[('ff', ('ibex_top.u_ibex_core.if_stage_i.instr_out',))]
>>> [hop.net for hop in project.trace("ibex_top.rst_ni", "ibex_top.u_ibex_core.id_stage_i.controller_i.ctrl_fsm_cs")]
['ibex_top.rst_ni', 'ibex_top.u_ibex_core.rst_ni', 'ibex_top.u_ibex_core.id_stage_i.rst_ni', 'ibex_top.u_ibex_core.id_stage_i.controller_i.rst_ni', 'ibex_top.u_ibex_core.id_stage_i.controller_i.ctrl_fsm_cs']

```

The granularity is the whole signal: the select of an assignment (`[3:0]`) is kept as text. Labeled `for`
generate constructs are unrolled: `top.g_st[1].data` is the signal of the second iteration (the index is checked),
`top.g_st.data` stands for all of them (`multiple`). Instance arrays are not unrolled. The select of `?:` is a
condition, like the ones of `if` and `case`. The search of `trace` stops behind flip-flops (`through_regs`) and at
modules which are not defined, but passes cells which pass their input on: wrappers of technology cells (one input,
one output, driven by undefined cells only) and the cells given as `passthrough` (`["BUFX2:A->Y"]`).

See [Project][hdl_parser.project.Project] for a full reference.

## Macros

Macros are **not** expanded by default. On request (`--expand-macros`, `expand_macros=True`) macros are expanded,
if their `` `define `` is known. So ports, parameters and instances created by macros are found.
The macros defined in the same file and in the files it includes are known.
Included files are searched next to the file and in the include directories (`--incdir`, `+incdir+` in filelists):

!!! example "Command Line"

    ```bash
    hdl-parser info --expand-macros examples/sv/macro_ports.sv
    hdl-parser info --expand-macros --incdir path/to/inc top.sv
    ```

!!! example "Python"

    ```python
    >>> import hdl_parser

    >>> file = hdl_parser.parse_file("examples/sv/macro_ports.sv", expand_macros=True)
    >>> for port in file.modules[0].ports:
    ...     print(f"{port.direction:6} {port.dim:14} {port.name}")
    input                 clk_i
    input                 rst_ni
    input                 in_valid
    input  [IN_WIDTH-1:0] in_data
    output                in_ready
    output                out_valid
    output [8-1:0]        out_data
    input                 out_ready
    output                busy_o

    >>> file = hdl_parser.parse_file("top.sv", expand_macros=True, inc_dirs=["path/to/inc"])  # doctest: +SKIP

    ```

??? info "Example Files"

    ``` title="examples/sv/macros.svh"
    --8<-- "examples/sv/macros.svh"
    ```

    ``` title="examples/sv/macro_ports.sv"
    --8<-- "examples/sv/macro_ports.sv"
    ```

Macros which are not defined by the file or its included files, have to be handed over:

!!! example "Command Line"

    ```bash
    hdl-parser info --expand-macros --macro-file examples/sv/macros.svh top.sv
    ```

!!! example "Python"

    ```python
    >>> defines = hdl_parser.parse_defines("examples/sv/macros.svh")
    >>> defines.diagnostics
    ()
    >>> file = hdl_parser.parse_text("module top (`CLK_RST_PORTS); endmodule", expand_macros=True, macros=defines.macros)
    >>> [port.name for port in file.modules[0].ports]
    ['clk_i', 'rst_ni']

    ```

Macros in the module header which are not expanded are never dropped silently.
A warning is issued and they are listed in `unresolved_macros` of the module:

```python
>>> file = hdl_parser.parse_text("module top (`CLK_RST_PORTS, `STREAM_PORTS(in, input, output)); endmodule")
>>> for macro in file.modules[0].unresolved_macros:
...     print(macro.name, macro.args)
CLK_RST_PORTS None
STREAM_PORTS ('in', 'input', 'output')

```

Every problem found while parsing is also listed in `diagnostics` of the file, with a code, a source location
and the related item. See [Diagnostic][hdl_parser.datamodel.Diagnostic] for all codes:

```python
>>> for diag in file.diagnostics:
...     print(diag.code, diag.severity, f"{diag.loc.line}:{diag.loc.col}", diag.item)
macro-not-expanded warning 1:13 top.`CLK_RST_PORTS
macro-not-expanded warning 1:29 top.`STREAM_PORTS

```

The file is read once, from top to bottom, like a compiler does:
a macro has to be defined before its use, a later `` `define `` replaces an earlier one and `` `undef `` is followed.

### Conditions

`` `ifdef `` conditions are **not** resolved by default: all branches are kept and
ports, parameters and instances are tagged by `ifdefs`.
A macro which is defined differently in several branches is ambiguous and therefore not expanded.

On request (`--resolve-ifdefs`, `resolve_ifdefs=True`) the conditions on macros which are **known to be defined**
are resolved. The code which is not compiled is removed, the remaining code is no longer tagged with this condition:

```python
>>> text = """
... `define USE_AXI
... `ifdef USE_AXI
...     `define BUS_PORTS input awvalid, output awready
... `else
...     `define BUS_PORTS input psel, output pready
... `endif
... module top (
...     `BUS_PORTS,
... `ifdef DEBUG
...     output dbg,
... `endif
...     input clk
... );
... endmodule
... """
>>> file = hdl_parser.parse_text(text, expand_macros=True, resolve_ifdefs=True)
>>> for port in file.modules[0].ports:
...     print(port.name, port.ifdefs)
awvalid ()
awready ()
dbg ('DEBUG',)
clk ()

```

This is safe by design. A macro without a visible `` `define `` (like `DEBUG` above) is not necessarily undefined.
It may be defined on the command line of your simulator, by the tool itself or by a file which has been compiled earlier.
Conditions on such macros are never resolved, so nothing is removed by a wrong guess.
A macro which is defined under such a condition is expanded, but it is not known to be defined.

Macros which are defined outside of your files are handed over by `--macro-file` / `macros=`.

If you know all definitions (your filelist and its `+define+` / `--define` options are complete), the
**closed world** (`--closed-world`, `closed_world=True`) resolves the remaining conditions like a compiler does:
a macro which is neither defined by the given macros, nor by the file or its included files, is undefined.
`DEBUG` above is undefined, so `dbg` is removed:

```python
>>> file = hdl_parser.parse_text(text, expand_macros=True, resolve_ifdefs=True, closed_world=True)
>>> [port.name for port in file.modules[0].ports]
['awvalid', 'awready', 'clk']

```

A project (and the commands working on one, `mcp` included) leaves the conditions on macros unknown,
which any of its files or their included files define - under any condition. Only macros which are defined nowhere
are undefined. The closed world ends at an included file which is not found: it may define any macro.

!!! info "Limitations"

    * Include guards and defaults (`` `ifndef X `` directly followed by `` `define X ``) are assumed to be compiled.
    * `` `ifdef `` conditions on macros without a known definition are resolved in the closed world only.
    * Unknown macros are reported for the module header only (parameter and port list), not for the module body.
    * `` `include `` statements are followed for their `` `define `` statements only.
      The included code itself is not inserted.
