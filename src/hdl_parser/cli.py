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

import logging
import sys
from collections.abc import Iterator
from pathlib import Path

import click
from pydantic import BaseModel, ConfigDict
from rich.console import Console
from rich.logging import RichHandler

from ._gen_templates import gen_instance, gen_markdown_table
from .datamodel import File
from .filelistparser import parse_filelist
from .parser import parse_defines, parse_file

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
        if exc_type:
            if exc_type is KeyboardInterrupt:
                self.console.print("[red]Aborted.")
            else:
                self.console.print("[red][bold]Failed.")
            sys.exit(1)


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
            # the context swallows the message
            LOGGER.error("'%s' requires '--expand-macros'.", option)
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
