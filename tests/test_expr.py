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

"""Evaluation Of Constant Expressions."""

from pytest import mark, raises

from hdl_parser._expr import DictNames, Num, Unknown, evaluate, evaluate_dims

NAMES = DictNames({"W": 8, "DEPTH": 17, "pkg::X": 3, "R": 2.5, "S": "abc", "w": 8, "depth": 17, "pkg::x": 3, "b": True})


def _value(text: str, lang: str = "sv"):
    return evaluate(text, lang, NAMES).value


@mark.parametrize(
    "text, expected",
    (
        # numbers
        ("12", 12),
        ("1_000", 1000),
        ("1.5", 1.5),
        ("2e3", 2000.0),
        ("'h10", 16),
        ("8'hFF", 255),
        ("8 'h FF", 255),
        ("4'sb1010", 10),
        ("16'd10", 10),
        ("3'o7", 7),
        ("4'hFF", 15),
        ('"abc"', "abc"),
        # arithmetic
        ("W-1", 7),
        ("2**W - 1", 255),
        ("2 ** 3 ** 2", 64),
        ("(W+1)*2", 18),
        ("-W/3", -2),
        ("7/2", 3),
        ("-7 % 3", -1),
        ("7 % -3", 1),
        ("1.5 * 2", 3.0),
        ("7 / 2.0", 3.5),
        ("32'hFFFF_FFFF + 1", 4294967296),
        # shifts, comparison, logic
        ("W << 2", 32),
        ("W >> 1", 4),
        ("W <<< 1", 16),
        ("-8 >>> 1", -4),
        ("W > 4", 1),
        ("W <= 4", 0),
        ("W == 8", 1),
        ("W != 8", 0),
        ("W === 8", 1),
        ("W !== 8", 0),
        ('"abc" == S', 1),
        ("W & 12", 8),
        ("W | 3", 11),
        ("W ^ 12", 4),
        ("W ~^ 3", -12),
        ("W ^~ 3", -12),
        ("!W", 0),
        ("!0", 1),
        ("~0", -1),
        ("~8'h0F", 240),
        ("|W", 1),
        ("|0", 0),
        ("^8'hFE", 1),
        ("&4'hF", 1),
        ("&4'h7", 0),
        ("W && 0", 0),
        ("W || 0", 1),
        ("W > 4 ? pkg::X : 0", 3),
        ("W < 4 ? 1 : W < 9 ? 2 : 3", 2),
        ("W + (W > 4 ? 1 : 2) * 2", 10),
        # just the operands needed are evaluated
        ("1 || UNKNOWN", 1),
        ("0 && UNKNOWN", 0),
        ("1 ? W : UNKNOWN", 8),
        ("0 ? f(1) : W", 8),
        ("0 ? `M(1) : W", 8),
        # concatenation and select
        ("{4'h3, 4'hC}", 0x3C),
        ("{2{4'hA}}", 0xAA),
        ("{2{2'b10, 1'b1}}", 0b101101),
        ("12'hABC[7:4]", 0xB),
        ("12'hABC[0]", 0),
        ("12'hABC[4+:4]", 0xB),
        ("12'hABC[7-:4]", 0xB),
        # casts and functions
        ("int'(R)", 3),
        ("int'(-2.5)", -3),
        ("unsigned'(W)", 8),
        ("logic'(1)", 1),
        ("W'(300)", 44),
        ("4'(255)", 15),
        ("4'('1)", 15),
        ("my_t'(5)", 5),
        ("pkg::my_t'(W)", 8),
        ("$clog2(DEPTH)", 5),
        ("$clog2(16)", 4),
        ("$clog2(1)", 0),
        ("$clog2(0)", 0),
        ("$signed(W)", 8),
        ("$unsigned(W) + 1", 9),
        ("$countones(8'hF1)", 5),
        ("$ceil(R)", 3.0),
        ("$floor(R)", 2.0),
        ("$rtoi(R)", 2),
        ("$itor(W)", 8.0),
        ("$pow(2, 3)", 8.0),
        ("$sqrt(16)", 4.0),
    ),
)
def test_sv(text, expected):
    """SystemVerilog Expressions."""
    result = _value(text)
    assert result == expected
    assert type(result) is type(expected)


def test_sv_width():
    """The Number Of Bits Is Known, If It Is Stated."""
    assert evaluate("8'hFF") == Num(255, 8)
    assert evaluate("{4'h3, 4'hC}") == Num(0x3C, 8)
    assert evaluate("'hFF") == Num(255)
    assert evaluate("W'(1)", names=NAMES) == Num(1, 8)
    assert evaluate("'1") == Num(1, fill=True)
    assert evaluate("'0") == Num(0, fill=True)
    assert evaluate("~'0") == Num(1, fill=True)
    assert evaluate("8'h0F & 8'h3C") == Num(0x0C, 8)


