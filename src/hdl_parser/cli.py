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
"""Command Line Interface."""

import json as json_
import logging
import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import click
from pydantic import BaseModel, ConfigDict
from rich.console import Console
from rich.logging import RichHandler

from . import query
from ._gen_templates import gen_instance, gen_markdown_table
from ._mcp import serve
from .datamodel import File
from .filelistparser import parse_filelist
from .parser import parse_defines, parse_file
from .project import Project

LOGGER = logging.getLogger(__name__)

_LOGLEVELMAP = {
    0: logging.WARNING,
    1: logging.INFO,
    2: logging.DEBUG,
}


arg_filepaths = click.argument("filepaths", nargs=-1, type=click.Path(exists=True, readable=True, path_type=Path))
opt_filelists = click.option(
    "--filelist", "-f", type=click.Path(exists=True, readable=True, path_type=Path), multiple=True, help="Filelist"
)
opt_expand_macros = click.option(
    "--expand-macros",
    "-e",
    is_flag=True,
    help="Expand macros which are defined in the file, its included files or the files given by '--macro-file'.",
)
opt_macro_files = click.option(
    "--macro-file",
    "-m",
    "macro_files",
    type=click.Path(exists=True, readable=True, path_type=Path),
    multiple=True,
    help="File with `define macros. Requires '--expand-macros'. Can be given multiple times.",
)
opt_resolve_ifdefs = click.option(
    "--resolve-ifdefs",
    "-r",
    is_flag=True,
    help="Resolve `ifdef conditions on macros which are known to be defined. Requires '--expand-macros'.",
)
opt_inc_dirs = click.option(
    "--incdir",
    "-I",
    "inc_dirs",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    multiple=True,
    help="Directory to search for included files, in addition to the ones of the filelists. "
    "Used by '--expand-macros'. Can be given multiple times.",
)


def opt_parse(func):
    """Options which control the parser. See `_parse_files`."""
    for option in (opt_resolve_ifdefs, opt_inc_dirs, opt_macro_files, opt_expand_macros, opt_filelists):
        func = option(func)
    return func


def _create_console(**kwargs) -> Console:
    return Console(**kwargs)


class Ctx(BaseModel):
    """Command Line Context."""

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
    )

    console: Console

    verbose: int = 0
    no_color: bool | None = None

    @staticmethod
    def create(no_color: bool | None = None, **kwargs) -> "Ctx":
        """Create."""
        console = _create_console(log_time=False, log_path=False, no_color=no_color)
        return Ctx(console=console, no_color=no_color, **kwargs)

    def __enter__(self):
        # Logging
        level = _LOGLEVELMAP.get(self.verbose, logging.DEBUG)
        if not self.no_color:
            handler = RichHandler(
                show_time=False,
                show_path=False,
                rich_tracebacks=True,
                console=_create_console(stderr=True, no_color=self.no_color),
            )
            format_ = "%(message)s"
        else:
            handler = logging.StreamHandler(stream=sys.stderr)
            format_ = "%(levelname)s %(message)s"
        handlers = [handler]
        logging.basicConfig(level=level, format=format_, handlers=handlers)

        return self

    def __exit__(self, exc_type, exc_value, tb):  # pragma: no cover
        # '--help' and usage errors are handled by click
        if exc_type and not issubclass(exc_type, (click.exceptions.Exit, click.ClickException)):
            # standard output is kept for the answer
            stderr = _create_console(stderr=True, no_color=self.no_color)
            if exc_type is KeyboardInterrupt:
                stderr.print("[red]Aborted.")
            else:
                # tell the reason
                LOGGER.error("%s: %s", exc_type.__name__, exc_value)
                stderr.print("[red][bold]Failed.")
            sys.exit(EXIT_FAILED)


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("-v", "--verbose", count=True, help="Increase Verbosity.")
@click.option("--no-color", is_flag=True, help="Disable Coloring.", envvar="UCDP_NO_COLOR")
@click.version_option()
@click.pass_context
def cli(ctx, verbose=0, no_color=False):
    """Easy-To-Use SystemVerilog Parser."""
    ctx.obj = ctx.with_resource(Ctx.create(verbose=verbose, no_color=no_color))


