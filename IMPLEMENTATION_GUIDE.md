# Implementation guide for the hdl-parser backlog

This guide turns the findings in `REVIEW.md` into work packages that an AI coding agent can pick up one at a time.
Each package is self-contained: the problem, a reproduction, the design to follow, the pitfalls, the tests to add and what "done" means.

If you are an agent assigned one package: read sections 1 to 3 first, then only your package.

## 1. How to use this guide

- One package per branch and per pull request. Do not combine packages unless the package says so.
- Follow the design given in the package. Where a package says "owner decision", the default is already chosen; implement the default and mention it in the PR description.
- Start by writing the failing test from the package's reproduction. Confirm it fails for the stated reason before changing code.
- Stay inside the package's scope. If you find another bug, write it in the PR description; do not fix it.
- If the design in the package turns out not to work, stop and report what you found instead of inventing a different design.

## 2. Project orientation

`hdl-parser` extracts module interfaces from SystemVerilog. It is not a full parser, and it must stay pure Python and fast.

Pipeline for SystemVerilog:

1. `src/hdl_parser/_sv/preproc.py`: `expand()` expands known macros inside module headers. Helpers you can reuse: `find_closing(text, pos)` (position after the `)` matching the `(` at `pos`, string-aware), `split_args(text)` (split at top-level commas) and `_iter_toplevel(text, pos)` (yields `(pos, char, level)` outside strings, counting `()`, `[]` and `{}`).
2. `src/hdl_parser/_sv/lexer.py`: `SystemVerilogLexer`, a Pygments `ExtendedRegexLexer` used as a state machine. States: `root` → `module_name` → `module_header` → `port_declaration` / `param_declaration` / `param_value` → `module_body` → `instance_connections`. It emits custom tokens defined in `_sv/token.py`.
3. `src/hdl_parser/_sv/parser.py`: `parse()` walks the tokens, fills mutable objects from `src/hdl_parser/_datamodel.py` through the `_proc_*_tokens` functions, then converts them to the frozen public model in `src/hdl_parser/datamodel.py` through the `_normalize_*` functions.
4. `src/hdl_parser/parser.py`: public API (`parse_file`, `parse_text`, `parse_defines`). `src/hdl_parser/cli.py`: the `info`, `json` and `gen-sv-instance` commands.

Things to know about the lexer before touching it:

- Rules are tried in order and the first match wins. Moving a rule changes behaviour.
- Text that no rule matches becomes an `Error` token, one character at a time, and the parser ignores it. This is how input gets dropped silently.
- `default("#pop")` leaves a state when nothing matches. A tuple of states such as `("#pop", "a", "b")` is applied left to right.
- A callback rule receives `(lexer, match, ctx)`. It yields `(pos, token, text)` and must set `ctx.pos`; it may push to `ctx.stack`. See `filter_instance_keywords_callback` and `header_macro_callback` for working examples.
- `get_tokens_unprocessed` is overridden to retag comment tokens depending on the current state.
- To watch the lexer work: `uv run hdl-parser -vv json file.sv` prints every token and state change.

Things to know about the data model:

- The public classes are frozen and use `extra="forbid"`. A new field needs a default.
- `overview` (used by the `json` command and the reference data) omits fields that still have their default value. A new field with a default does not change existing reference data unless it is populated.

## 3. Rules for every package

### Commands

```bash
uv sync                                  # once
uv run pytest -q                         # tests, doctests in docs/, coverage
uv run ruff format src tests
uv run ruff check src tests
uv run mypy src
uv run mkdocs build --strict             # only if you touched docs/ or docstrings
```

All five must pass before you commit.

### Reference data

`tests/test_parser.py::test_examples` parses every `examples/sv/*.sv` and `examples/vhdl/*.vhd` file and compares the JSON with `tests/refdata/`. Any `.sv` file you add to `examples/sv/` is tested automatically.

To create or update reference data:

```bash
touch .test2ref && uv run pytest -q; rm .test2ref
git diff tests/refdata
```

Read the diff. Every change to an existing reference file must be a direct, intended consequence of your package, and you must list it in the PR description. An unexplained change is a regression.

### Safety net

Three checks protect against regressions. They exist because line coverage alone did not catch any of the bugs in `REVIEW.md`.

