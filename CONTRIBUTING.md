# CONTRIBUTING

Please follow the github workflow. Create a ticket and/or branch. Create a pull-request.

See [github Documentation](https://docs.github.com/en/pull-requests/collaborating-with-pull-requests/proposing-changes-to-your-work-with-pull-requests/creating-a-pull-request) for further information.
We follow the [Semantic Version Scheme](https://semver.org/).

## Local Development

### Installation

Please install these tools:

* [`uv` Installation](https://docs.astral.sh/uv/getting-started/installation/)
* [`make`](https://www.gnu.org/software/make/)
* [`git`](https://git-scm.com/)
* [Visual Studio Code](https://code.visualstudio.com/)


### Editor
Start Visual Studio Code:

```bash
make code
```

### Testing

Run auto-formatting, linting, tests and documentation build:

```bash
make all
```

See `make help` for any further details.


## Comparing parser output between revisions

`tools/compare_refs.py` parses a set of HDL files with two git revisions of `hdl_parser` and shows which modules, ports and instances changed.
Use it to check a parser change against code you cannot commit as test data, for example a private code base.
The files are parsed locally; nothing is sent anywhere and nothing is written into the repository.
Use `--out DIR` (a directory outside the repository) to keep the two JSON dumps.

Compare the working tree (including uncommitted changes) against `main`:

```bash
uv run python tools/compare_refs.py --base main path/to/rtl
```

Compare two revisions using a filelist and a macro file:

```bash
uv run python tools/compare_refs.py --base v1.0.0 --head my-branch -f rtl/files.f -m rtl/defines.svh --out ~/compare
```

The tool prints a unified diff of the JSON for every file that differs, followed by a summary:

| Class | Meaning |
|---|---|
| identical | Same output on both sides |
| changed | Output differs; see the diff |
| newly failing | Parses on base, raises on head. Treat as a regression |
| newly passing | Raises on base, parses on head |
| failing on both | Raises on both sides |

The summary also shows the total parse time per side and their ratio.
The exit code is 0 when everything is identical, 1 when anything differs, 2 on usage or git errors.
Read every diff: a change is only fine if you can explain it as an intended result of your work.

Before merging any change to `src/hdl_parser/_sv/lexer.py` or `src/hdl_parser/_sv/parser.py`, run the tool on a large private code base and review the result.

## Project Structure

The project contains these files and directories:

| File/Directory | Description |
|---|---|
| `src/` | Python Package Sources - the files this is all about |
| `pyproject.toml` | Python Package Meta File. Also contains all tool settings |
| `.gitignore` | Lists of files and directories ignored by version control system |
| `.github/` | Github Settings |
| `.readthedocs.yaml` | Documentation Server Configuration |
| `.pre-commit-config.yaml` | Pre-Commit Check Configuration |
| `uv.lock` | File with resolved python package dependencies |

Next to that, there are some temporary files ignored by version control system.

| File/Directory | Description |
|---|---|
| `htmlcov/` | Test Execution Code Coverage Report in HTML format |
| `report.xml` | Test Execution Report |
| `.venv` | Virtual Environments |