pass_ctx = click.make_pass_decorator(Ctx)


@cli.command()
@arg_filepaths
@opt_parse
@pass_ctx
def gen_sv_instance(ctx, filepaths: tuple[Path, ...], **options):  # noqa: ARG001
    """Parses an SystemVerilog file and returns a instance of the module."""
    for file in _parse_files(filepaths, **options):
        for module in file.modules:
            instance = gen_instance(module)
            print(instance)


@cli.command()
@arg_filepaths
@opt_parse
@pass_ctx
@click.option(
    "--width",
    "-w",
    type=int,
    help="Enforce Table Width. Environment Variable HDL_PARSER_WIDTH.",
    envvar="HDL_PARSER_WIDTH",
)
@click.option("--level", "-l", type=int, default=2, help="Markdown Header Level. Default 2. Means '##'")
@click.option("--sub", "-s", is_flag=True, help="Show Submodules")
def info(
    ctx: Ctx,
    filepaths: tuple[Path, ...],
    width: int | None = None,
    level: int = 2,
    sub: bool = False,
    **options,
) -> None:
    """Creates Markdown Overview Tables."""
    for file in _parse_files(filepaths, **options):
        pre = "#" * level
        for module in file.modules:
            params, ports, insts = gen_markdown_table(module, width=width)
            ctx.console.print(f"""\
{pre} Module `{module.name}`

Path `{file.path!s}`
""")

            if params:
                ctx.console.print(f"{pre}# Parameters")
                ctx.console.print(params)

            ctx.console.print(f"{pre}# Ports")
            if ports:
                ctx.console.print(ports)
            else:
                ctx.console.print("\nNo Ports\n")

            if sub:
                ctx.console.print(f"{pre}# Submodules")
                if insts:
                    ctx.console.print(insts)
                else:
                    ctx.console.print("\nNo Submodules\n")


@cli.command()
@arg_filepaths
@opt_parse
def json(filepaths: tuple[Path, ...], **options) -> None:
    """Dump All Extracted Information in a JSON file."""
    for file in _parse_files(filepaths, **options):
        print(file.overview)


EXIT_OK = 0
"""The answer is printed. Problems of the design are part of the answer, never a failure."""
EXIT_FAILED = 1
"""Internal failure: a bug. The reason is printed on standard error."""
EXIT_USAGE = 2
"""Wrong command line, or bad argument of a query (`{"error": {"code": "bad-argument", ...}}`)."""
EXIT_NOT_FOUND = 3
"""Name not found: `{"error": {"code": "not-found", "suggestions": [...]}}` on standard output."""

_PATHS_HELP = """
    PATHS are the files of the design, or one directory with all of them. The current directory by default.
    Alternatively a filelist is given by '--filelist'.
"""


def opt_project(func):
    """Options which create the project."""
    options = (
        click.argument("paths", nargs=-1, type=click.Path(exists=True, readable=True, path_type=Path)),
        click.option(
            "--filelist",
            "-f",
            type=click.Path(exists=True, dir_okay=False, path_type=Path),
            help="Filelist of the project.",
        ),
        opt_expand_macros,
        opt_resolve_ifdefs,
        opt_inc_dirs,
        click.option(
            "--define",
            "-D",
            "defines",
            multiple=True,
            metavar="NAME[=VALUE]",
            help="Macro defined for all files. Used by '--expand-macros'. Can be given multiple times.",
        ),
        click.option(
            "--root",
            type=click.Path(exists=True, file_okay=False, path_type=Path),
            help="Root directory. All paths are relative to it. By default the directory given, or the common one.",
        ),
        click.option(
            "--exclude", "-x", multiple=True, help="Pattern of files to be left out of a directory: 'models/*'."
        ),
        click.option("--cache", is_flag=True, help="Keep the results within the root, parse changed files only."),
        click.option(
            "--cache-dir",
            type=click.Path(file_okay=False, path_type=Path),
            help="Keep the results in this directory, parse changed files only. Implies '--cache'.",
        ),
    )
    for option in reversed(options):
        func = option(func)
    return func