- **Corpus tests** (`tests/test_corpus.py`): 54 real open-source files under `tests/corpus/` are snapshot-compared and checked against the structural invariants in `tests/invariants.py`. Never edit or reformat a corpus file.
- **Known issues** (`KNOWN_ISSUES_SNAPSHOT` and `KNOWN_ISSUES_INVARIANTS` in `tests/test_corpus.py`): strict xfails for bugs that are not fixed yet. When your package fixes one, the test fails as XPASS: remove the entry, regenerate the reference data for that file and review it. Never add an entry to make your change pass; a new failure is a regression in your change.
- **Benchmark** (`tests/test_benchmark.py`): fails when parsing gets more than 50% slower than the recorded baseline. Do not re-record the baseline to make a slowdown pass. Re-record only when a package intentionally changes speed, and say so in the PR.

Corpus reference data changes follow the same rule as example reference data: every changed line must be an intended consequence of the package. For the corpus, open the source file and confirm that each added or removed port, parameter or instance is right.

For any package that touches `_sv/lexer.py` or `_sv/parser.py`, also run the comparison tool on the corpus and paste its summary into the PR description:

```bash
uv run python tools/compare_refs.py --base main --quiet tests/corpus examples/sv
```

The repository owner runs the same tool on a private code base before merging; see `CONTRIBUTING.md`.

### Traps

- Do not run `make pre-commit` or `pre-commit run --all-files` and commit the result blindly. The `insert-license` hook rewrites the copyright year in every file. Revert year-only changes in files you did not otherwise touch (`git checkout <file>`).
- New `.py` files need the MIT header. Copy the first 21 lines of `src/hdl_parser/_sv/preproc.py`.
- Ruff enforces complexity limits (10 for `C901`, 12 branches for `PLR0912`) and a 120-character line. When a `_proc_*` function grows, extract a helper; do not add `noqa`.
- Docstrings follow the Google convention and are required on public functions.
- `pyproject.toml` sets `filterwarnings = ["error"]`: a Python warning fails the test run.
- Do not add runtime dependencies.
- Do not push to `main`. Do not rewrite refdata with `make test2ref` (it deletes all reference data first).

### Definition of done

1. A test reproduces the problem and now passes.
2. Corpus tests pass, fixed entries are removed from the known-issue lists, and no entry was added.
3. All commands in "Commands" pass, with coverage of the files you touched not lower than before.
4. Reference data changes are reviewed and explained.
5. `docs/usage.md` or the relevant docstring is updated when behaviour visible to users changed.
6. The matching row in `REVIEW.md` is not edited; note the fix in the PR description instead.

## 4. Order of work and model assignment

"Small" packages are mechanical and suit Sonnet 5.5. "Large" packages change lexer state logic and suit Opus 5.5.

