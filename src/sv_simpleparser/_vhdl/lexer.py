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

import logging
import re

from pygments.lexer import ExtendedRegexLexer, LexerContext, bygroups, include, this, using, words
from pygments.token import Comment, Keyword, Name, Number, Operator, Punctuation, String, Whitespace

from .token import Entity, Gen, Port

LOGGER = logging.getLogger(__name__)

# fmt: off
keywords = (
    "abs", "access", "after", "alias", "all", "and",
    "architecture", "array", "assert", "attribute", "begin", "block",
    "body", "buffer", "bus", "case", "component", "configuration",
    "constant", "disconnect", "downto", "else", "elsif", "end",
    "entity", "exit", "file", "for", "function", "generate",
    "generic", "group", "guarded", "if", "impure", "in",
    "inertial", "inout", "is", "label", "library", "linkage",
    "literal", "loop", "map", "mod", "nand", "new",
    "next", "nor", "not", "null", "of", "on",
    "open", "or", "others", "out", "package", "port",
    "postponed", "procedure", "process", "pure", "range", "record",
    "register", "reject", "rem", "return", "rol", "ror", "select",
    "severity", "signal", "shared", "sla", "sll", "sra",
    "srl", "subtype", "then", "to", "transport", "type",
    "units", "until", "use", "variable", "wait", "when",
    "while", "with", "xnor", "xor"
)

types = (
    "boolean", "bit", "character", "severity_level", "integer", "time",
    "delay_length", "natural", "positive", "string", "bit_vector",
    "file_open_kind", "file_open_status", "std_ulogic", "std_ulogic_vector",
    "std_logic", "std_logic_vector", "signed", "unsigned"
)

mode = (
    "in", "out", "inout", "buffer", "linkage",
)

itf_obj_type = (
        "constant", "signal", "variable", "file",
)
# fmt: on


def comments_callback(lexer: ExtendedRegexLexer, match, ctx: LexerContext):  # noqa: ARG001
    state_stack = ctx.stack

    # The actual comment is located at group 2
    match_string = match.group(2)
    match_start = match.start(0)

    if "port_clause" in state_stack:
        yield match_start, Port.Comment, match_string
    elif "generic_clause" in state_stack:
        yield match_start, Gen.Comment, match_string
    else:
        yield match_start, Comment, match_string
    ctx.pos = match.end()


def value_callback(lexer: ExtendedRegexLexer, match, ctx: LexerContext):  # noqa: ARG001
    prev_state = ctx.stack[-2]

    if prev_state == "generic_value":
        yield match, Gen.Value, match.group(0)
    else:
        yield match, Gen.Value, match.group(0)
    ctx.pos = match.end()


