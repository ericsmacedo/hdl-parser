# hdl-parser review

Scope: what the package does, improvements and features worth adding, and how to handle macros that define ports in the module header.
Every behaviour listed below was reproduced against the current `main` (47 tests pass, 98% coverage).

## 1. What it does

`hdl-parser` is a pure-Python extractor of module interface information from SystemVerilog (and, undocumented, VHDL). It is not a full parser: it does no syntax checking and builds no AST.

| Layer | File | Role |
|---|---|---|
| Lexer | `src/hdl_parser/_sv/lexer.py` | A Pygments `ExtendedRegexLexer` used as a state machine (`root` → `module_name` → `module_header` → `port_declaration` / `param_declaration` → `module_body` → `instance_connections`). It emits custom tokens such as `Module.Port.PortName`. |
| Parser | `src/hdl_parser/_sv/parser.py` | Folds the token stream into mutable `_datamodel` objects, tracks the `ifdef` stack, then normalizes into the public model. |
| Data model | `src/hdl_parser/datamodel.py` | Frozen pydantic classes: `File`, `Module`, `Param`, `Port`, `ModuleInstance`, `Connection`. |
| API | `src/hdl_parser/parser.py` | `parse_file()` and `parse_text()`, language chosen by file suffix. |
| CLI | `src/hdl_parser/cli.py` | `info` (Markdown tables), `json`, `gen-sv-instance` (Jinja instantiation template). Accepts files and `-f` filelists. |

What it extracts: ports (direction, type, signedness, packed/unpacked dims, comments), parameters and localparams (type, dims, default), submodule instances with their connections, and the `ifdef` conditions guarding each item. Conditionals are recorded as annotations (`ifdefs=("FOO", "!BAR")`), not evaluated.

Speed, measured here on a synthetic 8,000-line file (10 modules, 200 ports and 300 instances each): about 0.5 s, roughly 15k lines/s.

## 2. Macros that define ports in the module header

### Current behaviour

Macro calls in the header are dropped silently, so the port list comes back incomplete with no warning:

```systemverilog
module m #(parameter int W = `DEF_W) (
  input  logic clk,
  `AXI_PORTS(s_axi, 32),        // dropped
  `STD_CLK_RST                  // dropped
  output logic [`WIDTH-1:0] q   // kept, dim = "[`WIDTH-1:0]"
);
```

The cause is that the `module_header` and `port_declaration` states have no rule for a backtick identifier, so the text falls through as Pygments `Error` tokens, which the parser ignores. Macros inside dimensions and parameter defaults survive as raw text. `` `define `` bodies are lexed as `Comment.Preproc` and discarded, so nothing is available to expand with.

### Recommendation: a small built-in macro expander, with a visible fallback

Do this in three steps. Each is useful on its own.

**Step 1: never drop silently (small change).**
Add a rule for `` `NAME `` and `` `NAME(...) `` in `module_header` and `port_declaration` that emits a new `Module.Port.Macro` token, and expose it in the model:

```python
class MacroCall(_BaseModel):
    name: str                    # "AXI_PORTS"
    args: tuple[str, ...] = ()   # ("s_axi", "32")
    ifdefs: tuple[str, ...] = ()

class Module(_BaseModel):
    ...
    header_macros: tuple[MacroCall, ...] = ()   # unresolved macro calls, in order
```

Users can then see that a header is incomplete, and `gen-sv-instance` can warn. Add `strict=True` to `parse_*` to raise instead.
The argument matcher must count parentheses. The existing `` `\w+\s*\(.*?\) `` pattern is non-greedy and stops at the first `)`, so `` `P(a, f(b)) `` breaks.

**Step 2: expand macros in pure Python before lexing.**
Add `hdl_parser/_sv/preproc.py`:

1. `collect_defines(text) -> dict[str, Macro]`: one regex pass over `` `define NAME(args) body `` handling `\` line continuations and default argument values.
2. `expand(text, macros) -> str`: one `re.sub` over `` `IDENT `` with a callback that substitutes arguments, handles ` `` ` token pasting and `` `" `` stringification, and re-expands nested macros with a depth limit. Compiler directives (`` `ifdef ``, `` `include ``, `` `timescale `` and so on) are left alone.
3. Macro sources, in priority order: `macros=` passed by the caller, `+define+` / `-D` from the CLI or filelist, `` `include `` files resolved through the incdirs, and defines in the same file.

API:

```python
defs = hdl_parser.parse_defines(["inc/company_macros.svh"])   # parse once, reuse
file = hdl_parser.parse_file("top.sv", macros=defs, inc_dirs=[...], expand_macros=True)
```

Design points that matter for you:

- **Speed stays.** The scan is a C-level regex pass; the Python callback only runs per macro use, which is sparse. To make it cheaper still, expand only between `module` and the header's closing `);`. Parse the shared company header once per run and reuse the table for every file.
- **Keep provenance.** Add `Port.macro: str = ""` holding the originating macro call. Document generators can group ports by macro, and `gen-sv-instance` can choose between expanded ports and re-emitting the macro.
- **Conditional definitions.** A macro defined differently under `` `ifdef `` branches is ambiguous while conditionals are only annotated. Pick the definition using the supplied defines when given; otherwise fall back to the step 1 placeholder and warn. Do not guess.
- **Unknown macros** fall back to the step 1 placeholder, so results are never silently wrong.

