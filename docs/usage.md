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

## Macros In Module Headers

Macros which define ports or parameters in the module header are expanded,
if their `` `define `` is known. Macros defined in the same file are always known.
Macros defined in other files have to be handed over, as `` `include `` statements are **not** followed:

!!! example "Command Line"

    ```bash
    hdl-parser info --macro-file examples/sv/macros.svh examples/sv/macro_ports.sv
    ```

!!! example "Python"

    ```python
    >>> import hdl_parser

    >>> macros = hdl_parser.parse_defines("examples/sv/macros.svh")
    >>> file = hdl_parser.parse_file("examples/sv/macro_ports.sv", macros=macros)
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

    ```

??? info "Example Files"

    ``` title="examples/sv/macros.svh"
    --8<-- "examples/sv/macros.svh"
    ```

    ``` title="examples/sv/macro_ports.sv"
    --8<-- "examples/sv/macro_ports.sv"
    ```

Macros in the module header which cannot be expanded are never dropped silently.
A warning is issued and they are listed in `unresolved_macros` of the module:

```python
>>> file = hdl_parser.parse_file("examples/sv/macro_ports.sv")
>>> for macro in file.modules[0].unresolved_macros:
...     print(macro.name, macro.args)
CLK_RST_PORTS None
STREAM_PORTS ('in', 'input', 'output', 'IN_WIDTH')
STREAM_PORTS ('out', 'output', 'input')

```

!!! info "Limitations"

    * Macros are expanded within the module header only (parameter and port list), not in the module body.
    * `` `include `` statements are not followed. Use `--macro-file` / `parse_defines`.
    * `` `ifdef `` conditions are not evaluated. Include guards are fine,
      but a macro with different definitions is ambiguous and not expanded.
    * `` `undef `` is ignored.