def opt_answer(func):
    """Options which size the answer of a query."""
    options = (
        click.option(
            "--limit",
            "-n",
            type=click.IntRange(min=0),
            help="Number of entries of every list. Default 100. 0 for no limit. "
            "Left out entries are counted in 'omitted'.",
        ),
        click.option("--compact", "-c", is_flag=True, help="JSON on a single line."),
    )
    for option in reversed(options):
        func = option(func)
    return func


opt_fields = click.option(
    "--fields", "-F", multiple=True, help="Comma separated fields to be returned. Can be given multiple times."
)
opt_blackbox = click.option(
    "--blackbox",
    "blackboxes",
    multiple=True,
    metavar="PATTERN",
    help="Module names known to be missing (blackboxes, cells): no 'undefined-module' for them. Can be given "
    "multiple times.",
)
opt_summary = click.option("--summary", "-s", is_flag=True, help="Names and counts only.")


def load_project(  # noqa: PLR0913
    paths: tuple[Path, ...] = (),
    filelist: Path | None = None,
    expand_macros: bool = False,
    resolve_ifdefs: bool = False,
    inc_dirs: tuple[Path, ...] = (),
    defines: tuple[str, ...] = (),
    root: Path | None = None,
    exclude: tuple[str, ...] = (),
    cache: bool = False,
    cache_dir: Path | None = None,
) -> Project:
    """Create the project according to the options of `opt_project`."""
    if resolve_ifdefs and not expand_macros:
        raise click.UsageError("'--resolve-ifdefs' requires '--expand-macros'.")
    if filelist and paths:
        raise click.UsageError("Give either PATHS or '--filelist'.")
    if not filelist and not paths:
        paths = (Path(),)
    dirs = [path for path in paths if path.is_dir()]
    if dirs and len(paths) > 1:
        raise click.UsageError("Give either one directory or files.")
    if exclude and not dirs:
        raise click.UsageError("'--exclude' requires a directory.")
    kwargs: dict[str, Any] = {
        "root": root,
        "expand_macros": expand_macros,
        "resolve_ifdefs": resolve_ifdefs,
        "defines": dict(_split_define(define) for define in defines),
        "inc_dirs": inc_dirs,
        "cache": cache_dir or cache,
    }
    if filelist:
        return Project.from_filelist(filelist, **kwargs)
    if dirs:
        if root is not None:
            raise click.UsageError("'--root' is the directory given.")
        del kwargs["root"]
        return Project.from_dir(dirs[0], exclude=exclude, **kwargs)
    return Project.from_files(paths, **kwargs)


def _split_define(define: str) -> tuple[str, str]:
    name, _, value = define.partition("=")
    if not name:
        raise click.BadParameter(f"'{define}' has no name.", param_hint="'--define'")
    return name, value


def _quiet(ctx: Ctx) -> None:
    """Problems are part of the JSON answer. Log them on request only (`-v`)."""
    if ctx.verbose:
        return
    logger = logging.getLogger("hdl_parser._diagnostics")
    level = logger.level
    logger.setLevel(logging.ERROR)
    click.get_current_context().call_on_close(lambda: logger.setLevel(level))


def _fields(fields: tuple[str, ...]) -> tuple[str, ...]:
    return tuple(name.strip() for item in fields for name in item.split(",") if name.strip())


def _answer(func, compact: bool = False) -> None:
    """Print the answer of the query `func`. A failed query is an error object and exit code."""
    try:
        answer = func()
        code = EXIT_OK
    except query.QueryError as exc:
        answer = exc.to_dict()
        code = EXIT_NOT_FOUND if exc.code == "not-found" else EXIT_USAGE
    print(json_.dumps(answer, indent=None if compact else 2))
    if code:
        raise click.exceptions.Exit(code)


