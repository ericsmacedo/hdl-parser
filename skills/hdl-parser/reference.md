# hdl-parser Reference

All MCP tools with their arguments. The command line query of the same name (`where_used`: `where-used`) takes
the same arguments as options; run `hdl-parser <query> --help` for their spelling. Every tool but `reload` also
takes `detail`: `compact` (default) or `full`.

## `module`

One module, interface or package: parameters, ports, instances, signals, types, ... with source locations. Start with summary=true, then ask for the fields needed.

| Argument | Type | Description |
| -------- | ---- | ----------- |
| `name` (required) | string | Name or full identifier ('rtl/top.sv:top'). |
| `fields` | array of string | Fields to be returned. All by default. |
| `limit` | integer | Number of entries of every list. Default 100. 0: no limit. |
| `summary` | boolean | Names and counts only. |

## `hierarchy`

Instance tree below the module 'top'. Without 'top': the top modules of the design. Names have the labels of the generate blocks around: 'g_lane.u_sub'.

| Argument | Type | Description |
| -------- | ---- | ----------- |
| `top` | string | Name or full identifier ('rtl/top.sv:top'). |
| `depth` | integer | Number of instance levels below the top. |
| `limit` | integer | Number of nodes. Default 100. 0: no limit. |
| `fields` | array of string | Fields of every node: module, inst, definition, multiple, loc. All by default. |
| `summary` | boolean | Every node has name and module only. |
| `leaves` | boolean | Without 'top': tops without instances too (mostly unused library cells). |
| `text` | boolean | The tree as indented text 'name (module)', much smaller than JSON. |

## `where_used`

All places a module or interface is instantiated at, with file and location. Works for modules which are not defined in the project (blackboxes, hard macros) too.

| Argument | Type | Description |
| -------- | ---- | ----------- |
| `name` (required) | string | Name or full identifier ('rtl/top.sv:top'). |
| `limit` | integer | Number of entries of every list. Default 100. 0: no limit. |

## `find`

Items by name. Without wildcard: part of the name, not case sensitive. With wildcards (*, ?, [...]): the name or the full identifier ('rtl/top.sv:top.*').

| Argument | Type | Description |
| -------- | ---- | ----------- |
| `pattern` (required) | string |  |
| `kinds` | array of string: `connection`, `function`, `instance`, `interface`, `macro`, `member`, `modport`, `module`, `package`, `param`, `port`, `process`, `signal`, `typedef` | Kinds of items. All by default. |
| `limit` | integer | Number of entries of every list. Default 100. 0: no limit. |
| `fields` | array of string | Fields to be returned. All by default. |

## `diagnostics`

Problems found in the design: undefined modules, macros not expanded, files which cannot be read, ... with code, severity, message and location: `file` and `line` are where the problem is. A problem within an included file is reported once, `parsed` lists the files including it.

| Argument | Type | Description |
| -------- | ---- | ----------- |
| `severity` | string: `error`, `warning`, `info` | Minimum severity. |
| `codes` | array of string |  |
| `file` | string | Path of a file, relative to the root, or a pattern: the problems located in it or found by parsing it. |
| `exclude` | array of string | Patterns of files whose problems are left out: 'lib/stdcells/*'. A problem found by parsing other files too is kept for them. |
| `blackboxes` | array of string | Patterns of module names known to be missing: no 'undefined-module' for them. |
| `group_by` | string: `code`, `file`, `module` | Number of problems by group instead of the problems. Start with this. |
| `limit` | integer | Number of entries of every list. Default 100. 0: no limit. |

## `elaborate`

Values of the parameters and widths of the ports (in bits) of one instance, with the parameter values given down the hierarchy applied. Names are resolved across files and packages. Nothing is guessed: what is not known has 'unknown' with the reason. For generate loops with known indices, one node per iteration: 'g_lane[1].u_sub'.

