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
| `processes`    | modules, interfaces          | `always` blocks (VHDL: processes) with their clock and reset       |
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
    >>> macros = hdl_parser.parse_defines("examples/sv/macros.svh")
    >>> file = hdl_parser.parse_text("module top (`CLK_RST_PORTS); endmodule", expand_macros=True, macros=macros)
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

!!! info "Limitations"

    * Include guards and defaults (`` `ifndef X `` directly followed by `` `define X ``) are assumed to be compiled.
    * `` `ifdef `` conditions on macros without a known definition are never resolved.
      There is no way to declare a macro as undefined.
    * Unknown macros are reported for the module header only (parameter and port list), not for the module body.
    * `` `include `` statements are followed for their `` `define `` statements only.
      The included code itself is not inserted.
