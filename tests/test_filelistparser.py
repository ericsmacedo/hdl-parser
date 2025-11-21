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

from pathlib import Path

from hdl_parser import parse_filelist


def test_filelistparser(examples):
    """Test FileList Parser."""
    filelist = examples / "sv" / "filelist.f"
    filepaths = []
    incdirs = []
    parse_filelist(filepaths, incdirs, filelist)
    assert filepaths == [
        examples / "sv" / "adder.sv",
        examples / "sv" / "instances_example.sv",
        examples / "sv" / "packed_unpacked.sv",
        examples / "sv" / "bcd_adder.sv",
    ]
    assert incdirs == [examples / "sv" / "inc"]


def test_filelistparser_rel(examples):
    """Test FileList Parser."""
    examples = examples.relative_to(Path().resolve())
    filelist = examples / "sv" / "filelist.f"
    filepaths = []
    incdirs = []
    parse_filelist(filepaths, incdirs, filelist)
    assert filepaths == [
        examples / "sv" / "adder.sv",
        examples / "sv" / "instances_example.sv",
        examples / "sv" / "packed_unpacked.sv",
        examples / "sv" / "bcd_adder.sv",
    ]
    assert incdirs == [examples / "sv" / "inc"]
