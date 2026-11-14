# MIT License
#
# Copyright (c) 2026 ericsmacedo
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all
# copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.
"""Test Macro Examples In All Modes."""

import logging
import re

from pytest import mark, param
from test2ref import assert_refdata

from hdl_parser import parse_file
from hdl_parser._sv.preproc import expand

from .conftest import EXAMPLES_PATH
from .sv_invariants import check_invariants

MACROS_PATH = EXAMPLES_PATH / "sv" / "macros"
MACRO_EXAMPLES = tuple(sorted(MACROS_PATH.glob("*.sv")))
INC_DIRS = (MACROS_PATH / "inc",)
MODES = {
    "default": {},
    "expand": {"expand_macros": True, "inc_dirs": INC_DIRS},
    "resolve": {"expand_macros": True, "inc_dirs": INC_DIRS, "resolve_ifdefs": True},
}
# (example, mode) -> reason. Strict, see 'tests/test_sv_corpus.py'.
KNOWN_ISSUES = {
    ("module_macros.sv", "default"): "issue 80: a file without modules raises RuntimeError('No module found.')",
}
_DEFINE = re.compile(r"`define(?:\\\r?\n|[^\n])*")


def _cases() -> list:
    cases = []
    for path in MACRO_EXAMPLES:
        for mode in MODES:
            marks = []
            if (path.name, mode) in KNOWN_ISSUES:
                marks.append(mark.xfail(strict=True, reason=KNOWN_ISSUES[(path.name, mode)]))
            cases.append(param(path, mode, id=f"{path.name}-{mode}", marks=marks))
    return cases


def test_examples_found():
    """There Are Examples."""
    assert len(MACRO_EXAMPLES) >= 14


@mark.parametrize("path, mode", _cases())
def test_macro_examples(tmp_path, caplog, path, mode):
    """Parse Macro Example And Compare With 'refdata': Result, Messages And Preprocessed Text."""
    kwargs = MODES[mode]
    with caplog.at_level(logging.WARNING):
        file = parse_file(path, **kwargs)
    (tmp_path / "overview.json").write_text(file.overview)
    messages = [record.getMessage().replace(f"{path}: ", "") for record in caplog.records]
    (tmp_path / "messages.txt").write_text("".join(f"{message}\n" for message in messages))
    source = path.read_text()
    if kwargs:
        source = expand(source, file_path=path, inc_dirs=INC_DIRS, resolve_ifdefs=kwargs.get("resolve_ifdefs", False))
        (tmp_path / "expanded.sv").write_text(source)
        # the bodies of the defines are no code
        assert check_invariants(file, _DEFINE.sub("", source)) == []
    assert_refdata(test_macro_examples, tmp_path, flavor=f"{path.name}-{mode}")
