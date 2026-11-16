<h1 align="center">hdl-parser</h1>

<p align="center">
  <b>Fast, dependable answers about SystemVerilog and VHDL designs — for engineers, scripts and AI agents.</b>
</p>

<p align="center">
  <a href="https://pypi.org/project/hdl-parser/"><img src="https://badge.fury.io/py/hdl-parser.svg" alt="PyPI Version"></a>
  <a href="https://pypi.python.org/pypi/hdl-parser"><img src="https://img.shields.io/pypi/pyversions/hdl-parser.svg" alt="Python Versions"></a>
  <a href="https://github.com/ericsmacedo/hdl-parser/actions/workflows/main.yml"><img src="https://github.com/ericsmacedo/hdl-parser/actions/workflows/main.yml/badge.svg" alt="Build"></a>
  <a href="https://coveralls.io/github/ericsmacedo/hdl-parser?branch=main"><img src="https://coveralls.io/repos/github/ericsmacedo/hdl-parser/badge.svg?branch=main" alt="Coverage"></a>
  <a href="https://hdl-parser.readthedocs.io/en/stable/"><img src="https://readthedocs.org/projects/hdl-parser/badge/?version=stable" alt="Documentation"></a>
  <a href="https://pypi.python.org/pypi/hdl-parser"><img src="https://img.shields.io/pypi/dm/hdl-parser.svg?label=downloads" alt="Downloads"></a>
  <a href="https://github.com/ericsmacedo/hdl-parser/blob/main/LICENSE"><img src="https://img.shields.io/github/license/ericsmacedo/hdl-parser" alt="License"></a>
</p>

<p align="center">
  <a href="https://hdl-parser.readthedocs.io/en/stable/">Documentation</a> ·
  <a href="https://hdl-parser.readthedocs.io/en/stable/usage/">Usage</a> ·
  <a href="https://hdl-parser.readthedocs.io/en/stable/agents/">AI Agents &amp; MCP</a> ·
  <a href="https://hdl-parser.readthedocs.io/en/stable/cli/">CLI Reference</a> ·
  <a href="https://github.com/ericsmacedo/hdl-parser/issues">Issues</a>
</p>

---

**hdl-parser** reads your RTL and tells you what is in it: modules, ports, parameters, instances, signals,
processes, packages and types — and, across a whole project, the hierarchy, where a module is used, the value of
every parameter and what drives a signal. It is a pure-Python library and command line tool, installs with `pip`,
and needs no simulator, no EDA license and no compiled dependencies.

```bash
pip install hdl-parser
```

## Why hdl-parser?

* **SystemVerilog and VHDL** — one data model for both. VHDL entities, generics, records and processes map onto
  the same modules, parameters, types and processes.
* **Whole designs, not just files** — load a filelist (`+incdir+`, `+define+`, `-v`, `-y`) or a directory and ask
  about the hierarchy, where-used, parameter values and connectivity across all files.
* **Real elaboration** — parameter overrides are applied down the hierarchy; port widths, `$bits()`, enums and
  package constants are evaluated.
* **Connectivity** — `drivers`, `loads` and `trace` follow a signal through assignments, flip-flops and instance
  ports, with clock and enable conditions.
* **Never guesses** — every answer points to a file and line. What cannot be known has no value, but a reason.
  Problems are reported as structured diagnostics, never hidden.
* **Robust on real code** — `` `ifdef ``/`` `elsif `` support, optional macro expansion, and one bad file does not
  stop the rest of the project. Snapshot-tested on Ibex, OpenTitan, PULP `common_cells` and AXI, NEORV32,
  Microwatt, PoC, SURF and Potato.
* **Fast** — a lightweight extractor rather than a full compiler, with parallel parsing (`--jobs`) and an
  incremental cache (`--cache`) for large designs.