| Argument | Type | Description |
| -------- | ---- | ----------- |
| `top` (required) | string | Name or full identifier ('rtl/top.sv:top'). |
| `path` | string | Instance names below the top, with generate labels: 'u_core.u_alu', 'g_lane[1].u_sub'. |
| `params` | object | Values of the parameters of the top, by name. Defaults otherwise. |
| `depth` | integer | Instance levels below the node returned too. Default 0: the node only. |
| `names` | array of string | Patterns of names of parameters and ports: 'WIDTH', '*_i'. All by default. |
| `unknown` | boolean | Only values which are not known, with the reason. |
| `limit` | integer | Number of nodes, and of parameters and ports of every node. |

## `evaluate`

Value of an expression ('$clog2(DEPTH)+1', 'pkg::WIDTH') within a module, interface or package.

| Argument | Type | Description |
| -------- | ---- | ----------- |
| `expr` (required) | string |  |
| `scope` (required) | string | Module, interface or package. Name or full identifier. |
| `params` | object | Values of the parameters of the scope, by name. Defaults otherwise. |

## `drivers`

What drives a signal: assignments (with the signals they read and their conditions), output ports of instances, the connection of an input port within the parent. Ask for the drivers of the signals read ('nets') to go further. A select within a generate loop is evaluated per iteration ('[4*i+:4]': one driver with '[3:0]', one with '[7:4]'). A select of the signal ('top.data[5]') keeps the drivers of its bits.

| Argument | Type | Description |
| -------- | ---- | ----------- |
| `path` (required) | string | Instance path of a signal: top module, instance names (with generate labels), signal: 'top.u_core.u_alu.result_o'. The index of a for generate block selects one iteration: 'top.g_st[1].data'. |
| `params` | object | Values of the parameters of the top, by name. Defaults otherwise. |
| `limit` | integer | Number of entries of every list. Default 100. 0: no limit. |
| `passthrough` | array of string | Cells which pass their inputs on to their outputs, i.e. wrappers of technology cells: 'buf_wrap', or with ports for modules which are not defined: 'BUFX2:A->Y'. |

## `loads`

What a signal drives: assignments reading it (also by a condition: 'control'), input ports of instances, the connection of an output port within the parent.

| Argument | Type | Description |
| -------- | ---- | ----------- |
| `path` (required) | string | Instance path of a signal: top module, instance names (with generate labels), signal: 'top.u_core.u_alu.result_o'. The index of a for generate block selects one iteration: 'top.g_st[1].data'. |
| `params` | object | Values of the parameters of the top, by name. Defaults otherwise. |
| `limit` | integer | Number of entries of every list. Default 100. 0: no limit. |
| `passthrough` | array of string | Cells which pass their inputs on to their outputs, i.e. wrappers of technology cells: 'buf_wrap', or with ports for modules which are not defined: 'BUFX2:A->Y'. |

## `trace`

Shortest connection from one signal to another one below the same top, hop by hop with kind and location, with 'counts' of hops, flip-flops and conditions. Stops behind flip-flops unless through_regs=true, and at undefined modules ('stopped_at').

| Argument | Type | Description |
| -------- | ---- | ----------- |
| `src` (required) | string | Instance path of the signal to start at. |
| `dst` (required) | string | Instance path of the signal to reach. |
| `params` | object | Values of the parameters of the top, by name. Defaults otherwise. |
| `through_regs` | boolean | Continue behind flip-flops. |
| `control` | boolean | Follow conditions, resets and clocks too. Default true. |
| `limit` | integer | Number of hops. Default 100. 0: no limit. |
| `passthrough` | array of string | Cells which pass their inputs on to their outputs, i.e. wrappers of technology cells: 'buf_wrap', or with ports for modules which are not defined: 'BUFX2:A->Y'. |

## `reload`

Read the project again, i.e. after files were added. Changed files are read again automatically.

## Command Line Only

| Command | Purpose |
| ------- | ------- |
| `hdl-parser project` | The whole design as one JSON document. |
| `hdl-parser schema` | JSON Schema of that document. |
| `hdl-parser mcp` | The MCP server, on standard input and output. `--blackbox PATTERN` applies to every `diagnostics` call. |
| `hdl-parser json FILE`, `info FILE`, `gen-sv-instance FILE` | Single files: JSON, Markdown tables, an instance template. They ignore `hdl-parser.toml`. |

