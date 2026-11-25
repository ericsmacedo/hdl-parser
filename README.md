[![PyPI Version](https://badge.fury.io/py/hdl-parser.svg)](https://badge.fury.io/py/hdl-parser)
[![Python Build](https://github.com/ericsmacedo/hdl-parser/actions/workflows/main.yml/badge.svg)](https://github.com/ericsmacedo/hdl-parser/actions/workflows/main.yml)
[![Documentation](https://readthedocs.org/projects/hdl-parser/badge/?version=stable)](https://hdl-parser.readthedocs.io/en/stable/)
[![Coverage Status](https://coveralls.io/repos/github/ericsmacedo/hdl-parser/badge.svg?branch=main)](https://coveralls.io/github/ericsmacedo/hdl-parser?branch=main)
[![python-versions](https://img.shields.io/pypi/pyversions/hdl-parser.svg)](https://pypi.python.org/pypi/hdl-parser)
[![semantic-versioning](https://img.shields.io/badge/semver-2.0.0-green)](https://semver.org/)

[![Downloads](https://img.shields.io/pypi/dm/hdl-parser.svg?label=pypi%20downloads)](https://pypi.python.org/pypi/hdl-parser)
[![Contributors](https://img.shields.io/github/contributors/ericsmacedo/hdl-parser.svg)](https://github.com/ericsmacedo/hdl-parser/graphs/contributors/)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request)
[![Issues](https://img.shields.io/github/issues/ericsmacedo/hdl-parser)](https://github.com/ericsmacedo/hdl-parser/issues)
[![PRs open](https://img.shields.io/github/issues-pr/ericsmacedo/hdl-parser.svg)](https://github.com/ericsmacedo/hdl-parser/pulls)
[![PRs done](https://img.shields.io/github/issues-pr-closed/ericsmacedo/hdl-parser.svg)](https://github.com/ericsmacedo/hdl-parser/pulls?q=is%3Apr+is%3Aclosed)


# Easy-To-Use SystemVerilog And VHDL Parser

* [Documentation](https://hdl-parser.readthedocs.io/en/stable/)
* [PyPI](https://pypi.org/project/hdl-parser/)
* [Sources](https://github.com/ericsmacedo/hdl-parser)
* [Issues](https://github.com/ericsmacedo/hdl-parser/issues)

## Features

* SystemVerilog, Verilog and VHDL
* Extract ports, parameters, signals, types, functions, processes and continuous assignments
* Extract submodule instances and their connections
* `ifdef` support, optionally resolved (`--resolve-ifdefs`, `--closed-world`)
* Optional expansion of macros (ports, parameters and instances created by macros)
* Projects: hierarchy, where-used, diagnostics across files, configured by `hdl-parser.toml`
* Elaboration: values of parameters and widths of ports per instance (`elaborate`, `evaluate`)
* Connectivity: drivers and loads of signals and bits across the hierarchy, and how one signal reaches another
  (`drivers`, `loads`, `trace`)
* Made for AI agents: small JSON answers with source locations (`hdl-parser module`, `hierarchy`, `where-used`,
  `find`, `diagnostics`, `elaborate`, `evaluate`, `drivers`, `loads`, `trace`) and an MCP server (`hdl-parser mcp`). See the
  [Guide for AI Agents](https://hdl-parser.readthedocs.io/en/stable/agents/) and the agent skill in
  [skills/hdl-parser](https://github.com/ericsmacedo/hdl-parser/blob/main/skills/hdl-parser/SKILL.md)
* Standards: `IEEE 1800-2009 SystemVerilog`, VHDL

## Limitations

* **No Syntax Checks** - Source code is not checked. Code which is not syntactically correct may give incomplete
  results; what is not understood is reported as diagnostic
* **No Full Parser** - This parser intends to be simple and just extract some information from the source code. **Fast and Simple.**

## Installation

Installing it is pretty easy:

```bash
pip install hdl-parser
```

## Authors

* [Eric Macedo](mailto:ericsmacedo@gmail.com)
* [Daniel Jakschik](mailto:iccode17@gmail.com)

## Usage

See [Usage Documentation](https://hdl-parser.readthedocs.io/en/stable/usage/)