@cli.command(
    help=f"""Dump All Files Of A Design As One JSON Document.
{_PATHS_HELP}
    The document has the format given by 'hdl-parser schema'. Problems are listed
    in its 'diagnostics' and the ones of its files. A file which cannot be read or
    parsed does not stop the others.
"""
)
@opt_project
@pass_ctx
def project(ctx: Ctx, **options) -> None:
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    print(load_project(**options).overview)


@cli.command(
    help=f"""One Module, Interface Or Package As JSON.

    NAME is a name or a full identifier ('rtl/top.sv:top').
{_PATHS_HELP}"""
)
@click.argument("name")
@opt_project
@opt_fields
@opt_summary
@opt_answer
@pass_ctx
def module(ctx: Ctx, name: str, fields: tuple[str, ...], summary: bool, limit: int | None, compact: bool, **options):  # noqa: PLR0913
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    prj = load_project(**options)
    _answer(lambda: query.module(prj, name, fields=_fields(fields), limit=limit, summary=summary), compact)


@cli.command(
    help=f"""Instance Tree Below A Module As JSON. The Top Modules, If '--top' Is Not Given.
{_PATHS_HELP}"""
)
@click.option("--top", "-t", help="Name or full identifier of the module.")
@click.option("--depth", "-d", type=click.IntRange(min=0), help="Number of instance levels below the top.")
@click.option("--leaves", is_flag=True, help="Without '--top': top modules without instances too.")
@click.option("--text", is_flag=True, help="The tree as indented text, much smaller than JSON.")
@opt_project
@opt_fields
@opt_summary
@opt_answer
@pass_ctx
def hierarchy(  # noqa: PLR0913
    ctx: Ctx,
    top: str | None,
    depth: int | None,
    leaves: bool,
    text: bool,
    fields: tuple[str, ...],
    summary: bool,
    limit: int | None,
    compact: bool,
    **options,
):
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    prj = load_project(**options)
    _answer(
        lambda: query.hierarchy(
            prj, top, depth=depth, limit=limit, fields=_fields(fields), summary=summary, leaves=leaves, text=text
        ),
        compact,
    )


@cli.command(
    help=f"""All Instances Of A Module As JSON.

    NAME is a name or a full identifier ('rtl/top.sv:top').
{_PATHS_HELP}"""
)
@click.argument("name")
@opt_project
@opt_answer
@pass_ctx
def where_used(ctx: Ctx, name: str, limit: int | None, compact: bool, **options):
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    prj = load_project(**options)
    _answer(lambda: query.where_used(prj, name, limit=limit), compact)


@cli.command(
    help=f"""Items By Name As JSON.

    PATTERN without wildcard is part of the name, not case sensitive ('clk' finds 'clk_i').
    With wildcards ('*', '?', '[...]') it matches the name or the full identifier ('rtl/top.sv:top.*').
{_PATHS_HELP}"""
)
@click.argument("pattern")
@click.option(
    "--kind", "-k", "kinds", multiple=True, type=click.Choice(sorted(set(query.KINDS.values()))), help="Kind of items."
)
@opt_project
@opt_fields
@opt_answer
@pass_ctx
def find(  # noqa: PLR0913
    ctx: Ctx, pattern: str, kinds: tuple[str, ...], fields: tuple[str, ...], limit: int | None, compact: bool, **options
):
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    prj = load_project(**options)
    _answer(lambda: query.find(prj, pattern, kinds=kinds, limit=limit, fields=_fields(fields)), compact)