| ID | Package | Size | Depends on | Touches `lexer.py` |
|---|---|---|---|---|
| A0 | Safety net: corpus, invariants, comparison tool, benchmark | Done | | no |
| A1 | Filelist is parsed twice | Small | | no |
| A2 | Unknown file suffix raises `KeyError` | Small | | no |
| A3 | File without a module aborts the run | Small | | no |
| A4 | File encoding | Small | | no |
| A5 | Remove per-token debug overhead | Small | | yes |
| A6 | Dead code and leftovers | Small | A5 | yes |
| B1 | Nested parentheses in connections | Small | | yes |
| B2 | Instance arrays | Small | B1 | yes |
| B3 | Procedural blocks, generate blocks, tasks, functions | Large | B2 | yes |
| B4 | Parameter overrides on instances | Small | B2 | yes |
| C1 | Robust dimensions | Small | | yes |
| C2 | User-defined types and interface ports | Large | C1 | yes |
| C3 | Parameter type keywords | Small | C2 | yes |
| C4 | Warn about dropped header text | Small | C2 | yes |
| D1 | Filelist options | Small | A1 | no |
| E1 | `` `include `` resolution | Large | D1 | no |
| E2 | Evaluated conditionals | Large | D1 | no |
| E3 | Macro expansion in the module body | Small | | no |
| F1 | Header-only mode | Large | C2 | yes |
| F2 | Parallel parsing | Small | A3 | no |
| F3 | Hierarchy tree | Small | B3, A3 | no |
| F4 | Interfaces and packages | Large | B3, C2 | yes |
| F5 | Source locations | Large | all lexer packages | yes |
| F6 | Port provenance from macros | Large | F5 | no |
| F7 | Smaller features | Small | see package | varies |

Packages that touch `lexer.py` conflict with each other. Run them one after another in the order of the table, each starting from the merged result of the previous one. Packages that do not touch `lexer.py` can run in parallel with anything.

A0 is already implemented and must be merged before any Large package starts.

Packages that clear known-issue entries: A3 clears the package-only file (`ibex/ibex_pkg.sv`), C2 clears all user-defined-type and package-scoped-type entries. B3 has no entries to clear, because lost instances are invisible to the invariants; expect corpus reference data to gain instances instead.

Suggested first wave, all parallel: A1, A2, A3, A4, D1 (after A1), E3, and the lexer chain starting with A5.

## 5. Group A: quick fixes

### A1. Filelist is parsed twice

- **Problem:** `parse_filelist()` in `src/hdl_parser/filelistparser.py` opens the file and calls `_parse()` two times. The work is doubled at every `-f` nesting level, and each unparsable line warns twice (once with an empty context).
- **Fix:** delete the first `with` block. Keep the one that passes `context=str(filepath)`.
- **Test:** in `tests/test_filelistparser.py`, write a filelist containing one line that cannot be parsed (use `+unknown+option`) and assert with `caplog` that exactly one warning is logged and that it contains the filelist path.

### A2. Unknown file suffix raises `KeyError`

- **Problem:** `parse_text()` in `src/hdl_parser/parser.py` does `LANGMAP[file_path.suffix]`. A `.svh`, `.vh` or `.SV` file raises `KeyError`, and the CLI prints only `Failed.`.
- **Fix:** `LANGMAP.get(file_path.suffix.lower(), "sv")`, as the docstring already promises. Add `.svh` and `.vh` to `LANGMAP`.
- **Test:** `parse_text(text, file_path="x.svh")`, `"x.SV"` and `"x.unknown"` all return the module.

### A3. File without a module aborts the run

- **Problem:** `parse_text()` raises `RuntimeError("No module found.")`. A package-only or interface-only file in a filelist aborts the whole CLI run.
- **Owner decision, default chosen:** return `File(path=..., modules=())` and log at `INFO` level instead of raising.
- **Fix:** remove the `raise`. In `cli.py` nothing else is needed: the loops over `file.modules` print nothing for an empty file.
- **Corpus:** remove both `ibex/ibex_pkg.sv` entries from the known-issue lists and generate its reference data.
- **Tests:** `tests/test_cli.py::test_empty` currently asserts `exit_code == 1`; change it to `0` with empty output. Add a parser test for a package-only text.
- **Mention in the PR:** this is a public API behaviour change.

### A4. File encoding

- **Problem:** `parse_file()` and `parse_defines()` call `read_text()` with the platform default encoding. Old RTL with Latin-1 characters in comments raises `UnicodeDecodeError`.
- **Fix:** `read_text(encoding="utf-8", errors="replace")` in both. Apply the same to `filepath.open(...)` in `filelistparser.py` (it already passes `encoding`; add `errors="replace"`).
- **Test:** write a file with `b"// \xe9\nmodule m (input a);\nendmodule\n"` and parse it.

### A5. Remove per-token debug overhead

- **Problem:** `SystemVerilogLexer.get_tokens_unprocessed` copies the state stack, slices the token and builds an f-string for every token, even when debug logging is off. Measured cost: 13% or more of parse time.
- **Fix:** decide once, before the loop, whether debug logging is enabled. Use the existing loop only in that case; otherwise use this lean loop, which was verified to give identical results:

```python
debug = LOGGER.isEnabledFor(logging.DEBUG)
ctx = self.ctx = context or LexerContext(text, 0)
if not debug:
    for pos, token, string in ExtendedRegexLexer.get_tokens_unprocessed(self, text, ctx):
        if token[0] == "Node":
            stack = ctx.stack
            if "port_declaration" in stack:
                token = (*Port, token[1])
            elif "param_declaration" in stack:
                token = (*Param, token[1])
            elif "instance_connections" in stack:
                token = (*Instance.Con, token[1])
        yield pos, token, string
    return