## Project Options

Command line options of every project query and of `mcp`, and the keys of `hdl-parser.toml`.

| Option | Key | Meaning |
| ------ | --- | ------- |
| `PATHS` | `paths` | Files, or one directory with all of them. The current directory by default. |
| `-f`, `--filelist` | `filelist` | Filelist: files, `+incdir+`, `+define+`, `-y`, `-v`. |
| `-x`, `--exclude` | `exclude` | Patterns of files left out of a directory. |
| `--root` | `root` | Root directory: all paths are relative to it. |
| `-e`, `--expand-macros` | `expand_macros` | Expand `` `define `` macros. |
| `-r`, `--resolve-ifdefs` | `resolve_ifdefs` | Remove `` `ifdef `` branches which are known not to be compiled. Requires `-e`. |
| `--closed-world` | `closed_world` | Macros defined nowhere are undefined, like for a compiler. Requires `-r`. |
| `-D NAME[=VALUE]` | `defines` (table) | Macros defined for all files. |
| `-I`, `--incdir` | `inc_dirs` | Include directories. |
| `--cache` | `cache` | Keep the results within the root, parse changed files only. |
| `--cache-dir` | `cache_dir` | Keep the results in this directory. |
| `-j`, `--jobs` | `jobs` | Number of processes parsing. One per CPU by default. |
| `--blackbox` | `blackbox` | Modules known to be missing (`diagnostics`, `mcp`). |
| `--passthrough` | `passthrough` | Cells passing inputs to outputs (`drivers`, `loads`, `trace`). |
| `--exclude-file` | `exclude_problems` | Files whose problems are left out (`diagnostics`). |
| `--config FILE`, `--no-config` | | Before the query: another configuration file, or none. |

## Exit Codes

| Code | Meaning |
| ---- | ------- |
| 0 | Answer on standard output. |
| 1 | Internal failure (a bug). The reason is on standard error. |
| 2 | Wrong command line, or bad argument: `{"error": {"code": "bad-argument", ...}}`. |
| 3 | Name not found: `{"error": {"code": "not-found", "suggestions": [...]}}`. |

## Diagnostic Codes

| `code`                | Severity | Meaning                                                           |
| --------------------- | -------- | ----------------------------------------------------------------- |
| `macro-not-expanded`  | warning  | Macro in a module header is not expanded. `item` is the macro.    |
| `macro-ambiguous`     | warning  | Macro has different definitions under unknown conditions.         |
| `macro-recursive`     | warning  | Macro uses itself.                                                |
| `macro-args-missing`  | warning  | Macro with arguments is used without.                             |
| `macro-args-count`    | warning  | Macro is used with the wrong number of arguments.                 |
| `macro-bad-define`    | warning  | `` `define `` cannot be parsed.                                   |
| `include-not-found`   | warning  | Included file is not found.                                       |
| `include-unreadable`  | warning  | Included file cannot be read.                                     |
| `header-item-skipped` | warning  | Code within a parameter or port list is not understood.           |
| `missing-end`         | warning  | Module, entity or architecture without end.                       |
| `unbalanced-bracket`  | warning  | Bracket is never closed.                                          |
| `no-module`           | info     | File without module, interface or package, i.e. an included file. |
| `file-not-found`      | error    | File does not exist.                                              |
| `file-unreadable`     | error    | File cannot be read.                                              |
| `parse-failed`        | error    | File cannot be parsed. This is a bug of the parser.               |
| `duplicate-definition`| warning  | Module, interface or package is defined more than once in the project. |
| `undefined-module`    | warning  | Module of an instance is not defined in the project. `item` is the instance. |
| `filelist-not-found`  | error    | Filelist cannot be read.                                          |
| `filelist-unknown`    | warning  | Option of a filelist is not understood.                           |
| `filelist-variable`   | warning  | Environment variable used by a filelist is not defined.           |
| `statement-skipped`   | info     | Statement of a process is not understood (a task call).           |
| `multiple-drivers`    | warning  | Signal or port is driven by more than one assignment or process.  |
