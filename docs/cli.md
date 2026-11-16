# Command Line Interface

This page provides documentation for our command line tools.

The commands `project`, `module`, `hierarchy`, `where-used`, `find` and `diagnostics` print JSON and have
these exit codes (see the [Guide for AI Agents](agents.md)):

| Code | Meaning                                         |
| ---- | ----------------------------------------------- |
| 0    | Answer                                          |
| 1    | Internal failure (a bug), reason on standard error |
| 2    | Wrong command line, or bad argument of a query  |
| 3    | Name not found, with suggestions                |

::: mkdocs-click
    :module: hdl_parser.cli
    :command: cli
    :prog_name: hdl-parser