```

- **Pitfall:** `(*Port, token[1])` produces a plain tuple, not a Pygments token; the parser relies on tuple comparison, so keep it exactly as today.
- **Test:** no reference data may change. Add one test that parses an example with `caplog.at_level(logging.DEBUG)` and asserts the result equals the non-debug result, so both branches stay covered.

### A6. Dead code and leftovers

- Delete the commented-out `find_connection` and `comments` states at the end of `tokens` in `_sv/lexer.py`.
- `port_types_tup` duplicates `variable_types_tup`; keep one tuple and derive the other name from it.
- `cli.py`: the `--no-color` option reads `UCDP_NO_COLOR`. Change to `envvar=["HDL_PARSER_NO_COLOR", "UCDP_NO_COLOR"]` so the old name keeps working.
- No behaviour change, no reference data change.

## 6. Group B: instances and the module body

### B1. Nested parentheses in connections

- **Reproduction:** `sub u (.e(f(x)), .b(y));` gives `con == "f(x"` for port `e`.
- **Cause:** in state `instance_connections`, the rule `(\.)([a-zA-Z_]\w*)\s*\(\s*(.*?)\s*\)\s*,?` stops at the first `)`.
- **Design:** replace that rule with a callback rule on `(\.)([a-zA-Z_]\w*)\s*(?=\()`. In the callback, call `find_closing(ctx.text, pos_of_paren)`, yield `Instance.Con.Start`, `Instance.Con.Port` and `Instance.Con.Connection` (inner text, stripped), then advance `ctx.pos` past an optional `\s*,`. If `find_closing` returns `None`, yield the match as `Error` and advance past it.
- **Pitfalls:** keep the rule position (before the `.port,` rule). An empty connection `.a()` must give `con == ""`. A comment inside the parentheses stays part of the connection text, as today.
- **Tests:** `.a(f(x))`, `.a({b, c[3:0]})`, `.a(g(h(1), 2))`, `.a()`, `.a ( b )`, and a string argument containing `)`.

### B2. Instance arrays

- **Reproduction:** `sub u_sub [3:0] (.clk(clk));` yields no instance.
- **Design:** in the instance rule in `module_body`, `(\w+)\s*(?:#\(.*?\))?\s+(\w+)\s*\((.*?)\)\s*;`, allow `((?:\s*\[[^\]]*\])*)` between the instance name and the `(`. In `filter_instance_keywords_callback`, set `ctx.pos` after the range and yield it as a new token `Instance.Dim`. Add `dim: str = ""` to `ModuleInstance` (and `InstDecl`) and fill it.
- **While you are there:** require the module name to start with a letter or underscore and not to be preceded by a backtick, digit or `.`: `(?<![`\w.$])([a-zA-Z_]\w*)`. This removes false instances such as `` `MACRO foo (x); `` and `#10 foo (x);`.
- **Tests:** array instance, array instance with parameters, the two false positives above.

### B3. Procedural blocks, generate blocks, tasks and functions

This package fixes two bugs with one mechanism.

- **Reproduction 1:** an instance inside `for (genvar i = 0; i < 2; i++) begin : g ... end` is lost.
- **Reproduction 2:** `task t(input logic a, output logic b); endtask` inside a module adds `a` and `b` to the module ports. The same happens for `function`.
- **Cause:** `module_body` enters the state `begin` on every `begin`. That state only knows `end`, so everything inside becomes `Error` tokens, including instances in generate blocks. Nested blocks are not counted. Tasks and functions have no state at all, so their `input` / `output` are taken as ports.
- **Design:** distinguish procedural code from generate code by the keyword that introduces it.
  1. In `module_body`, before the generic `keywords` rule, add a rule for `always`, `always_ff`, `always_comb`, `always_latch`, `initial` and `final` that pushes a new state `procedural`.
  2. `procedural` skips one statement: comments and strings are consumed; `begin` switches to `("#pop", "proc_after", "proc_block")`; `;` pops; anything else is consumed with cheap rules (`\w+`, `\s+`, `.`), not one `Error` token per character.
  3. `proc_block` counts nesting: `begin`, `fork` and `case`-less blocks push `#push`; `end`, `join`, `join_any`, `join_none` pop; comments and strings are consumed; everything else is consumed cheaply.
  4. `proc_after` handles `else`: whitespace and comments are consumed; `else` switches to `("#pop", "procedural")`; `default("#pop")`.
  5. Add states `function_body` and `task_body`, entered from `module_body` on `function` and `task`, which consume everything up to `endfunction` / `endtask`.
  6. Remove the `begin` rule and the `begin` state from `module_body`. A `begin` at module level is then a generate block, and its content is lexed as normal module body, so instances are found.