@mark.parametrize(
    "text, reason",
    (
        ("UNKNOWN + 1", "'UNKNOWN' is not known"),
        ("pkg::Y", "'pkg::Y' is not known"),
        ("f(3) + 1", "function 'f' is not evaluated"),
        ("pkg::f(W, 2)", "function 'pkg::f' is not evaluated"),
        ("$bits(my_t)", "the number of bits of 'my_t' is not known"),
        ("$size(x)", "'$size' is not evaluated"),
        ("$random", "'$random' is not evaluated"),
        ("4'b1x0", "''b1x0' contains x or z"),
        ("8'hzz", "''hzz' contains x or z"),
        ("`MACRO + 1", "macro `MACRO is not expanded"),
        ("'{1, 2}", "assignment pattern '{...}"),
        ("'1 + 1", "the number of bits of a fill literal ('0, '1) depends on the context"),
        ("{W, 4'h1}", "concatenation of a value without number of bits"),
        ("&W", "reduction needs a number of bits"),
        ("a.b", "member of 'a'"),
        ("cls#(8)::X", "class 'cls'"),
        ("W inside {1}", "'inside' is not understood"),
        ("1ns", "'1ns' is no number"),
        ("W / 0", "division by zero"),
        ("W % 0", "division by zero"),
        ("2 ** -1", "negative exponent"),
        ("1 << -1", "shift amount out of range"),
        ("W + S", "operand is no integer"),
        ('W == "a"', "comparison of a string and a number"),
        ("W +", "'end' is not understood"),
        (")", "')' is not understood"),
        ("(W", "')' expected, but found 'end'"),
        ("W W", "'W' is not understood"),
        ("W ? 1", "':' expected, but found 'end'"),
        ("", "no expression"),
        ("  ", "no expression"),
        ("$clog2(1, 2)", "'$clog2' is not evaluated"),
        ("0'(1)", "size of a cast is not positive"),
        ("W[9:10]", "select is out of range"),
        ("$sqrt(-1)", "math domain error"),
        ("always", "'always' is not understood"),
    ),
)
def test_sv_unknown(text, reason):
    """Nothing Is Guessed: What Is Not Known For Sure Is Unknown, With The Reason."""
    with raises(Unknown) as info:
        evaluate(text, "sv", NAMES)
    assert str(info.value) == reason


@mark.parametrize(
    "text, expected",
    (
        ("12", 12),
        ("1_000", 1000),
        ("1e3", 1000),
        ("1.5e1", 15.0),
        ("16#FF#", 255),
        ("2#1010#", 10),
        ("16#F#e1", 240),
        ('x"0F"', 15),
        ('b"101"', 5),
        ('"0101"', "0101"),
        ("'1'", "1"),
        ("true", True),
        ("FALSE", False),
        ("W - 1", 7),
        ("2**W - 1", 255),
        ("W mod 3", 2),
        ("-7 mod 3", -1),
        ("(-7) mod 3", 2),
        ("7 mod (-3)", -2),
        ("(-7) rem 3", -1),
        ("7 / 2", 3),
        ("(-7) / 2", -3),
        ("abs (-3)", 3),
        ("abs(W - 10) * 2", 4),
        ("W = 8", True),
        ("W /= 8", False),
        ("W >= 8 and DEPTH < 20", True),
        ("W > 8 or DEPTH < 20", True),
        ("W > 8 xor DEPTH < 20", True),
        ("not (W > 3)", False),
        ("not b", False),
        ("(W > 3) nand (W > 4)", False),
        ("Pkg.X + 1", 4),
        ("integer(ceil(log2(real(DEPTH))))", 5),
        ("integer(2.5)", 3),
        ("natural(W)", 8),
        ("to_integer(unsigned(W))", 8),
        ("maximum(W, 3)", 8),
        ("minimum(W, 3)", 3),
        ("to_unsigned(13, 3)", 5),
        ("floor(2.5)", 2.0),
        ("sqrt(16.0)", 4.0),
    ),
)
def test_vhdl(text, expected):
    """VHDL Expressions. Names Are Not Case Sensitive."""
    result = _value(text, "vhdl")
    assert result == expected
    assert type(result) is type(expected)
    assert evaluate('x"0F"', "vhdl") == Num(15, 8)
    assert evaluate("to_unsigned(5, 3)", "vhdl") == Num(5, 3)