@cli.command(
    help=f"""Problems Found In The Design As JSON.
{_PATHS_HELP}"""
)
@click.option("--severity", type=click.Choice(query.SEVERITIES), help="Minimum severity. Everything by default.")
@click.option("--code", "codes", multiple=True, help="Code of the problems. Can be given multiple times.")
@click.option("--file", "file_", help="Path of a file, relative to the root, or a pattern ('rtl/*').")
@click.option("--exclude-file", "excludes", multiple=True, help="Pattern of files whose problems are left out.")
@opt_blackbox
@click.option("--group-by", type=click.Choice(("code", "file", "module")), help="Number of problems by group.")
@opt_project
@opt_answer
@pass_ctx
def diagnostics(  # noqa: PLR0913
    ctx: Ctx,
    severity: str | None,
    codes: tuple[str, ...],
    file_: str | None,
    excludes: tuple[str, ...],
    blackboxes: tuple[str, ...],
    group_by: str | None,
    limit: int | None,
    compact: bool,
    **options,
):
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    prj = load_project(**options)
    _answer(
        lambda: query.diagnostics(
            prj,
            severity=severity,
            codes=codes,
            file=file_,
            limit=limit,
            exclude=excludes,
            blackboxes=blackboxes,
            group_by=group_by,
        ),
        compact,
    )


opt_params = click.option(
    "--param",
    "-p",
    "params",
    multiple=True,
    metavar="NAME=VALUE",
    help="Value of a parameter of the top or scope. Can be given multiple times.",
)


def _params(params: tuple[str, ...]) -> dict[str, int | float | str | bool]:
    values: dict[str, int | float | str | bool] = {}
    for param in params:
        name, sep, text = param.partition("=")
        if not sep or not name:
            raise click.UsageError(f"'{param}' is no NAME=VALUE.")
        values[name] = _scalar(text)
    return values


def _scalar(text: str) -> int | float | str | bool:
    if text.lower() in ("true", "false"):
        return text.lower() == "true"
    for convert in (int, float):
        try:
            return convert(text)
        except ValueError:  # noqa: PERF203
            pass
    return text


@cli.command(
    help=f"""Parameter Values And Port Widths Of An Instance As JSON.

    TOP is a name or a full identifier ('rtl/top.sv:top').
{_PATHS_HELP}"""
)
@click.argument("top")
@click.option("--path", default="", help="Instance names below TOP, separated by dots: 'u_core.u_alu'.")
@opt_params
@click.option("--depth", "-d", type=click.IntRange(min=0), default=0, help="Instance levels below, default 0.")
@click.option("--name", "names", multiple=True, help="Pattern of names of parameters and ports.")
@click.option("--unknown", is_flag=True, help="Only values which are not known, with the reason.")
@opt_project
@opt_answer
@pass_ctx
def elaborate(  # noqa: PLR0913
    ctx: Ctx,
    top: str,
    path: str,
    params: tuple[str, ...],
    depth: int,
    names: tuple[str, ...],
    unknown: bool,
    limit: int | None,
    compact: bool,
    **options,
):
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    values = _params(params)
    prj = load_project(**options)
    _answer(
        lambda: query.elaborate(
            prj, top, path=path, params=values, depth=depth, names=names, unknown=unknown, limit=limit
        ),
        compact,
    )


@cli.command(
    help=f"""Value Of An Expression Within A Module Or Package As JSON.
{_PATHS_HELP}"""
)
@click.argument("expr")
@click.argument("scope")
@opt_params
@opt_project
@opt_answer
@pass_ctx
def evaluate(ctx: Ctx, expr: str, scope: str, params: tuple[str, ...], limit: int | None, compact: bool, **options):  # noqa: ARG001, PLR0913
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    values = _params(params)
    prj = load_project(**options)
    _answer(lambda: query.evaluate(prj, expr, scope, params=values), compact)


_PATH_HELP = """PATH is the instance path of a signal: the top module, the instance names below (with the labels
    of the generate blocks around) and the signal, separated by dots ('top.u_core.u_alu.result_o')."""


