# MIT License
#
# Copyright (c) 2025-2026 ericsmacedo
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

import logging

from pytest import mark, raises
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


LATIN1_VHDL = """\
-- Author: Andr\u00e9
entity top is
  port (
    clk : in std_logic -- 25 \u00b0C clock
  );
end entity;
"""


def test_parse_file_latin1(tmp_path):
    """Latin-1 Encoded File Falls Back From UTF-8."""
    file_path = tmp_path / "top.vhd"
    file_path.write_bytes(LATIN1_VHDL.encode("latin-1"))
    assert b"\xe9" in file_path.read_bytes()

    file = parse_file(file_path)

    assert [module.name for module in file.modules] == ["top"]
    (port,) = file.modules[0].ports
    assert port.name == "clk"
    assert port.comment == ("-- 25 \u00b0C clock",)


def test_parse_file_utf8(tmp_path):
    """UTF-8 Encoded File Keeps Non-ASCII Comment Text."""
    file_path = tmp_path / "top.vhd"
    file_path.write_bytes(LATIN1_VHDL.encode("utf-8"))

    file = parse_file(file_path)

    assert file.modules[0].ports[0].comment == ("-- 25 \u00b0C clock",)


def test_parse_file_encoding(tmp_path):
    """Explicit Encoding Is Used Strictly."""
    file_path = tmp_path / "top.vhd"
    file_path.write_bytes(LATIN1_VHDL.encode("latin-1"))

    file = parse_file(file_path, encoding="latin-1")
    assert file.modules[0].ports[0].comment == ("-- 25 \u00b0C clock",)

    with raises(UnicodeDecodeError):
        parse_file(file_path, encoding="utf-8")


@mark.parametrize("text", ["", "// comment", "package p;\n  typedef logic [3:0] t;\nendpackage\n", "module"])
def test_no_module(tmp_path, caplog, text):
    """Files Without Modules Are Fine."""
    assert parse_text(text) == File(path=None, modules=())
    file_path = tmp_path / "file.sv"
    file_path.write_text(text)
    with caplog.at_level(logging.INFO):
        assert parse_file(file_path) == File(path=file_path, modules=())
    assert f"{file_path}: no module found." in caplog.text