* **Built for AI agents** — small, compact JSON answers with a published JSON Schema, stable exit codes and a
  built-in [MCP server](https://hdl-parser.readthedocs.io/en/stable/agents/) (`hdl-parser mcp`).

## Quick Start

### Python

```python
import hdl_parser

file = hdl_parser.parse_file("examples/sv/adder.sv")
module = file.modules[0]

for port in module.ports:
    print(port.direction, port.name, port.dim)
# input  A [DATA_WIDTH-1:0]
# input  B [DATA_WIDTH-1:0]
# output X [DATA_WIDTH:0]
# ...

print([(inst.name, inst.module) for inst in module.insts])
# [('u_test_module', 'test_module')]
```

Work on a whole design with a `Project`:

```python
from hdl_parser import Project

project = Project.from_dir("tests/corpus/sv/ibex")    # or Project.from_filelist("top.f")

project.where_used("ibex_alu")                       # every instance of ibex_alu
project.hierarchy("ibex_ex_block")                   # instance tree
tree = project.elaborate("ibex_cs_registers", params={"PMPNumRegions": 8}, depth=1)
tree.ports["csr_addr_i"].value                       # 12 (bits, resolved from ibex_pkg::csr_num_e)
project.drivers("ibex_top.u_ibex_core.if_stage_i.instr_rdata_id_o")
```

### Command Line

Document a module as Markdown tables:

```bash
hdl-parser info examples/sv/adder.sv
```

```markdown
### Ports
| Name     | Dimension          | I/O      | Functional Description |
|----------|--------------------|----------|------------------------|
| `A`      | `[DATA_WIDTH-1:0]` | `input`  | Packed input operand A |
| `B`      | `[DATA_WIDTH-1:0]` | `input`  | Packed input operand B |
| `X`      | `[DATA_WIDTH:0]`   | `output` | Packed sum output      |
```

Generate an instantiation template:

```bash
hdl-parser gen-sv-instance examples/sv/adder.sv
```

```systemverilog
adder #(
    .DATA_WIDTH (DATA_WIDTH),
    .OUTPUT_WIDTH (OUTPUT_WIDTH)
) u_adder (
    .A (A),
    .B (B),
    .X (X),
    ...
);
```

Ask questions about a design (the current directory, a directory, files, or `-f top.f`):

```bash
hdl-parser hierarchy --top ibex_top --text   # instance tree
hdl-parser where-used ibex_alu               # where is a module instantiated?
hdl-parser module ibex_alu --summary         # a module in brief
hdl-parser find 'rst_*'                      # items by name
hdl-parser elaborate ibex_top -p RV32E=1     # parameter values and port widths
hdl-parser drivers top.u_core.result_o       # what drives a signal?
hdl-parser trace top.rst_ni top.u_core.state_q
hdl-parser diagnostics --group-by code       # what could not be resolved?
```

```json
{
  "query": "drivers",
  "net": {"path": "ibex_top.u_ibex_core.if_stage_i.instr_rdata_id_o", "kind": "port", "direction": "output",
          "file": "ibex_if_stage.sv", "line": 72},
  "result": [
    {"kind": "ff", "nets": ["ibex_top.u_ibex_core.if_stage_i.instr_out"],
     "conds": ["ibex_top.u_ibex_core.if_stage_i.if_id_pipe_reg_we"],
     "clock": "ibex_top.u_ibex_core.if_stage_i.clk_i", "file": "ibex_if_stage.sv", "line": 659}
  ],
  "total": 1
}
```

### AI Agents (MCP)

Give your coding agent precise knowledge of your RTL:

```bash
claude mcp add hdl-parser -- hdl-parser mcp --cache
```

or in any MCP client:

```json
{"mcpServers": {"hdl-parser": {"command": "hdl-parser", "args": ["mcp", "--cache", "-f", "top.f"]}}}
```

See the [Guide for AI Agents](https://hdl-parser.readthedocs.io/en/stable/agents/).

## What Is Extracted

| Item | SystemVerilog | VHDL |
| ---- | ------------- | ---- |
| Design units | modules, interfaces, packages | entities + architectures, packages |
| Parameters | `parameter`, `localparam` | generics, constants |
| Ports | ports with direction, type, packed/unpacked dimensions | ports |
| Signals | nets and variables | signals |
| Types | enums, structs, unions, typedefs | enumerations, records, aliases |
| Functions | functions and tasks | functions and procedures |
| Processes | `always*` blocks with clock, reset and assignments | processes |
| Assignments | `assign` | concurrent signal assignments |
| Instances | parameter values, connections, generate blocks | `generic map`, `port map`, components |
| Interfaces | modports | — |

Comments next to a declaration are kept as its description, and every item carries its source location.
See [What Is Extracted](https://hdl-parser.readthedocs.io/en/stable/usage/#what-is-extracted).

## Scope

hdl-parser is deliberately **not** a compiler or linter:

* It expects syntactically correct code and performs no syntax checks.
* It extracts structure; it does not simulate or synthesize.
* Connectivity is tracked per whole signal; bit selects are kept as text.

If you need a full IEEE 1800 front end, use a tool like Slang or Verible. If you want quick, scriptable answers
about a design in pure Python, use hdl-parser.

## Contributing

Contributions are welcome — see [CONTRIBUTING.md](https://github.com/ericsmacedo/hdl-parser/blob/main/CONTRIBUTING.md).
Bug reports with a small HDL snippet are especially helpful.

## Authors

* [Eric Macedo](mailto:ericsmacedo@gmail.com)
* [Daniel Jakschik](mailto:iccode17@gmail.com)

## License

[MIT](https://github.com/ericsmacedo/hdl-parser/blob/main/LICENSE)
