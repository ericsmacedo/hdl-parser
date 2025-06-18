# MIT License
#
# Copyright (c) 2025 ericsmacedo
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
"""Test Parser."""

from pytest import mark
from test2ref import assert_refdata

from hdl_parser import File, Module, Port, parse_file, parse_text

from .conftest import EXAMPLES


@mark.parametrize("example", EXAMPLES)
def test_examples(tmp_path, example):
    """Test All Examples And Compare with 'refdata'."""
    file = parse_file(example)
    (tmp_path / "overview.json").write_text(file.overview)
    assert_refdata(test_examples, tmp_path, flavor=example.name)


def test_parse_text(tmp_path):
    """Parse Text."""
    file_path = tmp_path / "file.sv"
    text = """
module text (
    input  a_i, // Input a
    output x_o  // Output x
);
endmodule
"""
    ref = File(
        path=None,
        modules=(
            Module(
                name="text",
                params=(),
                ports=(
                    Port(
                        direction="input",
                        ptype="",
                        dtype="",
                        name="a_i",
                        dim="",
                        dim_unpacked="",
                        ifdefs=(),
                        comment=("Input a",),
                    ),
                    Port(
                        direction="output",
                        ptype="",
                        dtype="",
                        name="x_o",
                        dim="",
                        dim_unpacked="",
                        ifdefs=(),
                        comment=("Output x",),
                    ),
                ),
                insts=(),
            ),
        ),
    )
    assert ref == parse_text(text)
    ref = File(path=file_path, modules=ref.modules)
    assert ref == parse_text(text, file_path=file_path)
    assert ref == parse_text(text, file_path=str(file_path))