class VhdlLexer(ExtendedRegexLexer):
    """For VHDL source code."""

    # name = 'vhdl'
    # aliases = ['vhdl']
    # filenames = ['*.vhdl', '*.vhd']
    # mimetypes = ['text/x-vhdl']
    # url = 'https://en.wikipedia.org/wiki/VHDL'
    # version_added = '1.5'
    flags = re.MULTILINE | re.DOTALL

    tokens = {
        "root": [
            (r"\s+", Whitespace),
            (r"(\\)(\n)", bygroups(String.Escape, Whitespace)),  # line continuation
            include("comment"),
            (r"'(U|X|0|1|Z|W|L|H|-)'", String.Char),
            (r"[~!%^&*+=|?:<>/-]", Operator),
            (r"'[a-z_]\w*", Name.Attribute),
            (r"[()\[\],.;\']", Punctuation),
            (r'"[^\n\\"]*"', String),
            (r"(library)(\s+)([a-z_]\w*)", bygroups(Keyword, Whitespace, Name.Namespace)),
            (r"(use)(\s+)(entity)", bygroups(Keyword, Whitespace, Keyword)),
            (r"(use)(\s+)([a-z_][\w.]*\.)(all)", bygroups(Keyword, Whitespace, Name.Namespace, Keyword)),
            (r"(use)(\s+)([a-z_][\w.]*)", bygroups(Keyword, Whitespace, Name.Namespace)),
            (r"(std|ieee)(\.[a-z_]\w*)", bygroups(Name.Namespace, Name.Namespace)),
            (words(("std", "ieee", "work"), suffix=r"\b"), Name.Namespace),
            # detect entity name
            (r"(entity)\s+([a-zA-Z_]\w+)\s+(is)\s+", bygroups(Keyword, Entity.Name, Keyword), "entity_header"),
            (r"(entity|component)(\s+)([a-z_]\w*)", bygroups(Keyword, Whitespace, Name.Class)),
            (
                r"(architecture|configuration)(\s+)([a-z_]\w*)(\s+)"
                r"(of)(\s+)([a-z_]\w*)(\s+)(is)",
                bygroups(
                    Keyword, Whitespace, Name.Class, Whitespace, Keyword, Whitespace, Name.Class, Whitespace, Keyword
                ),
            ),
            (r"([a-z_]\w*)(:)(\s+)(process|for)", bygroups(Name.Class, Operator, Whitespace, Keyword)),
            (r"(end)(\s+)", bygroups(using(this), Whitespace), "endblock"),
            include("types"),
            include("keywords"),
            include("numbers"),
            (r"[a-z_]\w*", Name),
        ],
        "endblock": [
            include("keywords"),
            (r"[a-z_]\w*", Name.Class),
            (r"\s+", Whitespace),
            (r";", Punctuation, "#pop"),
        ],
        "types": [
            (words(types, suffix=r"\b"), Keyword.Type),
        ],
        "keywords": [
            (words(keywords, suffix=r"\b"), Keyword),
        ],
        "numbers": [
            (r"\d{1,2}#[0-9a-f_]+#?", Number.Integer),
            (r"\d+", Number.Integer),
            (r"(\d+\.\d*|\.\d+|\d+)E[+-]?\d+", Number.Float),
            (r'X"[0-9a-f_]+"', Number.Hex),
            (r'O"[0-7_]+"', Number.Oct),
            (r'B"[01_]+"', Number.Bin),
        ],
        "entity_header": [
            (r"\s+", Whitespace),
            include("comment"),
            (r"\bport\b", Keyword, "port_clause"),
            (r"\bgeneric\b", Keyword, "generic_clause"),
            (r"(end)\s+([a-zA-Z_]\w+)\s*;", bygroups(Keyword, Entity.HeaderEnd), "#pop"),
            include("root"),
        ],
        "port_clause": [
            (r"\s+", Whitespace),
            include("comment"),
            # port modes (vhdl std page 97)
            (r"([a-zA-Z_]\w*)", Port.NewPortDecl, "port_declaration"),
            (r";", Port.End),
            (r"[(:,]", Punctuation),
            (r"\)\s*;", Port.ClauseEnd, "#pop"),
        ],
        "port_declaration": [
            (r"\s+", Whitespace),
            include("comment"),
            # port modes (vhdl std page 97)
            (words(mode, prefix=r"\b", suffix=r"\b"), Port.Mode),
            (r"\b(std_logic_vector)(\()", bygroups(Port.Type, Punctuation), "port_width"),
            (words(types, prefix=r"\b", suffix=r"\b"), Port.Type),
            (r"([a-zA-Z_]\w*)", Port.Name),
            (r";", Port.End, "#pop"),
            (r"[(:,]", Punctuation),
            # end of port declaration AND end of port clause
            (r"\)\s*;", Port.ClauseEnd, "#pop:2"),
        ],
        "port_width": [
            include("comment"),
            (r"[{\[(]", Port.Width, "value_delimiter"),
            (r'"(?:\\.|[^"\\])*"', Port.Width),
            # end of generic clause
            (r"[,);]", Punctuation, "#pop"),
            (r".", Port.Width),
        ],
        "generic_clause": [
            (r"\s+", Whitespace),
            include("comment"),
            (r"([a-zA-Z_]\w*)", Gen.NewGenDecl, "gen_declaration"),
            (r"\)\s*;", Gen.ClauseEnd, "#pop"),
            # TODO: check if it can be removed
            (r"\(", Punctuation),
        ],
        "gen_declaration": [
            (r"\s+", Whitespace),
            include("comment"),
            (words(types, prefix=r"\b", suffix=r"\b"), Gen.Type),
            # (vhdl std page 96)
            (words(itf_obj_type, prefix=r"\b", suffix=r"\b"), Gen.Other),
            (r"([a-zA-Z_]\w*)", Gen.Name),
            (r":=", Gen.ValueStart, "generic_value"),
            (r"\)\s*;", Gen.ClauseEnd, "#pop:2"),
            (r";", Gen.End, "#pop"),
            (r"[(:,]", Punctuation),
        ],
        "generic_value": [
            include("comment"),
            (r"[{\[(]", Gen.Value, "value_delimiter"),
            (r'"(?:\\.|[^"\\])*"', Gen.Value),
            # end of generic_value, gen_declaration and genneric clause
            (r"\)\s*;", Gen.ClauseEnd, "#pop:3"),
            # end of generic clause
            (r"[,);]", Punctuation, "#pop:2"),
            (r".", Gen.Value),
        ],
        "value_delimiter": [
            include("comment"),
            (r"[{\[(]", value_callback, "#push"),
            (r"[}\])]", value_callback, "#pop"),
            (r'"(?:\\.|[^"\\])*"', value_callback),
            (r"[,);]", Punctuation, "#pop"),
            (r".", value_callback),
        ],
        "comment": [
            (r"(--)(.*?)$", comments_callback),
            (r"/(\\\n)?[*]((.|\n)*?)[*](\\\n)?/", comments_callback),
        ],
    }

    def get_tokens_unprocessed(self, text=None, context=None):
        # Override get_tokens_unprocessed to add debug logic
        # In debug mode, print (Token, match, state_stack)
        self.ctx = context or LexerContext(text, 0)
        stack = self.ctx.stack.copy()
        for item in ExtendedRegexLexer.get_tokens_unprocessed(self, text, self.ctx):
            if stack == self.ctx.stack:
                LOGGER.debug(f'({item[1]}, "{item[2]}")')
            else:
                LOGGER.debug(f'({item[1]}, "{item[2]}"),\n state stack: {self.ctx.stack}')
                stack = self.ctx.stack.copy()
            yield item
