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

from pygments.lexer import ExtendedRegexLexer, LexerContext, bygroups, include, words
from pygments.token import Keyword, Name, Number, Operator, Punctuation, String, Whitespace

from .token import Architecture, Component, Entity, Gen, Node, Port

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


class VhdlLexer(ExtendedRegexLexer):
    """For VHDL source code."""

    name = "vhdl"
    aliases = ["vhdl"]
    filenames = ["*.vhdl", "*.vhd"]
    mimetypes = ["text/x-vhdl"]
    url = "https://en.wikipedia.org/wiki/VHDL"
    flags = re.MULTILINE | re.DOTALL | re.IGNORECASE

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
            (r"(entity)\s+(\w+)\s+(is)\s+", bygroups(Keyword, Entity.Name, Keyword), "entity_header"),
            (r"(component)\s+(\w+)\s+(is)\s+", bygroups(Keyword, Component.Name, Keyword), "component_header"),
            (
                r"architecture\s+(\w+)\s*of\s*(\w+)\s*is\s*",
                bygroups(Architecture.Name, Architecture.Entity),
                "architecture",
            ),
            (r"(entity|component)(\s+)([a-z_]\w*)", bygroups(Keyword, Whitespace, Name.Class)),
            (
                r"(architecture|configuration)(\s+)([a-z_]\w*)(\s+)"
                r"(of)(\s+)([a-z_]\w*)(\s+)(is)",
                bygroups(
                    Keyword, Whitespace, Name.Class, Whitespace, Keyword, Whitespace, Name.Class, Whitespace, Keyword
                ),
            ),
            (r"([a-z_]\w*)(:)(\s+)(process|for)", bygroups(Name.Class, Operator, Whitespace, Keyword)),
            # (r"(end)(\s+)", bygroups(using(this), Whitespace), "endblock"),
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
        "architecture": [
            (r"\bend\s+\w+\s*;", Architecture.End, "#pop"),
            (r"\b(begin|then)\b", Keyword, "begin"),
            include("root"),
        ],
        "begin": [
            (r"\b(begin|then)\b", Keyword, "#push"),
            (r"\bend\b", Keyword, "#pop"),
            include("root"),
        ],
        "entity_header": [
            (r"\s+", Whitespace),
            include("comment"),
            (r"\bport\b", Keyword, "port_clause"),
            (r"\bgeneric\b", Keyword, "generic_clause"),
            (r"(end)\s+(\w+)\s*;", bygroups(Keyword, Entity.HeaderEnd), "#pop"),
            include("root"),
        ],
        "component_header": [
            (r"\s+", Whitespace),
            include("comment"),
            (r"\bport\b", Keyword, "port_clause"),
            (r"\bgeneric\b", Keyword, "generic_clause"),
            (r"(end)\s+(\w+)\s*;", bygroups(Keyword, Component.HeaderEnd), "#pop"),
            include("root"),
        ],
        "port_clause": [
            (r"\s+", Whitespace),
            include("comment"),
            (words(itf_obj_type, suffix=r"\b"), Port.PType),
            (r"([a-zA-Z_]\w*)", Port.NewPortDecl, "obj_declaration"),
            (r"[(:,]", Punctuation),
            (r"\)\s*;", Port.ClauseEnd, "#pop"),
        ],
        "generic_clause": [
            (r"\s+", Whitespace),
            include("comment"),
            (words(itf_obj_type, suffix=r"\b"), Gen.PType),
            (r"([a-zA-Z_]\w*)", Gen.NewGenDecl, "obj_declaration"),
            (r"[(:,]", Punctuation),
            (r"\)\s*;", Gen.ClauseEnd, "#pop"),
        ],
        "obj_declaration": [
            # This states cover only port names. It will jump to port type once a ":"
            # is found
            (r"\s+", Whitespace),
            include("comment"),
            (r"([a-zA-Z_]\w*)", Node.Name),
            (r"\s*:\s*", Punctuation, "obj_type"),
            (r"[,]", Punctuation),
        ],
        "obj_type": [
            (r"\s+", Whitespace),
            include("comment"),
            # port modes (vhdl std page 97)
            (words(mode, prefix=r"\b", suffix=r"\b"), Node.Mode),
            (r"(\w+)(\()", bygroups(Node.DType, Node.WidthStart), "obj_width"),
            (words(types, prefix=r"\b", suffix=r"\b"), Node.DType),
            (r":=", Node.ValueStart, "obj_value"),
            (r";", Node.End, "#pop:2"),
            (r"[(:,]", Punctuation),
            # end of port declaration AND end of port clause
            (r"\)\s*;", Node.ClauseEnd, "#pop:3"),
        ],
        "obj_width": [
            include("comment"),
            (r"[{\[(]", Port.Width, "value_delimiter"),
            (r"\w+", Port.Width),
            (r'"(?:\\.|[^"\\])*"', Port.Width),
            # end of port clause
            (r"[,);]", Port.WidthEnd, "#pop"),
            (r".", Port.Width),
        ],
        "obj_value": [
            include("comment"),
            (r"[{\[(]", Node.Value, "value_delimiter"),
            (r"\w+", Node.Value),
            (r'"(?:\\.|[^"\\])*"', Node.Value),
            # end of generic_value, gen_declaration and genneric clause
            (r"\)\s*;", Node.ClauseEnd, "#pop:4"),
            (r"[;]", Punctuation, "#pop:3"),
            (r".", Node.Value),
        ],
        "value_delimiter": [
            include("comment"),
            (r"[{\[(]", Node.Value, "#push"),
            (r"[}\])]", Node.Value, "#pop"),
            (r"\w+", Node.Value),
            (r'"(?:\\.|[^"\\])*"', Node.Value),
            (r"[,);]", Punctuation, "#pop"),
            (r".", Node.Value),
        ],
        "comment": [
            (r"(--)(.*?)$", Node.Comment),
            (r"/(\\\n)?[*]((.|\n)*?)[*](\\\n)?/", Node.Comment),
        ],
    }

    def get_tokens_unprocessed(self, text=None, context=None):
        # Override get_tokens_unprocessed to add debug logic
        # In debug mode, print (Token, match, state_stack)
        self.ctx = context or LexerContext(text, 0)
        stack = self.ctx.stack.copy()
        for pos, token, string in ExtendedRegexLexer.get_tokens_unprocessed(self, text, self.ctx):
            # This will replace the token "Node" by either Port or Gen, based on
            # the states present in the state stack. This logic enable us to reuse
            # states for both Ports and Generic declarations
            mod_token = token
            if "Node" in token[:]:
                if "port_clause" in stack:
                    mod_token = (*Port, token[1])
                elif "generic_clause" in stack:
                    mod_token = (*Gen, token[1])

            if stack == self.ctx.stack:
                LOGGER.debug(f'({token}, "{string}")')
            else:
                LOGGER.debug(f'state stack: {self.ctx.stack}\n({token}, "{string}")')
                stack = self.ctx.stack.copy()

            yield (pos, mod_token, string)