- **Pitfalls:**
  - `import "DPI-C" function int f(input int a);` and `export "DPI-C" ...;` have no `endfunction`. Add a rule in `module_body`, before the `function` rule, that consumes `\b(import|export)\s+"DPI(-C)?"[^;]*;`.
  - Use `\b` around every keyword; `endfunction` must not match inside `my_endfunction_x`.
  - `module_body` is also where non-ANSI port declarations (`input [7:0] a;`) are found. They must keep working: run the non-ANSI test.
  - A procedural statement without `begin` that contains `case ... endcase` ends at its first `;`, and the rest is lexed as module body. That is the same as today and acceptable. Do not try to parse `case`.
  - Instances inside a generate block must carry the right `ifdefs`.
- **Tests:** instance in a generate `for`; in a generate `if ... else`; in nested generate blocks; `always_ff` with nested `begin`/`end` followed by an instance; `always_comb if (a) begin ... end else begin ... end` followed by an instance; a task and a function with ports followed by an instance, asserting the module ports are unchanged; the DPI import; a `fork ... join` in an `initial` block.
- **Reference data:** existing examples and many corpus files gain instances that were lost before. Each one must be a real instance in the source file; spot-check at least ten against the corpus sources and list them in the PR.

### B4. Parameter overrides on instances

