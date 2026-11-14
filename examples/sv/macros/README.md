# Macro Examples

Small modules which use macros and `` `ifdef `` conditions in the ways found in real projects.
They are parsed in three modes by `tests/test_macro_examples.py` and compared with reference data:

| Mode | Options |
|---|---|
| `default` | none |
| `expand` | `expand_macros` |
| `resolve` | `expand_macros` and `resolve_ifdefs` |

The include directory is `inc`.

| File | Topic |
|---|---|
| `port_macros.sv` | Ports by macros with arguments, defaults, token pasting and comments within arguments |
| `param_macros.sv` | Parameters by macros, macros in defaults and dimensions, stringification |
| `bus_select.sv` | A define of the configuration selects the definition of another macro |
| `cond_ports.sv` | `` `ifdef ``, `` `ifndef ``, `` `elsif `` around parameters, ports, instances and modules |
| `cond_in_macro.sv` | Conditions and defines within macros |
| `nested_macros.sv` | Macros using macros, macros as arguments, default and empty arguments |
| `nonansi_ports.sv` | Non-ANSI header, ports declared by macros in the module body |
| `inst_macros.sv` | Instances and connections by macros |
| `module_macros.sv` | Module headers and entire modules by macros |
| `reg_macros.sv` | Registers, generate blocks and assertions by macros |
| `type_macros.sv` | Macros as port type, type definitions by macros |
| `redefine.sv` | Redefinition, `` `undef ``, local macros and use before definition |
| `include_chain.sv` | Nested includes with include guards, a missing include |
| `unresolved.sv` | Macros which cannot be expanded: unknown, used wrong, ambiguous, recursive |