**Step 3: escape hatches.**

- `macro_resolver: Callable[[str, tuple[str, ...]], str | None]`, for macros whose definition is generated or unreachable. The callback returns SV text to parse in place.
- `--preprocessor CMD`, to pipe through an external preprocessor (for example `verilator -E`) when exactness matters more than speed. This is optional and keeps the default path pure Python.

I recommend steps 1 and 2. Step 1 alone removes the silent data loss; step 2 covers the common company pattern (a shared `.svh` of port-bundle macros) without giving up the pure-Python, fast property.

## 3. Bugs found

| # | Input | Result | Cause |
|---|---|---|---|
| 1 | `.e(f(x))` in an instance | `con = "f(x"` | Non-greedy `(.*?)` in the connection rule; needs paren counting as in `param_value_delimiter`. |
| 2 | `sub u_sub [3:0] (...)` | Instance missed | Instance regex has no optional array range. |
| 3 | Instance inside `for ... begin : g ... end` | Instance missed | The `begin` state only matches `end`; everything inside is discarded. All generate-block instances are lost. |
| 4 | `task t(input logic a, output logic b)` in the body | `a`, `b` reported as module ports | `module_body` treats any `input`/`output` as a port. Needs `task`/`function` states. |
| 5 | `axi_if.slave s_axi` | Port missed | Interface ports are not recognised. |
| 6 | `input my_pkg::req_t req_i` | Port named `my_pkg` | User-defined and package-scoped types are not recognised. |
| 7 | `input req_t [3:0] reqs` or `input T d` | Two ports (`req_t` and `reqs`; `T` and `d`) | Same cause as 6: the type name is taken as a port name. |
| 8 | `parameter int unsigned A` | `ptype = "unsigned"` | Each type keyword overwrites the previous one. |
| 9 | `output logic q [2] [3]` | `dim_unpacked = "[2]"` | Only the first group is kept when dims are separated by whitespace. |
| 10 | File with only a package or interface | `RuntimeError: No module found`, CLI prints `Failed.` | One such file in a filelist aborts the whole run. Return an empty `File` instead. |
| 11 | `.svh`, `.vh` or any unknown suffix | `KeyError`, CLI prints `Failed.` | `LANGMAP[file_path.suffix]`; use `.get(..., "sv")` as the docstring promises. |
| 12 | Any filelist | Parsed twice | `parse_filelist()` calls `_parse()` two times (`filelistparser.py:53-59`); nested `-f` files are re-read exponentially with depth. |

## 4. Improvements

**Correctness**

- Fix the table above. Bugs 3, 4, 6 and 7 are the most likely to bite on real company code.
- Recognise user-defined types by position: in a port declaration, the last identifier before `,` / `)` / `[unpacked]` / `=` is the name and everything before it is the type.
- Log a warning with file and line whenever the lexer emits `Error` tokens inside a header. Today all unrecognised text disappears silently.

**Performance**

- Remove the per-token debug work in `SystemVerilogLexer.get_tokens_unprocessed`: it copies the state stack, slices the token and builds an f-string for every token even when debug logging is off. Replacing it with a lean loop gave an identical result 13% faster (0.512 s → 0.443 s on the file above).
- Add a `header_only=True` option that stops lexing at the end of the module header and skips to `endmodule`. When only ports and parameters are needed this skips most of each file and should be the largest single gain.
- Parse filelists in parallel (`concurrent.futures.ProcessPoolExecutor`); files are independent.
- Optional on-disk cache keyed by path, mtime and defines.

**Code health**

- `filelistparser`: `inc_dirs` are collected but never used, and `+define+`, `-y`, `-v`, `+libext+` and `$ENV` expansion are unsupported.
- `read_text()` has no encoding; legacy RTL with Latin-1 comments will raise. Use `encoding="utf-8", errors="replace"`.
- Remove the commented-out states at the end of the lexer and the unused duplicate `port_types_tup`.
- `Port.direction`, `ptype` and `dtype` carry a FIXME about allowed values; settle it, since it is public API.
- VHDL support exists in `_vhdl/` but the README does not mention it. Either document it as experimental or state that it is unsupported.
- The CLI env var is named `UCDP_NO_COLOR`, left over from another project.

## 5. Feature suggestions

Ordered by value for an RTL team.

1. **Macro expansion in headers** (section 2).
2. **Interfaces and packages**: parse `interface` (ports, modports) and `package` (parameters, typedefs) as first-class items. This also makes interface ports resolvable.
3. **Hierarchy**: resolve instances across a filelist into a tree, with `hdl-parser tree -f files.f --top top`, plus detection of unresolved modules.
4. **Evaluated conditionals**: `parse_file(..., defines={"FPGA"})` returns only the active branch, next to today's annotate-only mode.
5. **Parameter overrides on instances**: capture `#(.W(8))`; it is currently matched and thrown away.
6. **Source locations**: line and column on every `Module`, `Port`, `Param` and instance, for editor and lint integrations.
7. **Non-ANSI header ordering**: keep the header port order for `module m (a, b, c);` style.
8. **More generators**: testbench skeleton, wrapper module, cocotb stub, SV interface from a port group, and user-supplied Jinja templates (`--template`).
9. **Attributes**: capture `(* ... *)` on ports and modules.
10. **Simple expression evaluation**: resolve widths such as `[W-1:0]` given parameter values, for documentation and connection width checks.