- **Problem:** `sub #(.W(8), .T(logic [3:0])) u (...)` is matched but the parameters are discarded.
- **Design:** in `filter_instance_keywords_callback`, when the match contains `#(`, locate it and use `find_closing` to get the full parameter text (the regex's `#\(.*?\)` is not reliable for nested parentheses; change the rule so the callback, not the regex, consumes the parameter list). Parse entries with `split_args`; `.NAME(value)` gives a named override, anything else an ordered one. Add `params: tuple[Connection, ...] = ()` to `ModuleInstance`, reusing `Connection` (`port` is the parameter name, `con` the value).
- **Tests:** named, ordered, nested parentheses, type parameter, no parameters.

## 7. Group C: ports and types

### C1. Robust dimensions

- **Reproduction 1:** `output logic q [2] [3]` gives `dim_unpacked == "[2]"`.
- **Reproduction 2:** `input logic [W[1]-1:0] d` raises `TypeError: 'NoneType' object is not iterable` in `_normalize_ports`.
- **Design:**
  1. Replace the dimension rule `((\[[^]]+\])+)` in `port_declaration` and `param_declaration` with a callback on `\[` that counts brackets with `_iter_toplevel` and then keeps consuming further `\s*\[...\]` groups. Emit one token with whitespace between groups removed.
  2. In `_normalize_ports` and `_normalize_params`, skip a declaration whose `name` is `None` and log a warning naming the module. A malformed declaration must never raise.
- **Tests:** both reproductions, `[7:0][3:0]` packed, `[2][3]` and `[2] [3]` unpacked, the same for parameters.

### C2. User-defined types and interface ports

- **Reproductions:**
  - `input my_pkg::req_t req_i` gives a port named `my_pkg`.
  - `input req_t [3:0] reqs` and `input T d` give two ports each.
  - `axi_if.slave s_axi` and `axi_if s_axi` give no port.
- **Cause:** in `port_declaration`, every identifier that is not a built-in type keyword is a port name. In `module_header`, an identifier without a direction is ignored.
- **Design:**
  1. **Type by lookahead.** In `port_declaration`, before the `Port.PortName` rule, add a rule that matches an identifier, optionally scoped with `::`, only when another identifier follows after optional whitespace and optional packed dimensions: `[a-zA-Z_]\w*(?:::[a-zA-Z_]\w*)*(?=\s*(?:\[[^\]]*\]\s*)*[a-zA-Z_\\])`. Emit `Port.Ptype`.
  2. **New declaration after a comma.** `input my_t a, other_t b` declares `b` with the inherited direction and a new type. In `_proc_port_tokens` (or its caller), when a `Port.Ptype` or `Port.Dtype` token arrives and the current `PortDecl` already has a name, start a new `PortDecl` that copies `direction`.
  3. **Interface ports.** In `port_declaration` (before rule 1) and in `module_header`, add a rule for `([a-zA-Z_]\w*)\.([a-zA-Z_]\w*)\s+([a-zA-Z_]\w*)`. In `module_header` also add `([a-zA-Z_]\w*)\s+([a-zA-Z_]\w*)(?=\s*(?:\[[^\]]*\]\s*)*[,)])` for an interface port without modport. Both emit a new token `Port.Interface` carrying the type text, followed by `Port.PortName`. In the parser, `Port.Interface` starts a new `PortDecl` with `direction=""` and `ptype` set to `axi_if.slave` or `axi_if`.
  4. No change to the public model: `ptype` holds the type text and `direction` is empty for interface ports.
- **Pitfalls:**
  - The non-ANSI header `module m (a, b, c);` has single identifiers and must stay port-less in the header.
  - Keywords must not be taken as user types: exclude names in `keywords_types_tup` in the callback, or keep the keyword rules before the new rules.
  - `input a, b` must still give two ports with the same direction.
  - Check `gen-sv-instance` and `info` output for an interface port; an empty direction must not break the Markdown table.
- **Tests:** every reproduction, plus `input a, b`, `input logic a, my_t b`, `input my_t a, b`, an interface array port `axi_if.master m_axi [4]`, and the non-ANSI header.
- **Reference data:** `ptype` values of existing examples should not change. Explain any that do.
- **Corpus:** this package must clear every "bug 6" and "bug 7" entry in `KNOWN_ISSUES_INVARIANTS`. If some remain, the design is not fully implemented. The corpus reference data of those files changes: the spurious type-named ports disappear and `ptype` gets filled.

### C3. Parameter type keywords

- **Reproduction:** `parameter int unsigned A = 1` gives `ptype == "unsigned"`.
- **Design:** in `_proc_param_tokens`, append successive `Param.ParamType` tokens with a space instead of overwriting: `"int unsigned"`. Leave ports as they are (`signed` / `unsigned` already go to `dtype`).
- **Tests:** `int unsigned`, `logic signed [7:0]`, plain `int`. Check the reference data: only parameters with two type keywords may change.

### C4. Warn about dropped header text

- **Problem:** text in a module header that no rule matches disappears as `Error` tokens.
- **Design:** in `get_tokens_unprocessed`, when an `Error` token is produced while `module_header`, `port_declaration` or `param_declaration` is on the stack, remember the first such position per module. In `parse()`, log one warning per module with the line number (count newlines up to the position) and the offending text, truncated to 40 characters. Do not warn per character.
- **Do this after C2**, otherwise it is noisy.
- **Tests:** a header with garbage warns once; all examples parse without this warning (assert with `caplog` in `test_examples`).

## 8. Group D: filelists

### D1. Filelist options

- **Problem:** only `-f`, `+incdir+` and file paths are understood. `inc_dirs` are collected and never used.
- **Design:** in `filelistparser.py`:
  - Expand `$VAR` and `${VAR}` with `os.path.expandvars` before matching.
  - Parse `+define+A=1+B` and `-D A=1` / `-DA=1` into an optional container. To keep the public signature compatible, add a keyword argument `defines: dict[str, str] | None = None` to `parse_filelist` and `_parse`; fill it when given.
  - Accept and ignore, at `DEBUG` level, `-y <dir>`, `-v <file>`, `+libext+...`, `-timescale...` and `-sv`.
  - A single line may hold several `+incdir+a+b` entries; split on `+`.
- **CLI:** in `cli.py`, `_join_filepaths` should return the include directories and defines too. Convert each define to `Macro(name=name, body=value)` and merge them into the `macros` passed to `parse_file`. Macros from `--macro-file` win on a name clash.
- **Tests:** each option, an environment variable set with `monkeypatch.setenv`, and one CLI test where a `+define+WIDTH=4` in the filelist resolves `` [`WIDTH-1:0] `` in a module header.

## 9. Group E: macro follow-ups

Read `src/hdl_parser/_sv/preproc.py` and `tests/test_macros.py` first. Current rules, which you must keep: expansion only in module headers; a macro with conflicting definitions is never expanded; macros passed by the caller win over defines in the file; unknown macros are reported in `Module.unresolved_macros`.

### E1. `` `include `` resolution

- **Goal:** `parse_file("top.sv", inc_dirs=[...])` finds macros in included files without `--macro-file`.
- **Design:**
  1. Add a group to `_RE_SCAN` for `` `include\s+"([^"]+)" `` (it must come before the generic macro alternative).
  2. Add `collect_includes(text) -> list[str]`.
  3. In `parser.py`, add `inc_dirs: Iterable[Path] = ()` to `parse_file` and `parse_text`. Resolve each include relative to the including file's directory first, then each include directory. Collect defines recursively with a visited set to stop include cycles. A file that cannot be found is logged at `DEBUG` level and skipped.
  4. Cache `collect_defines` per resolved path and modification time (a module-level dict is enough) so a shared header is read once per run.
  5. Merging must respect the conflict rule: the same name with a different body across files makes the macro ambiguous and skipped. Write a `merge_defines` helper in `preproc.py`; do not use dict union.
  6. Precedence: `macros=` argument, then defines in the file itself, then included files.
- **CLI:** pass the include directories from the filelist (D1) and add `-I/--incdir`.
- **Tests:** include next to the file, include through `inc_dirs`, nested include, include cycle, missing include, conflict across two includes, cache hit (count `read_text` calls with a monkeypatch).

### E2. Evaluated conditionals

- **Goal:** `parse_file(..., defines={"FPGA"})` returns only the active branch. Without `defines` (the default, `None`) today's annotate-only behaviour is unchanged.
- **Design:** a new function `evaluate_conditionals(text, defines) -> str` in `preproc.py`, run before `expand()` when `defines` is not `None`.
  - One sequential pass over the text with a comment- and string-aware scanner (extend `_RE_SCAN`).
  - Maintain the set of defined names: start from `defines`, add on `` `define ``, remove on `` `undef ``, both only in active regions.
  - Handle `` `ifdef ``, `` `ifndef ``, `` `elsif ``, `` `else ``, `` `endif `` with a stack.
  - Replace inactive regions and the directive lines themselves with the same number of newlines, so line numbers do not move.
- **Consequences to assert in tests:** `ifdefs` tuples are empty in this mode; a macro defined differently in two branches is no longer ambiguous and is expanded.
- **CLI:** `-D NAME[=VALUE]`, repeatable; filelist defines from D1 count too.
- **Tests:** each directive, nesting, `` `define `` inside an active and an inactive branch affecting a later `` `ifdef ``, unbalanced `` `endif `` (warn, do not raise), line count preserved.

### E3. Macro expansion in the module body

- **Problem:** non-ANSI modules declare ports in the body, so port macros there are not expanded.
- **Design:** add `expand_body: bool = False` to `expand()`, `parse()`, `parse_file()` and `parse_text()`. When true, `_Expander` treats everything from `module` to `endmodule` as expandable: add `endmodule` to the keyword group of `_RE_SCAN` and end the region there instead of at the header's `;`.
- **CLI:** `--expand-body` flag on all three commands.
- **Tests:** a non-ANSI module with a port macro in the body, with and without the flag; text after `endmodule` is not expanded.

## 10. Group F: features

### F1. Header-only mode

- **Goal:** `parse_file(..., header_only=True)` skips module bodies. This is the largest speed gain when only ports and parameters are needed.
- **Design:** pass `header_only` to `SystemVerilogLexer(header_only=True)` (Pygments stores keyword options; read it in `__init__`). The header ends in three rules: `;` and `\)\s*;` in `module_header`, and `\)\s*;` in `port_declaration` and `param_declaration`. Replace their actions with one callback that emits the same token and state change and then, in header-only mode, moves `ctx.pos` to the next `endmodule` that is not inside a comment or string (use a compiled regex with comment and string alternatives, as `_RE_SCAN` does).
- **Pitfall:** a non-ANSI module needs its body for the ports. Skip only when the header contained at least one direction keyword or had an empty port list; track this with a flag on the lexer instance, reset at each `module`.
- **Tests:** ANSI module (no instances returned, ports equal to full mode), non-ANSI module (ports still found), two modules in one file, `endmodule` inside a comment in the body. Add a timing note to the PR, not a timing assertion to the tests.

### F2. Parallel parsing

- **Design:** add `parse_files(file_paths, *, macros=None, jobs=1) -> list[File]` to `parser.py`, using `concurrent.futures.ProcessPoolExecutor` when `jobs > 1` and a plain loop otherwise. Results keep the input order. Add `-j/--jobs` to the CLI commands and use `parse_files` there.
- **Pitfalls:** the worker function must be a module-level function (picklable). On failure, report which file failed. Keep `jobs=1` the default so tests and coverage are unaffected.
- **Tests:** `jobs=2` returns the same result as `jobs=1` for all examples.

### F3. Hierarchy tree

- **Design:** new module `src/hdl_parser/hierarchy.py` with `build_hierarchy(files, top=None)`: index all modules by name, link each `ModuleInstance.module` to its definition, report modules that are instantiated but not defined, and choose as top every module that is never instantiated when `top` is not given. Detect recursion and stop. New CLI command `tree` that prints with `rich.tree.Tree`, plus `--json`.
- **Tests:** a three-level example in `examples/sv/`, an unresolved module, two tops, explicit `--top`.

### F4. Interfaces and packages

- **Owner decision, default chosen:** add `File.interfaces: tuple[Interface, ...] = ()` and `File.packages: tuple[Package, ...] = ()`. `Interface` has `name`, `params`, `ports`, `modports`; `Modport` has `name` and `ports` (reuse `Port`). `Package` has `name` and `params`.
- **Design:** treat `interface ... endinterface` like a module in the lexer by reusing the header states with a different start token and end keyword. Add a `modport` state so that `input` / `output` inside `modport name (...)` are not taken as interface ports. For packages, capture `parameter` and `localparam` only.
- **Pitfalls:** `virtual interface` and `interface class` are not interface declarations. `import pkg::*;` is not a package declaration.
- **Tests:** an interface with parameters, ports and two modports; a package with parameters; a file mixing all three kinds.

### F5. Source locations

- **Goal:** `line` on `Module`, `Port`, `Param` and `ModuleInstance`.
- **Design:** `parse()` uses `lexer.get_tokens(text)`, which drops positions and also normalises the text (strips leading and trailing newlines). Switch to `get_tokens_unprocessed` on text you normalise yourself the same way, keep the offset of each name token, and convert offsets to lines with `bisect` over a precomputed list of newline offsets.
- **Pitfall:** macro expansion changes offsets. Have `expand()` optionally return a list of `(expanded_start, expanded_end, original_offset)` spans; an item inside an expansion gets the line of the macro call.
- **Reference data:** every reference file changes because `line` is populated. That is expected; verify that the diff contains only added `line` values.
- **Do this last among the lexer packages.**

### F6. Port provenance from macros

- **Goal:** `Port.macro: str = ""` and `Param.macro: str = ""` hold the text of the macro call that produced the item, for example `` `STREAM_PORTS(in, input, output, IN_WIDTH) ``.
- **Design:** build on the span list from F5. When an item's offset lies inside an expansion span, set `macro` to the original call text. Only the outermost macro is recorded.
- **Tests:** extend `tests/test_macros.py::test_example`: the first two ports come from `` `CLK_RST_PORTS ``, `busy_o` has `macro == ""`.

### F7. Smaller features

Each is one small package.

- **Custom templates:** `gen-sv-instance --template FILE` renders a user Jinja template with the `Module` object. See `src/hdl_parser/_gen_templates.py`.
- **Attributes:** capture `(* ... *)` before a port or module into `attributes: tuple[str, ...] = ()`. Needs a lexer rule in `module_header` and `port_declaration`.
- **Non-ANSI port order:** for `module m (a, b, c);` with directions declared in the body, return ports in header order. Capture the header identifier list and sort in `_normalize_ports`.
- **Width evaluation:** `datamodel` helper `eval_dim(dim, params) -> int | None` that evaluates simple constant expressions (`+ - * /`, `$clog2`, parentheses) with parameter values. Use a small recursive-descent evaluator; never call `eval()`.
- **VHDL status:** owner decision needed: either document `_vhdl/` as experimental in `README.md` and `docs/`, or state it is unsupported. Do not implement anything until decided.
