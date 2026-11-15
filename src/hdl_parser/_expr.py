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

"""Evaluation Of Constant Expressions.

[evaluate][hdl_parser._expr.evaluate] calculates the value of a SystemVerilog or VHDL expression, as it is used
for parameters and dimensions: `$clog2(DEPTH) + 1`, `2**N - 1`.

Nothing is ever guessed. An expression which cannot be evaluated for sure raises
[Unknown][hdl_parser._expr.Unknown] with the reason: a name without known value, a function call, an `x`, ...

The names used by an expression are looked up through [Names][hdl_parser._expr.Names].
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Protocol

from ._sv.tokenizer import MACRO, SYS, TYPE_KEYWORDS
from ._sv.tokenizer import tokenize as tokenize_sv
from ._tokens import EOF, ID, KW, NUM, STR, Token
from ._vhdl.tokenizer import tokenize as tokenize_vhdl

Scalar = int | float | str | bool
"""Value of an expression."""


class Unknown(Exception):  # noqa: N818
    """The Value Of An Expression Is Not Known. The message tells the reason."""


@dataclass(frozen=True)
class Num:
    """Value Of An Expression.

    Attributes:
        value: The value.
        width: Number of bits, if stated by the expression: `8'hFF`, a concatenation, a cast.
        fill: SystemVerilog `'0` and `'1`: all bits are `value`. The number of bits depends on the context.
    """

    value: Scalar
    width: int | None = None
    fill: bool = False


class Names(Protocol):
    """Lookup Of The Names Used By An Expression."""

    def value(self, path: tuple[str, ...]) -> Num:
        """Value of the name `path` (`("WIDTH",)`, `("pkg", "WIDTH")`). Raises `Unknown`."""

    def bits(self, text: str) -> int:
        """Number of bits of the type or name `text`: the result of `$bits(text)`. Raises `Unknown`."""


class DictNames:
    """Names With Known Values. Used for expressions on their own."""

    def __init__(self, values: Mapping[str, Scalar] | None = None):
        self.values = values or {}

    def value(self, path: tuple[str, ...]) -> Num:
        name = "::".join(path)
        if name not in self.values:
            raise Unknown(f"'{name}' is not known")
        return Num(self.values[name])

    def bits(self, text: str) -> int:
        raise Unknown(f"the number of bits of '{text}' is not known")


Thunk = Callable[[], Num]
"""Expression which is evaluated on request: just the operands needed are evaluated."""


def _int(num: Num, what: str = "operand") -> int:
    """Integer value of `num`."""
    if num.fill:
        raise Unknown("the number of bits of a fill literal ('0, '1) depends on the context")
    if isinstance(num.value, bool):
        return int(num.value)
    if not isinstance(num.value, int):
        raise Unknown(f"{what} is no integer")
    return num.value


def _number(num: Num) -> int | float:
    if isinstance(num.value, float):
        return num.value
    return _int(num)


def _truth(num: Num) -> bool:
    if isinstance(num.value, str):
        raise Unknown("condition is a string")
    return bool(_number(num))


def _divide(left: float, right: float) -> int | float:
    if not right:
        raise Unknown("division by zero")
    if isinstance(left, int) and isinstance(right, int):
        # integer division truncates towards zero
        quotient = abs(left) // abs(right)
        return quotient if (left < 0) == (right < 0) else -quotient
    return left / right


def _remainder(left: int, right: int) -> int:
    """Remainder with the sign of `left`."""
    if not right:
        raise Unknown("division by zero")
    return left - right * int(_divide(left, right))


def _power(base: float, exponent: float) -> int | float:
    if isinstance(base, int) and isinstance(exponent, int) and exponent < 0:
        raise Unknown("negative exponent")
    try:
        return base**exponent
    except (OverflowError, ZeroDivisionError) as exc:
        raise Unknown(str(exc)) from None


def _shift(value: int, amount: int, left: bool) -> int:
    if amount < 0 or amount > 4096:  # noqa: PLR2004
        raise Unknown("shift amount out of range")
    return value << amount if left else value >> amount


def _clog2(value: int) -> int:
    if value < 0:
        raise Unknown("$clog2 of a negative value")
    return (value - 1).bit_length() if value > 1 else 0


def _mask(value: int, width: int) -> int:
    return value & ((1 << width) - 1)


def _math(func: Callable[[float], float], value: float) -> float:
    try:
        return func(value)
    except (ValueError, OverflowError) as exc:
        raise Unknown(str(exc)) from None


class _Parser:
    """Common Part Of The Expression Parsers: a Pratt parser creating `Thunk`s."""

    def __init__(self, tokens: list[Token], names: Names):
        self.toks = tokens
        self.pos = 0
        self.names = names

    def peek(self, offset: int = 0) -> Token:
        idx = self.pos + offset
        return self.toks[idx] if idx < len(self.toks) else self.toks[-1]

    def next(self) -> Token:
        tok = self.peek()
        self.pos += 1
        return tok

    def expect(self, text: str) -> None:
        tok = self.next()
        if tok.text != text:
            raise Unknown(f"'{text}' expected, but found '{tok.text or 'end'}'")

    def adjacent(self, offset: int = 0) -> bool:
        """The token at `offset` and the one behind are not separated."""
        return self.peek(offset).end == self.peek(offset + 1).start

    def arguments(self) -> list[Thunk]:
        """Parse `(expression {, expression})`."""
        self.expect("(")
        args = []
        while self.peek().text != ")":
            args.append(self.expression())
            if self.peek().text != ")":
                self.expect(",")
        self.next()
        return args

    def skip_group(self) -> None:
        """Skip the bracket group at the current position."""
        depth = 0
        while True:
            tok = self.next()
            if tok.text in "([{" and tok.text:
                depth += 1
            elif tok.text in ")]}" and tok.text:
                depth -= 1
                if depth <= 0:
                    return
            elif tok.kind == EOF:
                raise Unknown("bracket is never closed")

    def expression(self, min_prec: int = 0) -> Thunk:
        raise NotImplementedError

    def parse(self) -> Num:
        """Parse all tokens and return the value."""
        thunk = self.expression()
        if self.peek().kind != EOF:
            raise Unknown(f"'{self.peek().text}' is not understood")
        return thunk()


# --- SystemVerilog ---

_SV_FUNCTIONS: dict[str, Callable[[int | float], int | float]] = {
    "$ceil": lambda value: float(_math(math.ceil, value)),
    "$floor": lambda value: float(_math(math.floor, value)),
    "$rtoi": lambda value: int(_math(math.trunc, value)),
    "$itor": float,
    "$ln": lambda value: _math(math.log, value),
    "$log10": lambda value: _math(math.log10, value),
    "$sqrt": lambda value: _math(math.sqrt, value),
    "$abs": abs,
}
_SV_CASTS = frozenset((*TYPE_KEYWORDS, "signed", "unsigned"))
_SV_INT_CASTS = frozenset(("int", "integer", "longint", "shortint", "byte"))
_SV_DIGITS = {"b": 2, "o": 8, "d": 10, "h": 16}
_SV_BITS = {"b": 1, "o": 3, "h": 4}


def _sv_compare(func: Callable[[Scalar, Scalar], bool]) -> Callable[[Num, Num], Num]:
    def compare(left: Num, right: Num) -> Num:
        if isinstance(left.value, str) or isinstance(right.value, str):
            if not (isinstance(left.value, str) and isinstance(right.value, str)):
                raise Unknown("comparison of a string and a number")
            return Num(int(func(left.value, right.value)), 1)
        return Num(int(func(_number(left), _number(right))), 1)

    return compare


def _sv_arith(func: Callable[[int | float, int | float], int | float]) -> Callable[[Num, Num], Num]:
    return lambda left, right: Num(func(_number(left), _number(right)))


def _sv_bitwise(func: Callable[[int, int], int]) -> Callable[[Num, Num], Num]:
    def bitwise(left: Num, right: Num) -> Num:
        width = left.width if left.width == right.width else None
        if left.fill or right.fill:
            raise Unknown("the number of bits of a fill literal ('0, '1) depends on the context")
        return Num(func(_int(left), _int(right)), width)

    return bitwise


# operator -> (precedence, function). The operands of `&&`, `||` and `?:` are evaluated on request.
_SV_BINARY: dict[str, tuple[int, Callable[[Num, Num], Num]]] = {
    "**": (12, _sv_arith(_power)),
    "*": (11, _sv_arith(lambda left, right: left * right)),
    "/": (11, _sv_arith(_divide)),
    "%": (11, lambda left, right: Num(_remainder(_int(left), _int(right)))),
    "+": (10, _sv_arith(lambda left, right: left + right)),
    "-": (10, _sv_arith(lambda left, right: left - right)),
    "<<": (9, lambda left, right: Num(_shift(_int(left), _int(right), True))),
    "<<<": (9, lambda left, right: Num(_shift(_int(left), _int(right), True))),
    ">>": (9, lambda left, right: Num(_shift(_int(left), _int(right), False))),
    ">>>": (9, lambda left, right: Num(_shift(_int(left), _int(right), False))),
    "<": (8, _sv_compare(lambda left, right: left < right)),  # type: ignore[operator]
    "<=": (8, _sv_compare(lambda left, right: left <= right)),  # type: ignore[operator]
    ">": (8, _sv_compare(lambda left, right: left > right)),  # type: ignore[operator]
    ">=": (8, _sv_compare(lambda left, right: left >= right)),  # type: ignore[operator]
    "==": (7, _sv_compare(lambda left, right: left == right)),
    "!=": (7, _sv_compare(lambda left, right: left != right)),
    "===": (7, _sv_compare(lambda left, right: left == right)),
    "!==": (7, _sv_compare(lambda left, right: left != right)),
    "&": (6, _sv_bitwise(lambda left, right: left & right)),
    "^": (5, _sv_bitwise(lambda left, right: left ^ right)),
    "~^": (5, _sv_bitwise(lambda left, right: ~(left ^ right))),
    "^~": (5, _sv_bitwise(lambda left, right: ~(left ^ right))),
    "|": (4, _sv_bitwise(lambda left, right: left | right)),
}
_SV_TWO_TOKENS = frozenset(("**", "~^", "^~"))
_SV_AND, _SV_OR, _SV_COND = 3, 2, 1


class _SvParser(_Parser):
    """SystemVerilog Expressions."""

    def operator(self) -> str:
        """The binary operator at the current position. Some consist of two tokens: `**`, `~^`, `^~`."""
        text = self.peek().text
        if text in ("+", "-") and self.peek(1).text == ":":
            # part of a select: [base+:width]
            return ""
        if text in ("*", "~", "^") and self.adjacent() and text + self.peek(1).text in _SV_TWO_TOKENS:
            return text + self.peek(1).text
        return text

    def expression(self, min_prec: int = 0) -> Thunk:
        left = self.unary()
        while True:
            operator = self.operator()
            if operator in _SV_BINARY:
                prec, func = _SV_BINARY[operator]
                if prec < min_prec:
                    return left
                self.pos += 2 if operator in _SV_TWO_TOKENS else 1
                left = self.binary(func, left, self.expression(prec + 1))
            elif operator == "&&" and min_prec <= _SV_AND:
                self.next()
                left = self.logical(left, self.expression(_SV_AND + 1), stop=False)
            elif operator == "||" and min_prec <= _SV_OR:
                self.next()
                left = self.logical(left, self.expression(_SV_OR + 1), stop=True)
            elif operator == "?" and min_prec <= _SV_COND:
                self.next()
                then = self.expression(_SV_COND)
                self.expect(":")
                left = self.conditional(left, then, self.expression(_SV_COND))
            else:
                return left

    @staticmethod
    def binary(func: Callable[[Num, Num], Num], left: Thunk, right: Thunk) -> Thunk:
        return lambda: func(left(), right())

    @staticmethod
    def logical(left: Thunk, right: Thunk, stop: bool) -> Thunk:
        """`&&` (`stop` is false) and `||`: the right operand is evaluated, if the left one does not decide."""

        def evaluate() -> Num:
            if _truth(left()) == stop:
                return Num(int(stop), 1)
            return Num(int(_truth(right())), 1)

        return evaluate

    @staticmethod
    def conditional(cond: Thunk, then: Thunk, otherwise: Thunk) -> Thunk:
        return lambda: then() if _truth(cond()) else otherwise()

    def unary(self) -> Thunk:  # noqa: PLR0911
        tok = self.peek()
        text = tok.text
        if text in ("+", "-", "!", "~", "&", "|", "^") and tok.kind not in (STR, ID):
            self.next()
            operand = self.unary()
            if text == "+":
                return lambda: Num(_number(operand()))
            if text == "-":
                return lambda: Num(-_number(operand()))
            if text == "!":
                return lambda: Num(int(not _truth(operand())), 1)
            if text == "~":
                return lambda: self.invert(operand())
            if text == "|":
                return lambda: Num(int(_int(operand()) != 0), 1)
            if text == "^":
                return lambda: Num(self.parity(operand()), 1)
            return lambda: self.reduce_and(operand())
        return self.postfix(self.primary())

    @staticmethod
    def invert(num: Num) -> Num:
        if num.fill:
            return Num(int(not num.value), fill=True)
        value = _int(num)
        return Num(~value if num.width is None else _mask(~value, num.width), num.width)

    @staticmethod
    def parity(num: Num) -> int:
        value = _int(num)
        if value < 0:
            raise Unknown("reduction of a negative value needs a number of bits")
        return value.bit_count() % 2

    @staticmethod
    def reduce_and(num: Num) -> Num:
        if num.width is None:
            raise Unknown("reduction needs a number of bits")
        return Num(int(_int(num) == (1 << num.width) - 1), 1)

    def postfix(self, operand: Thunk) -> Thunk:
        """Parse what follows a primary: `'(expression)` (a cast) and `[index]`."""
        while True:
            if self.peek().text == "'" and self.peek(1).text == "(":
                size = operand
                self.next()
                (inner,) = self.single_argument()
                operand = self.size_cast(size, inner)
            elif self.peek().text == "[":
                operand = self.select(operand)
            else:
                return operand

    def single_argument(self) -> list[Thunk]:
        args = self.arguments()
        if len(args) != 1:
            raise Unknown("one argument expected")
        return args

    @staticmethod
    def size_cast(size: Thunk, inner: Thunk) -> Thunk:
        def evaluate() -> Num:
            width = _int(size(), "size of a cast")
            num = inner()
            if width <= 0:
                raise Unknown("size of a cast is not positive")
            if num.fill:
                return Num((1 << width) - 1 if num.value else 0, width)
            return Num(_mask(_int(num), width), width)

        return evaluate

    def select(self, operand: Thunk) -> Thunk:
        """Parse `[index]`, `[high:low]`, `[base+:width]` or `[base-:width]`."""
        self.next()
        first = self.expression()
        kind = self.peek().text
        second = None
        if kind in ("+", "-") and self.peek(1).text == ":":
            self.next()
            kind += ":"
        if kind in (":", "+:", "-:"):
            self.next()
            second = self.expression()
        self.expect("]")

        def evaluate() -> Num:
            value = _int(operand())
            low = _int(first())
            width = 1
            if second is not None:
                other = _int(second())
                if kind == ":":
                    low, width = other, low - other + 1
                elif kind == "+:":
                    width = other
                else:
                    low, width = low - other + 1, other
            if low < 0 or width <= 0 or value < 0:
                raise Unknown("select is out of range")
            return Num(_mask(value >> low, width), width)

        return evaluate

    def primary(self) -> Thunk:  # noqa: C901, PLR0911, PLR0912
        tok = self.next()
        kind = tok.kind
        text = tok.text
        if kind == NUM:
            if text[0] == "'":
                return self.constant(self.based(text, None))
            if self.peek().kind == NUM and self.peek().text[0] == "'":
                return self.constant(self.based(self.next().text, self.decimal(text)))
            return self.constant(self.number(text))
        if kind == STR:
            return self.constant(Num(text[1:-1]))
        if text == "(":
            inner = self.expression()
            self.expect(")")
            return inner
        if text == "{":
            return self.concatenation()
        if text == "'":
            fill = self.peek()
            if fill.text in ("0", "1") and self.pos and self.toks[self.pos - 1].end == fill.start:
                self.next()
                return self.constant(Num(int(fill.text), fill=True))
            raise Unknown("assignment pattern '{...}")
        if kind == ID:
            return self.name(text)
        if kind == SYS:
            return self.system_function(text)
        if kind == MACRO:
            if self.peek().text == "(":
                self.skip_group()
            return self.unknown(f"macro {text} is not expanded")
        if kind == KW and text in _SV_CASTS and self.peek().text == "'":
            self.next()
            (inner,) = self.single_argument()
            if text in _SV_INT_CASTS:
                return lambda: Num(self.round(_number(inner())))
            return inner
        raise Unknown(f"'{text or 'end'}' is not understood")

    @staticmethod
    def constant(num: Num) -> Thunk:
        return lambda: num

    @staticmethod
    def unknown(reason: str) -> Thunk:
        """Something which is not evaluated. It is unknown, if its value is needed."""

        def evaluate() -> Num:
            raise Unknown(reason)

        return evaluate

    @staticmethod
    def round(value: float) -> int:
        """Round to the nearest integer, away from zero."""
        if isinstance(value, int):
            return value
        return math.floor(abs(value) + 0.5) * (1 if value >= 0 else -1)

    @staticmethod
    def decimal(text: str) -> int:
        digits = text.replace("_", "")
        if not digits.isdecimal():
            raise Unknown(f"'{text}' is no number")
        return int(digits)

    def number(self, text: str) -> Num:
        """Value of a number without base: `12`, `1_000`, `1.5`, `2e3`."""
        digits = text.replace("_", "")
        if digits.isdecimal():
            return Num(int(digits))
        try:
            return Num(float(digits))
        except ValueError:
            raise Unknown(f"'{text}' is no number") from None

    @staticmethod
    def based(text: str, width: int | None) -> Num:
        """Value of a number with base: `'hFF`, `'sb101`."""
        body = text[1:].lower().lstrip("s")
        base, digits = body[0], body[1:].replace("_", "").strip()
        if any(digit in "xz?" for digit in digits):
            raise Unknown(f"'{text}' contains x or z")
        try:
            value = int(digits, _SV_DIGITS[base])
        except ValueError:
            raise Unknown(f"'{text}' is no number") from None
        if width is not None:
            if width <= 0:
                raise Unknown(f"'{text}' has no bits")
            value = _mask(value, width)
        return Num(value, width)

    def concatenation(self) -> Thunk:
        """Parse `{a, b}` or the replication `{count{a, b}}` behind `{`."""
        first = self.expression()
        if self.peek().text == "{":
            self.next()
            inner = self.concatenation()
            self.expect("}")

            def replicate() -> Num:
                count = _int(first(), "replication count")
                if count < 0 or count > 4096:  # noqa: PLR2004
                    raise Unknown("replication count out of range")
                return self.concat([inner()] * count)

            return replicate
        parts = [first]
        while self.peek().text == ",":
            self.next()
            parts.append(self.expression())
        self.expect("}")
        return lambda: self.concat([part() for part in parts])

    @staticmethod
    def concat(nums: list[Num]) -> Num:
        value = width = 0
        for num in nums:
            if num.width is None:
                raise Unknown("concatenation of a value without number of bits")
            value = (value << num.width) | _mask(_int(num), num.width)
            width += num.width
        return Num(value, width)

    def name(self, first: str) -> Thunk:
        """Parse `name`, `pkg::name`, a call or a cast behind the first identifier."""
        path = [first]
        while self.peek().text == "::" and self.peek(1).kind == ID:
            self.next()
            path.append(self.next().text)
        name = "::".join(path)
        if self.peek().text == "#":
            raise Unknown(f"class '{name}'")
        if self.peek().text == "(":
            self.skip_group()
            return self.unknown(f"function '{name}' is not evaluated")
        if self.peek().text == "." and self.peek(1).kind == ID:
            raise Unknown(f"member of '{name}'")
        names = self.names
        if self.peek().text == "'" and self.peek(1).text == "(":
            self.next()
            (inner,) = self.single_argument()
            return self.name_cast(tuple(path), inner)
        return lambda: names.value(tuple(path))

    def name_cast(self, path: tuple[str, ...], inner: Thunk) -> Thunk:
        """`name'(expression)`: a cast to the size `name`, if it is a known value. A cast to a type otherwise."""
        names = self.names

        def evaluate() -> Num:
            try:
                size = names.value(path)
            except Unknown:
                # a type: the value is kept
                return inner()
            return self.size_cast(lambda: size, inner)()

        return evaluate

    def system_function(self, name: str) -> Thunk:
        if name == "$bits":
            start = self.peek(1).start
            self.skip_group()
            source = self.source[start : self.toks[self.pos - 1].start].strip()
            names = self.names
            return lambda: Num(names.bits(source))
        if self.peek().text != "(":
            raise Unknown(f"'{name}' is not evaluated")
        args = self.arguments()
        if name in ("$signed", "$unsigned") and len(args) == 1:
            return args[0]
        if name == "$clog2" and len(args) == 1:
            return lambda: Num(_clog2(_int(args[0]())))
        if name == "$countones" and len(args) == 1:
            return lambda: Num(self.parity_count(args[0]()))
        if name == "$pow" and len(args) == 2:  # noqa: PLR2004
            return lambda: Num(float(_power(float(_number(args[0]())), float(_number(args[1]())))))
        if name in _SV_FUNCTIONS and len(args) == 1:
            func = _SV_FUNCTIONS[name]
            return lambda: Num(func(_number(args[0]())))
        raise Unknown(f"'{name}' is not evaluated")

    @staticmethod
    def parity_count(num: Num) -> int:
        value = _int(num)
        if value < 0:
            raise Unknown("$countones of a negative value needs a number of bits")
        return value.bit_count()

    source = ""


# --- VHDL ---

_VHDL_LOGICAL: dict[str, Callable[[bool, bool], bool]] = {
    "and": lambda left, right: left and right,
    "or": lambda left, right: left or right,
    "nand": lambda left, right: not (left and right),
    "nor": lambda left, right: not (left or right),
    "xor": lambda left, right: left != right,
    "xnor": lambda left, right: left == right,
}
_VHDL_RELATIONAL: dict[str, Callable[[Scalar, Scalar], bool]] = {
    "=": lambda left, right: left == right,
    "/=": lambda left, right: left != right,
    "<": lambda left, right: left < right,  # type: ignore[operator]
    "<=": lambda left, right: left <= right,  # type: ignore[operator]
    ">": lambda left, right: left > right,  # type: ignore[operator]
    ">=": lambda left, right: left >= right,  # type: ignore[operator]
}
_VHDL_CONVERSIONS = frozenset(
    ("natural", "positive", "to_integer", "conv_integer", "unsigned", "signed", "std_logic_vector", "std_ulogic_vector")
)
_VHDL_MATH: dict[str, Callable[[float], float]] = {
    "log2": math.log2,
    "log10": math.log10,
    "log": math.log,
    "sqrt": math.sqrt,
    "ceil": lambda value: float(math.ceil(value)),
    "floor": lambda value: float(math.floor(value)),
    "round": lambda value: float(math.floor(abs(value) + 0.5) * (1 if value >= 0 else -1)),
    "trunc": lambda value: float(math.trunc(value)),
    "real": float,
}
_VHDL_BASES = {"b": 2, "o": 8, "x": 16, "d": 10}
_VHDL_LOGICAL_PREC, _VHDL_RELATIONAL_PREC, _VHDL_ADDING_PREC, _VHDL_MULTIPLYING_PREC = 1, 2, 4, 5


def _vhdl_bool(num: Num) -> bool:
    if not isinstance(num.value, bool):
        raise Unknown("operand is no boolean")
    return num.value


class _VhdlParser(_Parser):
    """VHDL Expressions."""

    def expression(self, min_prec: int = 0) -> Thunk:
        left = self.signed()
        while True:
            tok = self.peek()
            text = tok.text
            if tok.kind == KW and text in _VHDL_LOGICAL and min_prec <= _VHDL_LOGICAL_PREC:
                self.next()
                left = self.logical(_VHDL_LOGICAL[text], left, self.expression(_VHDL_LOGICAL_PREC + 1))
            elif text in _VHDL_RELATIONAL and tok.kind != STR and min_prec <= _VHDL_RELATIONAL_PREC:
                self.next()
                left = self.relational(_VHDL_RELATIONAL[text], left, self.expression(_VHDL_RELATIONAL_PREC + 1))
            elif text in ("+", "-") and tok.kind != STR and min_prec <= _VHDL_ADDING_PREC:
                self.next()
                left = self.arithmetic(text, left, self.expression(_VHDL_ADDING_PREC + 1))
            elif text in ("*", "/", "mod", "rem") and tok.kind != STR and min_prec <= _VHDL_MULTIPLYING_PREC:
                self.next()
                left = self.arithmetic(text, left, self.expression(_VHDL_MULTIPLYING_PREC + 1))
            elif text == "&" and min_prec <= _VHDL_ADDING_PREC:
                raise Unknown("concatenation")
            else:
                return left

    @staticmethod
    def logical(func: Callable[[bool, bool], bool], left: Thunk, right: Thunk) -> Thunk:
        return lambda: Num(func(_vhdl_bool(left()), _vhdl_bool(right())))

    @staticmethod
    def relational(func: Callable[[Scalar, Scalar], bool], left: Thunk, right: Thunk) -> Thunk:
        def evaluate() -> Num:
            first, second = left().value, right().value
            if isinstance(first, str) != isinstance(second, str) or isinstance(first, bool) != isinstance(second, bool):
                raise Unknown("comparison of different types")
            return Num(func(first, second))

        return evaluate

    @staticmethod
    def arithmetic(operator: str, left: Thunk, right: Thunk) -> Thunk:
        def evaluate() -> Num:
            first, second = _vhdl_number(left()), _vhdl_number(right())
            if operator == "+":
                return Num(first + second)
            if operator == "-":
                return Num(first - second)
            if operator == "*":
                return Num(first * second)
            if operator == "/":
                return Num(_divide(first, second))
            if not isinstance(first, int) or not isinstance(second, int):
                raise Unknown(f"'{operator}' of a real")
            if operator == "rem":
                return Num(_remainder(first, second))
            if not second:
                raise Unknown("division by zero")
            # the result of `mod` has the sign of the right operand
            return Num(first % second)

        return evaluate

    def signed(self) -> Thunk:
        """Parse `[+|-] term`."""
        text = self.peek().text
        if text in ("+", "-") and self.peek().kind != STR:
            self.next()
            operand = self.expression(_VHDL_MULTIPLYING_PREC)
            if text == "-":
                return lambda: Num(-_vhdl_number(operand()))
            return lambda: Num(_vhdl_number(operand()))
        return self.factor()

    def factor(self) -> Thunk:
        """Parse `primary [** primary]`, `abs primary` or `not primary`."""
        tok = self.peek()
        if tok.kind == KW and tok.text == "abs":
            self.next()
            operand = self.primary()
            return lambda: Num(abs(_vhdl_number(operand())))
        if tok.kind == KW and tok.text == "not":
            self.next()
            operand = self.primary()
            return lambda: Num(not _vhdl_bool(operand()))
        base = self.primary()
        if self.peek().text == "**":
            self.next()
            exponent = self.primary()
            return lambda: Num(_power(_vhdl_number(base()), _vhdl_number(exponent())))
        return base

    def primary(self) -> Thunk:
        tok = self.next()
        kind = tok.kind
        text = tok.text
        if kind == NUM:
            num = self.number(text)
            return lambda: num
        if kind == STR:
            # a string or a character: "abc", '1'
            num = Num(text[1:-1].replace('""', '"'))
            return lambda: num
        if text == "(":
            inner = self.expression()
            if self.peek().text != ")":
                raise Unknown("aggregate")
            self.next()
            return inner
        if kind == ID:
            return self.name(text)
        raise Unknown(f"'{text or 'end'}' is not understood")

    @staticmethod
    def number(text: str) -> Num:
        """Value of `12`, `1_000`, `1.5e3`, `16#FF#`, `2#1010#e2` or `x"0F"`."""
        lower = text.lower().replace("_", "")
        try:
            if lower.endswith('"'):
                # bit string
                prefix, _, digits = lower[:-1].partition('"')
                base = _VHDL_BASES[prefix[-1:] or "b"]
                bits = {2: 1, 8: 3, 16: 4}.get(base)
                width = int(prefix[:-1].rstrip("su")) if prefix[:-1].rstrip("su") else bits and bits * len(digits)
                return Num(int(digits, base), width)
            if "#" in lower:
                base_text, digits, exponent = lower.split("#")
                value = int(digits, int(base_text))
                if exponent:
                    value *= int(base_text) ** int(exponent.lstrip("e"))
                return Num(value)
            if "." in lower or "e-" in lower:
                return Num(float(lower))
            mantissa, _, exponent = lower.partition("e")
            return Num(int(mantissa) * 10 ** int(exponent or 0))
        except (ValueError, KeyError):
            raise Unknown(f"'{text}' is no number") from None

    def name(self, first: str) -> Thunk:
        """Parse `name`, `pkg.name`, a function call or a type conversion behind the first identifier."""
        path = [first.lower()]
        while self.peek().text == "." and self.peek(1).kind == ID:
            self.next()
            path.append(self.next().text.lower())
        name = ".".join(path)
        if self.peek().text == "'":
            raise Unknown(f"attribute of '{name}'")
        if self.peek().text != "(":
            if name in ("true", "false"):
                value = name == "true"
                return lambda: Num(value)
            names = self.names
            return lambda: names.value(tuple(path))
        function = path[-1]
        if function not in _VHDL_CONVERSIONS and function not in _VHDL_MATH and function not in _VHDL_FUNCTIONS:
            self.skip_group()
            return _SvParser.unknown(f"function '{name}' is not evaluated")
        args = self.arguments()
        if function in _VHDL_FUNCTIONS:
            return _VHDL_FUNCTIONS[function](args)
        (arg,) = args if len(args) == 1 else (None,)
        if arg is None:
            raise Unknown(f"function '{name}' with {len(args)} arguments")
        if function in _VHDL_MATH:
            func = _VHDL_MATH[function]
            return lambda: Num(_math(func, _vhdl_number(arg())))
        return arg


def _vhdl_number(num: Num) -> int | float:
    if isinstance(num.value, bool) or not isinstance(num.value, (int, float)):
        raise Unknown("operand is no number")
    return num.value


def _vhdl_integer(args: list[Thunk]) -> Thunk:
    """`integer(x)`: a real is rounded to the nearest integer."""
    if len(args) != 1:
        raise Unknown("one argument expected")
    return lambda: Num(_SvParser.round(_vhdl_number(args[0]())))


def _vhdl_extreme(func: Callable[[int | float, int | float], int | float]) -> Callable[[list[Thunk]], Thunk]:
    def create(args: list[Thunk]) -> Thunk:
        if len(args) != 2:  # noqa: PLR2004
            raise Unknown("two arguments expected")
        return lambda: Num(func(_vhdl_number(args[0]()), _vhdl_number(args[1]())))

    return create


def _vhdl_sized(args: list[Thunk]) -> Thunk:
    """`to_unsigned(value, size)`."""
    if len(args) != 2:  # noqa: PLR2004
        raise Unknown("two arguments expected")

    def evaluate() -> Num:
        width = _int(args[1]())
        if width <= 0:
            raise Unknown("size is not positive")
        return Num(_mask(_int(args[0]()), width), width)

    return evaluate


_VHDL_FUNCTIONS: dict[str, Callable[[list[Thunk]], Thunk]] = {
    "integer": _vhdl_integer,
    "maximum": _vhdl_extreme(max),
    "minimum": _vhdl_extreme(min),
    "to_unsigned": _vhdl_sized,
    "to_signed": _vhdl_sized,
    "conv_std_logic_vector": _vhdl_sized,
}


# --- interface ---


def evaluate(text: str, lang: str = "sv", names: Names | None = None) -> Num:
    """Value of the expression `text` in language `lang` (`sv` or `vhdl`). Raises `Unknown`, if it is not known."""
    if not text.strip():
        raise Unknown("no expression")
    names = names or DictNames()
    try:
        if lang == "vhdl":
            return _VhdlParser(tokenize_vhdl(text).tokens, names).parse()
        parser = _SvParser(tokenize_sv(text).tokens, names)
        parser.source = text
        return parser.parse()
    except RecursionError:
        raise Unknown("expression is nested too deep") from None


def split_dims(dims: str) -> list[str]:
    """Split the dimensions `[a][b:c]` into `["a", "b:c"]`."""
    parts = []
    depth = start = 0
    for idx, char in enumerate(dims):
        if char == "[":
            if not depth:
                start = idx + 1
            depth += 1
        elif char == "]":
            depth -= 1
            if not depth:
                parts.append(dims[start:idx])
        elif not depth and not char.isspace():
            depth = -1
            break
    if depth:
        raise Unknown(f"dimension '{dims}' is not understood")
    return parts


def _split_range(text: str) -> tuple[str, str] | None:
    """Split the range `left:right` at its colon. The colon of `a ? b : c` is none."""
    depth = questions = 0
    for idx, char in enumerate(text):
        if char in "([{":
            depth += 1
        elif char in ")]}":
            depth -= 1
        elif depth:
            continue
        elif char == "?":
            questions += 1
        elif char == ":" and text[idx : idx + 2] != "::" and text[idx - 1 : idx] != ":":
            if questions:
                questions -= 1
            else:
                return text[:idx], text[idx + 1 :]
    return None


def evaluate_dims(dims: str, lang: str = "sv", names: Names | None = None) -> int:
    """Number of elements of the dimensions `dims`: 8 for `[7:0]`, 32 for `[3:0][7:0]`, 4 for `[4]`.

    Raises `Unknown`, if it is not known.
    """
    count = 1
    for part in split_dims(dims):
        limits = _split_range(part)
        if limits is None:
            size = _int(evaluate(part, lang, names), "dimension")
        else:
            left, right = (_int(evaluate(limit, lang, names), "dimension") for limit in limits)
            size = abs(left - right) + 1
        if size <= 0:
            raise Unknown(f"dimension '[{part}]' has no elements")
        count *= size
    return count