@cli.command(
    help=f"""What Drives A Signal As JSON.

    {_PATH_HELP}
{_PATHS_HELP}"""
)
@click.argument("path")
@opt_params
@opt_project
@opt_answer
@pass_ctx
def drivers(ctx: Ctx, path: str, params: tuple[str, ...], limit: int | None, compact: bool, **options):
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    values = _params(params)
    prj = load_project(**options)
    _answer(lambda: query.drivers(prj, path, params=values, limit=limit), compact)


@cli.command(
    help=f"""What A Signal Drives As JSON.

    {_PATH_HELP}
{_PATHS_HELP}"""
)
@click.argument("path")
@opt_params
@opt_project
@opt_answer
@pass_ctx
def loads(ctx: Ctx, path: str, params: tuple[str, ...], limit: int | None, compact: bool, **options):
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    values = _params(params)
    prj = load_project(**options)
    _answer(lambda: query.loads(prj, path, params=values, limit=limit), compact)


@cli.command(
    help=f"""Shortest Connection From Signal SRC To Signal DST As JSON.

    SRC and DST are instance paths of signals below the same top ('top.u_core.u_alu.result_o').
    The search stops behind flip-flops, unless '--through-regs' is given.
{_PATHS_HELP}"""
)
@click.argument("src")
@click.argument("dst")
@opt_params
@click.option("--through-regs", is_flag=True, help="Continue behind flip-flops.")
@click.option("--data-only", is_flag=True, help="Do not follow conditions, resets and clocks.")
@opt_project
@opt_answer
@pass_ctx
def trace(  # noqa: PLR0913
    ctx: Ctx,
    src: str,
    dst: str,
    params: tuple[str, ...],
    through_regs: bool,
    data_only: bool,
    limit: int | None,
    compact: bool,
    **options,
):
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    values = _params(params)
    prj = load_project(**options)
    _answer(
        lambda: query.trace(
            prj, src, dst, params=values, through_regs=through_regs, control=not data_only, limit=limit
        ),
        compact,
    )


@cli.command(
    help=f"""Serve The Queries As MCP Server On Standard Input And Output.

    The tools are 'module', 'hierarchy', 'where_used', 'find', 'diagnostics', 'elaborate', 'evaluate',
    'drivers', 'loads', 'trace' and 'reload'.
    Files which changed are parsed again on the next query.
{_PATHS_HELP}"""
)
@opt_blackbox
@opt_project
@pass_ctx
def mcp(ctx: Ctx, blackboxes: tuple[str, ...], **options) -> None:
    """See `help`."""  # help is given to the decorator, as it is built from parts
    _quiet(ctx)
    prj = load_project(**options)  # usage errors are reported right away
    serve(lambda: load_project(**options), sys.stdin, sys.stdout, prj, blackboxes=blackboxes)


@cli.command()
def schema() -> None:
    """Print The JSON Schema Of The Document Of 'hdl-parser project'."""
    print(json_.dumps(Project.json_schema(), indent=2))


def _parse_files(  # noqa: PLR0913
    filepaths: tuple[Path, ...],
    filelist: tuple[Path, ...] = (),
    expand_macros: bool = False,
    macro_files: tuple[Path, ...] = (),
    inc_dirs: tuple[Path, ...] = (),
    resolve_ifdefs: bool = False,
) -> Iterator[File]:
    """Parse all files according to the options of `opt_parse`."""
    for option, value in (("--macro-file", macro_files), ("--resolve-ifdefs", resolve_ifdefs)):
        if value and not expand_macros:
            raise click.UsageError(f"'{option}' requires '--expand-macros'.")
    all_filepaths = list(filepaths)
    all_inc_dirs = list(inc_dirs)
    for filelist_path in filelist:
        parse_filelist(all_filepaths, all_inc_dirs, filelist_path)
    macros = parse_defines(*macro_files, inc_dirs=all_inc_dirs, resolve_ifdefs=resolve_ifdefs)
    for filepath in all_filepaths:
        yield parse_file(
            filepath, expand_macros=expand_macros, macros=macros, inc_dirs=all_inc_dirs, resolve_ifdefs=resolve_ifdefs
        )