@mark.parametrize(
    "text, reason",
    (
        ("UNKNOWN + 1", "'unknown' is not known"),
        ("clog2(W)", "function 'clog2' is not evaluated"),
        ("work.util.f(W)", "function 'work.util.f' is not evaluated"),
        ("W'length", "attribute of 'w'"),
        ("(others => '0')", "'others' is not understood"),
        ("(1, 2)", "aggregate"),
        ("W & W", "concatenation"),
        ("W and 1", "operand is no boolean"),
        ("not W", "operand is no boolean"),
        ("W = true", "comparison of different types"),
        ("W + true", "operand is no number"),
        ("W / 0", "division by zero"),
        ("W mod 0", "division by zero"),
        ("1.5 mod 2", "'mod' of a real"),
        ("16#XY#", "'16#XY#' is no number"),
        ("maximum(W)", "two arguments expected"),
        ("natural(1, 2)", "function 'natural' with 2 arguments"),
        ("to_unsigned(1, 0)", "size is not positive"),
        ("log2(0)", "math domain error"),
        ("W +", "'end' is not understood"),
        ("W W", "'W' is not understood"),
        ("", "no expression"),
    ),
)
def test_vhdl_unknown(text, reason):
    """Nothing Is Guessed."""
    with raises(Unknown) as info:
        evaluate(text, "vhdl", NAMES)
    assert str(info.value) == reason


@mark.parametrize(
    "dims, lang, expected",
    (
        ("[W-1:0]", "sv", 8),
        ("[0:W-1]", "sv", 8),
        ("[3:0][7:0]", "sv", 32),
        ("[4]", "sv", 4),
        ("[DEPTH][2]", "sv", 34),
        ("[pkg::X:0]", "sv", 4),
        ("[W > 4 ? 7 : 3 : 0]", "sv", 8),
        ("[$clog2(DEPTH)-1:0]", "sv", 5),
        ("[ 7 : 0 ]", "sv", 8),
        ("[1:-2]", "sv", 4),
        ("[W-1:0]", "vhdl", 8),
        ("[0:depth-1]", "vhdl", 17),
        ("", "sv", 1),
    ),
)
def test_dims(dims, lang, expected):
    """Number Of Elements Of Dimensions."""
    assert evaluate_dims(dims, lang, NAMES) == expected


@mark.parametrize(
    "dims, reason",
    (
        ("[N:0]", "'N' is not known"),
        ("[0]", "dimension '[0]' has no elements"),
        ("[R:0]", "dimension is no integer"),
        ("x[1]", "dimension 'x[1]' is not understood"),
        ("[1", "dimension '[1' is not understood"),
        ("[]", "no expression"),
    ),
)
def test_dims_unknown(dims, reason):
    """Dimensions Which Are Not Known."""
    with raises(Unknown) as info:
        evaluate_dims(dims, "sv", NAMES)
    assert str(info.value) == reason


def test_nested_too_deep():
    """Deep Nesting Is Unknown, No Crash."""
    with raises(Unknown, match="nested too deep"):
        evaluate("(" * 5000 + "1" + ")" * 5000)


@mark.parametrize(
    "text, lang, expected",
    (
        ("+W", "sv", 8),
        ("b + 1", "sv", 2),
        ("int'(W)", "sv", 8),
        ("+W", "vhdl", 8),
    ),
)
def test_more(text, lang, expected):
    """More Expressions."""
    assert _value(text, lang) == expected


@mark.parametrize(
    "text, lang, reason",
    (
        ("S ? 1 : 2", "sv", "condition is a string"),
        ("10.0 ** 1000", "sv", "(34, 'Numerical result out of range')"),
        ("$clog2(-1)", "sv", "$clog2 of a negative value"),
        ("f(1", "sv", "bracket is never closed"),
        ("'1 & 8'hFF", "sv", "the number of bits of a fill literal ('0, '1) depends on the context"),
        ("^(-1)", "sv", "reduction of a negative value needs a number of bits"),
        ("int'(1, 2)", "sv", "one argument expected"),
        ("1e", "sv", "'1e' is no number"),
        ("8'd1a", "sv", "''d1a' is no number"),
        ("0'h1", "sv", "''h1' has no bits"),
        ("{5000{1'b1}}", "sv", "replication count out of range"),
        ("$countones(-1)", "sv", "$countones of a negative value needs a number of bits"),
        ("integer(1, 2)", "vhdl", "one argument expected"),
        ("to_unsigned(1)", "vhdl", "two arguments expected"),
    ),
)
def test_more_unknown(text, lang, reason):
    """More Expressions Which Are Not Known."""
    with raises(Unknown) as info:
        evaluate(text, lang, NAMES)
    assert str(info.value) == reason
