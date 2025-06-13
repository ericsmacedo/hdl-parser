[![PyPI Version](https://badge.fury.io/py/sv-simpleparser.svg)](https://badge.fury.io/py/sv-simpleparser)
[![Python Build](https://github.com/ericsmacedo/sv-simpleparser/actions/workflows/main.yml/badge.svg)](https://github.com/ericsmacedo/sv-simpleparser/actions/workflows/main.yml)
[![Documentation](https://readthedocs.org/projects/sv-simpleparser/badge/?version=stable)](https://sv-simpleparser.readthedocs.io/en/stable/)
[![Coverage Status](https://coveralls.io/repos/github/ericsmacedo/sv-simpleparser/badge.svg?branch=main)](https://coveralls.io/github/ericsmacedo/sv-simpleparser?branch=main)
[![python-versions](https://img.shields.io/pypi/pyversions/sv-simpleparser.svg)](https://pypi.python.org/pypi/sv-simpleparser)
[![semantic-versioning](https://img.shields.io/badge/semver-2.0.0-green)](https://semver.org/)

[![Downloads](https://img.shields.io/pypi/dm/sv-simpleparser.svg?label=pypi%20downloads)](https://pypi.python.org/pypi/sv-simpleparser)
[![Contributors](https://img.shields.io/github/contributors/ericsmacedo/sv-simpleparser.svg)](https://github.com/ericsmacedo/sv-simpleparser/graphs/contributors/)
[![PRs welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg?style=flat-square)](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request)
[![Issues](https://img.shields.io/github/issues/ericsmacedo/sv-simpleparser)](https://github.com/ericsmacedo/sv-simpleparser/issues)
[![PRs open](https://img.shields.io/github/issues-pr/ericsmacedo/sv-simpleparser.svg)](https://github.com/ericsmacedo/sv-simpleparser/pulls)
[![PRs done](https://img.shields.io/github/issues-pr-closed/ericsmacedo/sv-simpleparser.svg)](https://github.com/ericsmacedo/sv-simpleparser/pulls?q=is%3Apr+is%3Aclosed)


# Easy-To-Use SystemVerilog Parser

* [Documentation](https://sv-simpleparser.readthedocs.io/en/stable/)
* [PyPI](https://pypi.org/project/sv-simpleparser/)
* [Sources](https://github.com/ericsmacedo/sv-simpleparser)
* [Issues](https://github.com/ericsmacedo/sv-simpleparser/issues)

## Features

* Extract Port Lists
* Extract Parameters
* Extract Submodule Instances and their connections
* `ifdef` support
* Standards: `IEEE 1800-2009 SystemVerilog`

## Limitations

* **No Syntax Checks** - Source Code files must be syntactically correct
* **No Full Parser** - This parser intends to be simple and just extract some information from the source code. **Fast and Simple.**

## Installation

Installing it is pretty easy:

```bash
pip install sv-simpleparser
```

## Usage

See [Usage Documentation](https://sv-simpleparser.readthedocs.io/en/stable/usage/)
