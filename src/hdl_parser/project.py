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

"""Project: All Files Of A Design As One Model.

A [Project][hdl_parser.project.Project] is created from files, a filelist or a directory:

* [Project.from_files][hdl_parser.project.Project.from_files]
* [Project.from_filelist][hdl_parser.project.Project.from_filelist]
* [Project.from_dir][hdl_parser.project.Project.from_dir]

It answers questions about the design, instead of single files:

* Which file defines a module, interface or package? [definitions][hdl_parser.project.Project.definitions],
  [resolve][hdl_parser.project.Project.resolve]
* What is instantiated below a module? [hierarchy][hdl_parser.project.Project.hierarchy]
* Which modules are instantiated nowhere? [tops][hdl_parser.project.Project.tops]
* Where is a module instantiated? [where_used][hdl_parser.project.Project.where_used]
* What is the item with this identifier? [find][hdl_parser.project.Project.find]
* What drives a signal, what does it drive, how is it connected to another one?
  [drivers][hdl_parser.project.Project.drivers], [loads][hdl_parser.project.Project.loads],
  [trace][hdl_parser.project.Project.trace]

A file which cannot be read or parsed never stops the others: it is part of the project, with a diagnostic.
"""

import gc
import hashlib
import json
import logging
import os
import re
from collections.abc import Iterable, Iterator, Mapping
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from fnmatch import fnmatch
from functools import cache, cached_property
from pathlib import Path
from typing import Any, NamedTuple

from . import datamodel as dm
from ._conn import Connectivity, Graph, Node
from ._diagnostics import Diagnostics, log_diagnostic, silent
from ._elab import Elaboration
from ._sv.preproc import RE_DEFINE_NAME, defined_names
from .filelistparser import DEFAULT_LIB_EXTS, read_filelist
from .parser import LANGMAP, Macros, parse_defines_text, parse_file

SCHEMA_VERSION = 1
"""Version of the JSON document of a project. Incremented on changes, which are not backward compatible."""

LOGGER = logging.getLogger(__name__)

MIN_FILES_PER_JOB = 8
"""Number of files a process has to parse at least: starting a process for less takes longer than parsing them."""

CACHE_DIR = ".hdl_parser_cache"
"""Name of the cache directory within the root of a project."""

Unit = dm.Module | dm.Package
"""Module, Interface Or Package."""


class Definition(NamedTuple):
    """Module, Interface Or Package With The File It Is Defined In.

    Attributes:
        file: File.
        unit: Module, interface or package.
        bodies: VHDL: architectures of the entity `unit`, which are located in other files.
    """

    file: dm.File
    unit: Unit
    bodies: tuple[tuple[dm.File, dm.Module], ...] = ()

    @property
    def id(self) -> str:
        """Full identifier: `rtl/top.sv:top`."""
        return self.file.full_id(self.unit)

    @property
    def insts(self) -> Iterator[tuple[dm.File, dm.ModuleInstance]]:
        """Instances within the module, with the file they are located in."""
        if isinstance(self.unit, dm.Module):
            for file, module in ((self.file, self.unit), *self.bodies):
                for inst in module.insts:
                    yield file, inst


class _Index:
    """Modules And Interfaces, Or Packages, By Name. The definition to be used is the first one of a name.

    SystemVerilog names are case sensitive. VHDL names are not.
    """

    def __init__(self) -> None:
        self.sv: dict[str, list[Definition]] = {}
        self.sv_lower: dict[str, list[Definition]] = {}
        self.vhdl: dict[str, list[Definition]] = {}

    def add(self, definition: Definition) -> None:
        name = definition.unit.name
        if definition.file.lang == "vhdl":
            self.vhdl.setdefault(name.lower(), []).append(definition)
        else:
            self.sv.setdefault(name, []).append(definition)
            self.sv_lower.setdefault(name.lower(), []).append(definition)

    def get(self, name: str, casefold: bool = False) -> list[Definition]:
        """Definitions of `name`. `casefold`: `name` is used by VHDL, so it is not case sensitive."""
        lower = name.lower()
        sv = self.sv_lower.get(lower, []) if casefold else self.sv.get(name, [])
        return [*sv, *self.vhdl.get(lower, [])]

    def groups(self) -> Iterator[list[Definition]]:
        """All definitions, grouped by name."""
        yield from self.sv.values()
        yield from self.vhdl.values()

    def sort(self, key) -> None:
        for definitions in (*self.sv.values(), *self.sv_lower.values(), *self.vhdl.values()):
            definitions.sort(key=key)


class Project(dm._BaseModel):
    """All Files Of A Design.

    The paths of the files, and therefore the full identifiers of all items, are relative to `root`.
    A file which is located elsewhere starts with `../`.

    A module, interface or package may be defined more than once, i.e. as RTL and as simulation model.
    All definitions are kept and reported (`duplicate-definition`). The one used by
    [resolve][hdl_parser.project.Project.resolve] and the hierarchy is

    1. the one of the file named by `prefer`,
    2. one of a file given directly, before one found through a library option of a filelist,
    3. the first one, in the order of the files.

    The full identifier (`models/fifo.sv:fifo`) always addresses one definition exactly.

    Attributes:
        schema_version: Version of this document.
        root: Root directory of the project.
        settings: How the files are parsed.
        files: Files, in the given order.
        libraries: Paths of the files, which have been found through a library option of a filelist.
        prefer: File to be used for a module, interface or package which is defined more than once, by name.
        diagnostics: Problems which are not related to one of the files, i.e. of a filelist. Located within their
                     `file`, the filelist. The problems of a file are located in its `diagnostics`.
    """

    schema_version: int
    root: Path
    settings: dm.Settings = dm.Settings()
    files: tuple[dm.File, ...] = ()
    libraries: tuple[str, ...] = ()
    prefer: dict[str, str] = {}
    diagnostics: tuple[dm.Diagnostic, ...] = ()

    # --- creation ---

    @classmethod
    def from_files(  # noqa: PLR0913
        cls,
        file_paths: Iterable[Path | str],
        root: Path | str | None = None,
        expand_macros: bool = False,
        resolve_ifdefs: bool = False,
        closed_world: bool = False,
        defines: dict[str, str] | None = None,
        inc_dirs: Iterable[Path | str] = (),
        prefer: dict[str, str] | None = None,
        cache: bool | Path | str = False,
        jobs: int | None = 1,
    ) -> "Project":
        """Create project from files.

        Args:
            file_paths: Paths to the files.

        Keyword Args:
            root: Root directory. The common directory of all files by default.
            expand_macros: Expand macros with known definition.
            resolve_ifdefs: Resolve `` `ifdef `` conditions on macros which are known to be defined.
            closed_world: Resolve `` `ifdef `` conditions on macros which are never defined too - neither by
                          `defines`, nor by any file of the project or a file it includes: these macros are
                          undefined, like for a compiler. Requires `resolve_ifdefs`.
            defines: Macros defined for all files, by name: `{"SYNTHESIS": "", "WIDTH": "8"}`.
                     Used by `expand_macros` only.
            inc_dirs: Include directories. Used by `expand_macros` only.
            prefer: File to be used for a module, interface or package which is defined more than once, by name:
                    `{"fifo": "rtl/fifo.sv"}`.
            cache: Keep the result of every file, and parse a file again only if it changed: the file itself,
                   a file it includes, or how it is parsed. `True` uses the directory `.hdl_parser_cache` within
                   the root of the project, a path any other directory.
            jobs: Number of processes parsing the files. `None` for one per CPU. The result is the same for any
                  number. More than one process requires the calling script to be importable without side
                  effects (`if __name__ == "__main__":`), and pays off for many files only: a few files are
                  always parsed by this process.
        """
        settings = dm.Settings(
            expand_macros=expand_macros, resolve_ifdefs=resolve_ifdefs, closed_world=closed_world, defines=defines or {}
        )
        builder = _Builder(cls, root, settings, map(Path, inc_dirs), prefer, cache, jobs)
        return builder.build(map(Path, file_paths))

    @classmethod
    def from_filelist(  # noqa: PLR0913
        cls,
        filelist_path: Path | str,
        root: Path | str | None = None,
        env: Mapping[str, str] | None = None,
        expand_macros: bool = False,
        resolve_ifdefs: bool = False,
        closed_world: bool = False,
        defines: dict[str, str] | None = None,
        inc_dirs: Iterable[Path | str] = (),
        prefer: dict[str, str] | None = None,
        cache: bool | Path | str = False,
        jobs: int | None = 1,
    ) -> "Project":
        """Create project from a filelist: its files, include directories, macros and libraries.

        See [hdl_parser.filelistparser][] for the format. What is not understood is reported in `diagnostics`.

        A module which is not defined by the files is searched for in the library directories of the filelist
        (`-y`), as `<directory>/<module><extension>`. Library files (`-v`) and the files found this way are
        listed in `libraries`: their modules are used, if they are not defined by another file.

        Args:
            filelist_path: Path to the filelist.

        Keyword Args:
            root: Root directory. The common directory of all files by default.
            env: Environment variables used by the filelist. The ones of the process by default.
            expand_macros: Expand macros with known definition.
            resolve_ifdefs: Resolve `` `ifdef `` conditions on macros which are known to be defined.
            closed_world: See [from_files][hdl_parser.project.Project.from_files].
            defines: Macros defined for all files, in addition to the ones of the filelist.
            inc_dirs: Include directories, in addition to the ones of the filelist.
            prefer: See [from_files][hdl_parser.project.Project.from_files].
            cache: See [from_files][hdl_parser.project.Project.from_files].
            jobs: See [from_files][hdl_parser.project.Project.from_files].
        """
        filelist = read_filelist(filelist_path, env=env)
        settings = dm.Settings(
            expand_macros=expand_macros,
            resolve_ifdefs=resolve_ifdefs,
            closed_world=closed_world,
            defines={**filelist.defines, **(defines or {})},
            lib_exts=tuple(filelist.lib_exts) or DEFAULT_LIB_EXTS,
        )
        builder = _Builder(cls, root, settings, (*filelist.inc_dirs, *map(Path, inc_dirs)), prefer, cache, jobs)
        return builder.build(filelist.files, filelist.lib_files, filelist.lib_dirs, filelist.diagnostics)

    @classmethod
    def from_dir(cls, dir_path: Path | str, exclude: Iterable[str] = (), **kwargs: Any) -> "Project":
        """Create project from all SystemVerilog and VHDL files below a directory. It is the root of the project.

        Hidden directories (`.git`, ...) are skipped.

        Args:
            dir_path: Path to the directory.

        Keyword Args:
            exclude: Files to be left out, as patterns on their path relative to the directory:
                     `models/*`, `*_tb.sv`. `*` matches `/` too.
            kwargs: See [from_files][hdl_parser.project.Project.from_files].
        """
        root = Path(dir_path)
        patterns = tuple(exclude)
        file_paths = []
        for file_path in sorted(root.rglob("*")):
            rel = file_path.relative_to(root)
            if file_path.suffix not in LANGMAP or any(part.startswith(".") for part in rel.parts):
                continue
            if not any(fnmatch(rel.as_posix(), pattern) for pattern in patterns) and file_path.is_file():
                file_paths.append(file_path)
        return cls.from_files(file_paths, root=root, **kwargs)

    @classmethod
    def json_schema(cls) -> dict[str, Any]:
        """JSON Schema of the JSON document of a project (`overview`).

        It is published as `schema/project.schema.json` with the documentation.
        """
        schema = cls.model_json_schema(mode="serialization")
        return {"$schema": "https://json-schema.org/draft/2020-12/schema", **schema}

    # --- files and items ---

    @cached_property
    def _files(self) -> dict[str, dm.File]:
        return {file.file_id: file for file in self.files}

    @cached_property
    def _file_order(self) -> dict[str, int]:
        return {file.file_id: number for number, file in enumerate(self.files)}

    @cached_property
    def _items(self) -> dict[str, dm.Item]:
        return {file.full_id(item): item for file in self.files for item in file.iter_items()}

    def file(self, path: Path | str) -> dm.File | None:
        """File with `path`, relative to the root of the project. `None` if it is not part of the project."""
        return self._files.get(Path(path).as_posix())

    def find(self, id_: str) -> dm.Item | None:
        """Item with the full identifier `id_` (`rtl/top.sv:top.u_sub`). `None` if not found."""
        return self._items.get(id_)

    def iter_diagnostics(self) -> Iterator[tuple[str, dm.Diagnostic]]:
        """All problems of the project and its files, with the path of the file (empty for the project itself)."""
        for diagnostic in self.diagnostics:
            yield "", diagnostic
        for file in self.files:
            for diagnostic in file.diagnostics:
                yield file.file_id, diagnostic

    # --- definitions ---

    def _order(self, definition: Definition) -> tuple[bool, bool, int]:
        """Sort key: the definition to be used first."""
        file_id = definition.file.file_id
        name = definition.unit.name
        preferred = self.prefer.get(name) or self.prefer.get(name.lower())
        return preferred != file_id, file_id in self.libraries, self._file_order[file_id]

    @cached_property
    def _modules(self) -> _Index:
        """Modules and interfaces."""
        index = _Index()
        # VHDL: the architectures of an entity may be located in other files
        bodies: dict[str, list[tuple[dm.File, dm.Module]]] = {}
        for file in self.files:
            for module in (*file.modules, *file.interfaces):
                if module.partial:
                    bodies.setdefault(module.name.lower(), []).append((file, module))
                else:
                    index.add(Definition(file, module))
        index.sort(self._order)
        for name, modules in bodies.items():
            entities = index.vhdl.get(name)
            if entities:
                entities[0] = entities[0]._replace(bodies=tuple(modules))
            else:
                # no entity: the first architecture stands for the module
                (file, module), *others = modules
                index.vhdl[name] = [Definition(file, module, tuple(others))]
        return index

    @cached_property
    def _packages(self) -> _Index:
        index = _Index()
        for file in self.files:
            for package in file.packages:
                index.add(Definition(file, package))
        index.sort(self._order)
        return index

    def definitions(self, name: str) -> tuple[Definition, ...]:
        """All modules, interfaces and packages named `name`. The ones to be used first.

        `name` is case sensitive. If there is no such name, it is not.
        """
        for casefold in (False, True):
            found = (*self._modules.get(name, casefold), *self._packages.get(name, casefold))
            if found:
                return found
        return ()

    def resolve(self, name: str, casefold: bool = False) -> Definition | None:
        """The module or interface named `name`, as it is used by instances. `None` if there is none.

        `name` may be a full identifier (`rtl/top.sv:top`) too.
        `casefold`: `name` is not case sensitive, as it is used by VHDL. VHDL modules are never case sensitive.
        """
        if ":" in name:
            unit = self.find(name)
            for definition in self._all_modules:
                # VHDL: an architecture located in another file stands for its entity
                if definition.unit is unit or any(module is unit for _, module in definition.bodies):
                    return definition
            return None
        found = self._modules.get(name, casefold)
        return found[0] if found else None

    def resolve_package(self, name: str, casefold: bool = False) -> Definition | None:
        """The package named `name`. `None` if there is none. See [resolve][hdl_parser.project.Project.resolve]."""
        found = self._packages.get(name, casefold)
        return found[0] if found else None

    @cached_property
    def _all_modules(self) -> tuple[Definition, ...]:
        """All modules and interfaces."""
        return tuple(definition for group in self._modules.groups() for definition in group)

    # --- hierarchy ---

    def _resolve_inst(self, file: dm.File, inst: dm.ModuleInstance) -> Definition | None:
        return self.resolve(inst.module, casefold=file.lang == "vhdl")

    @cached_property
    def _uses(self) -> dict[str, list[dm.Use]]:
        """Instances of all modules, by the full identifier of the module."""
        uses: dict[str, list[dm.Use]] = {}
        for parent in self._all_modules:
            for file, inst in parent.insts:
                definition = self._resolve_inst(file, inst)
                if definition:
                    use = dm.Use(inst=file.full_id(inst), module=parent.id, loc=inst.loc)
                    uses.setdefault(definition.id, []).append(use)
        return uses

    @cached_property
    def _undefined(self) -> tuple[tuple[dm.File, dm.ModuleInstance], ...]:
        """Instances of modules which are not defined, with their file."""
        return tuple(
            (file, inst)
            for parent in self._all_modules
            for file, inst in parent.insts
            if self._resolve_inst(file, inst) is None
        )

    def where_used(self, name: str) -> tuple[dm.Use, ...]:
        """All instances of the module or interface `name` (a name, or a full identifier).

        A name stands for the definition, which is used by instances. The result is in the order of the files.
        """
        definition = self.resolve(name) or self.resolve(name, casefold=True)
        return tuple(self._uses.get(definition.id, ())) if definition else ()

    def tops(self) -> tuple[Definition, ...]:
        """Modules which are instantiated nowhere, in the order of the files. Interfaces are no tops."""
        tops = [
            definition
            for definition in self._all_modules
            if not isinstance(definition.unit, dm.Interface) and definition.id not in self._uses
        ]
        return tuple(sorted(tops, key=lambda definition: self._file_order[definition.file.file_id]))

    def hierarchy(self, top: str, depth: int | None = None) -> dm.HierarchyNode | None:
        """Instance tree below the module `top` (a name, or a full identifier). `None` if there is no such module.

        `depth`: Number of instance levels below the top. Everything by default.
        The instances of a node which are left out are marked by `truncated`.
        """
        definition = self.resolve(top) or self.resolve(top, casefold=True)
        if definition is None:
            return None
        children, truncated = self._children(definition, depth, (definition.id,))
        return dm.HierarchyNode(
            name=definition.unit.name,
            module=definition.unit.name,
            definition=definition.id,
            children=children,
            truncated=truncated,
        )

    def elaborate(
        self, top: str, params: Mapping[str, int | float | str | bool] | None = None, depth: int | None = None
    ) -> dm.HierarchyNode | None:
        """Instance tree below the module `top`, with the values of all parameters and the size of all ports.

        Like [hierarchy][hdl_parser.project.Project.hierarchy], but every node has

        * `params`: the values of its parameters and local parameters, with the values given by its instance
          (`#(.WIDTH(8))`, `generic map (WIDTH => 8)`) applied down the hierarchy,
        * `ports`: the number of bits of its ports.

        Names are resolved across files: parameters, local parameters, members of enumerations, and the
        packages which are imported or named (`pkg::WIDTH`).

        Nothing is ever guessed. What cannot be evaluated for sure has no value, but the reason: a function call,
        a name without known value, a package which is not part of the project, ...

        Args:
            top: Name or full identifier of the module.

        Keyword Args:
            params: Values of the parameters of the top, by name. Its defaults are used otherwise.
            depth: Number of instance levels below the top. Everything by default.
        """
        definition = self.resolve(top) or self.resolve(top, casefold=True)
        if definition is None:
            return None
        elaboration = Elaboration(self)
        scope = elaboration.scope(definition, elaboration.top_overrides(params))
        return elaboration.node(scope, definition.unit.name, "", False, depth, (definition.id,))

    def evaluate(self, expr: str, scope: str, params: Mapping[str, int | float | str | bool] | None = None) -> dm.Value:
        """Value of the expression `expr` within the module, interface or package `scope` (a name or full identifier).

        `params`: Values of the parameters of `scope`, by name. Its defaults are used otherwise.
        An expression which cannot be evaluated for sure has no value, but the reason.
        """
        definition = self.resolve(scope) or self.resolve(scope, casefold=True) or self.resolve_package(scope)
        definition = definition or self.resolve_package(scope, casefold=True)
        if definition is None:
            return dm.Value(expr=expr, unknown=f"'{scope}' is not defined in the project")
        elaboration = Elaboration(self)
        return elaboration.scope(definition, elaboration.top_overrides(params)).value_of(expr)

    # --- connectivity ---

    @cached_property
    def _graphs(self) -> dict[str, Graph]:
        return {}

    def _graph(self, definition: Definition) -> Graph:
        """Net graph of the module `definition`. Created on first use."""
        graph = self._graphs.get(definition.id)
        if graph is None:
            graph = self._graphs[definition.id] = Graph(self, definition)
        return graph

    def _connectivity(
        self, params: Mapping[str, int | float | str | bool] | None, passthrough: Iterable[str] = ()
    ) -> Connectivity:
        return Connectivity(self, Elaboration(self).top_overrides(params), passthrough)

    def drivers(
        self,
        path: str,
        params: Mapping[str, int | float | str | bool] | None = None,
        passthrough: Iterable[str] = (),
    ) -> tuple[dm.Link, ...]:
        """What drives the signal with the instance path `path` (`top.u_core.u_alu.result_o`).

        The drivers are the assignments of the signal and the output ports of instances it is connected to.
        An input port is driven by the connection within the parent, or from outside of the design (the top).
        Every driver has the signals it reads (`nets`): ask for their drivers, to go further.

        The path starts with the top module (a name or full identifier), followed by the names of the instances
        (with the labels of the generate blocks around) and the signal. A generate
        construct is left out, if its condition is false for the parameter values (`params` of the top, defaults
        otherwise). Labeled `for` generate constructs are unrolled: `top.g_st[1].data` is the signal of the
        second iteration, the index is checked. Without index (`top.g_st.data`), a path stands for all iterations
        (`multiple`). Instance arrays are not unrolled.

        `passthrough`: Cells which pass their inputs on to their outputs: `buf_wrap`, `BUFX2:A->Y`
        (the ports are needed for modules, which are not defined). See [Link][hdl_parser.datamodel.Link].

        Raises:
            ValueError: The path does not exist.
        """
        conn = self._connectivity(params, passthrough)
        node = conn.locate(path)
        return tuple(conn.link(node, step, driver=True) for step in conn.drivers(node))

    def loads(
        self,
        path: str,
        params: Mapping[str, int | float | str | bool] | None = None,
        passthrough: Iterable[str] = (),
    ) -> tuple[dm.Link, ...]:
        """What the signal with the instance path `path` drives. See [drivers][hdl_parser.project.Project.drivers].

        The loads are the assignments reading the signal, also by a condition (`control`), and the input ports of
        instances it is connected to. An output port is loaded by the connection within the parent.

        Raises:
            ValueError: The path does not exist.
        """
        conn = self._connectivity(params, passthrough)
        node = conn.locate(path)
        return tuple(conn.link(node, step, driver=False) for step in conn.loads(node))

    def trace(  # noqa: PLR0913
        self,
        src: str,
        dst: str,
        params: Mapping[str, int | float | str | bool] | None = None,
        through_regs: bool = False,
        control: bool = True,
        passthrough: Iterable[str] = (),
    ) -> tuple[dm.Hop, ...]:
        """Shortest connection from the signal `src` to the signal `dst`, both instance paths below the same top.

        The search follows the loads of the signals: down through the input ports of instances, up through
        output ports. It stops at blackboxes (modules which are not defined) and, by default, behind flip-flops.
        The result starts with `src` and ends with `dst`. It is empty, if there is no connection.

        Args:
            src: Instance path of the signal to start at: `top.u_core.result_o`.
            dst: Instance path of the signal to reach.

        Keyword Args:
            params: Values of the parameters of the top, by name. Its defaults are used otherwise.
            through_regs: Continue behind flip-flops.
            control: Follow conditions (`if (en) y = a;` and `y = en ? a : b;` connect `en` to `y`), resets and
                     clocks too.
            passthrough: Cells which pass their inputs on to their outputs. See
                         [drivers][hdl_parser.project.Project.drivers].

        Raises:
            ValueError: A path does not exist.
        """
        conn = self._connectivity(params, passthrough)
        source: Node = conn.locate(src)
        target: Node = conn.locate(dst)
        return conn.hops(conn.trace(source, target, through_regs=through_regs, control=control))

    def _children(
        self, parent: Definition, depth: int | None, path: tuple[str, ...]
    ) -> tuple[tuple[dm.HierarchyNode, ...], bool]:
        """Instances within `parent`, and whether they are left out. `path`: modules from the top to `parent`."""
        if depth == 0:
            return (), any(True for _ in parent.insts)
        nodes = []
        for file, inst in parent.insts:
            definition = self._resolve_inst(file, inst)
            children: tuple[dm.HierarchyNode, ...] = ()
            truncated = False
            if definition and definition.id in path:
                # the module contains itself
                truncated = True
            elif definition:
                children, truncated = self._children(
                    definition, None if depth is None else depth - 1, (*path, definition.id)
                )
            nodes.append(
                dm.HierarchyNode(
                    name=inst.name,
                    module=inst.module,
                    inst=file.full_id(inst),
                    definition=definition.id if definition else "",
                    multiple=bool(inst.dim) or any(generate.kind == "for" for generate in inst.generates),
                    children=children,
                    truncated=truncated,
                )
            )
        return tuple(nodes), False


# --- creation ---


class _Builder:
    """Parse Files And Create The Project."""

    def __init__(  # noqa: PLR0913
        self,
        cls: type[Project],
        root: Path | str | None,
        settings: dm.Settings,
        inc_dirs: Iterable[Path],
        prefer: dict[str, str] | None,
        cache: bool | Path | str = False,
        jobs: int | None = 1,
    ):
        self.cls = cls
        self.cache_dir = cache
        self.jobs = _cpu_count() if jobs is None else max(jobs, 1)
        self.root = None if root is None else _absolute(Path(root))
        self.settings = settings
        self.inc_dirs = [_absolute(inc_dir) for inc_dir in inc_dirs]
        self.prefer = prefer or {}
        if settings.closed_world and not settings.resolve_ifdefs:
            raise ValueError("'closed_world' requires 'resolve_ifdefs=True'.")
        for name, value in settings.defines.items():
            if not RE_DEFINE_NAME.fullmatch(name):
                raise ValueError(f"'{name}' of 'defines' is no macro name.")
            if "\n" in value:
                raise ValueError(f"value of '{name}' of 'defines' has more than one line.")
        self.macros: Macros | None = None
        # names of the macros defined by the files, for the closed world
        self.maybe_defined: frozenset[str] = frozenset()
        if settings.expand_macros and settings.defines:
            # valid names and values: no problems
            defines = (f"`define {name} {value}\n" for name, value in settings.defines.items())
            self.macros = parse_defines_text(*defines).macros

    def build(
        self,
        file_paths: Iterable[Path],
        lib_files: Iterable[Path] = (),
        lib_dirs: Iterable[Path] = (),
        diagnostics: Iterable[dm.Diagnostic] = (),
    ) -> Project:
        """Create project from `file_paths` and the libraries `lib_files` and `lib_dirs`."""
        paths = list(dict.fromkeys(_absolute(path) for path in file_paths))
        lib_paths = [path for path in dict.fromkeys(_absolute(path) for path in lib_files) if path not in paths]
        dirs = [_absolute(lib_dir) for lib_dir in lib_dirs]
        if self.root is not None:
            root = self.root
        elif paths or lib_paths:
            root = Path(os.path.commonpath([path.parent for path in (*paths, *lib_paths)]))
        else:
            root = Path.cwd()
        settings = self.settings.model_copy(
            update={
                "inc_dirs": tuple(_relative(inc_dir, root) for inc_dir in self.inc_dirs),
                "lib_dirs": tuple(_relative(lib_dir, root) for lib_dir in dirs),
            }
        )
        fields: dict[str, Any] = {
            "schema_version": SCHEMA_VERSION,
            "root": root,
            "settings": settings,
            "prefer": self.prefer,
            "diagnostics": tuple(_relative_file(diagnostic, root) for diagnostic in diagnostics),
        }
        if self.settings.closed_world:
            sv_paths = (path for path in (*paths, *lib_paths) if LANGMAP.get(path.suffix, "sv") == "sv")
            self.maybe_defined = defined_names(sv_paths, self.inc_dirs)
        self.cache = self._create_cache(root)
        files = self._parse(root, (*paths, *lib_paths))
        libraries = [_relative(path, root) for path in lib_paths]
        while True:
            project = self.cls(files=tuple(files), libraries=tuple(libraries), **fields)
            # modules which are not defined are searched for in the library directories
            found = self._search(project, dirs, {*paths, *lib_paths})
            if not found:
                return _link(project)
            lib_paths += found
            files += self._parse(root, found)
            libraries += [_relative(path, root) for path in found]

    def _search(self, project: Project, lib_dirs: list[Path], known: set[Path]) -> list[Path]:
        """Files of the library directories, which define modules `project` does not."""
        found: list[Path] = []
        if not lib_dirs:
            return found
        names = dict.fromkeys(inst.module for file, inst in project._undefined)
        for name in names:
            candidates = (lib_dir / f"{name}{ext}" for lib_dir in lib_dirs for ext in project.settings.lib_exts)
            path = next((path for path in candidates if path.is_file()), None)
            if path and path not in known and path not in found:
                found.append(path)
        return found

    def _create_cache(self, root: Path) -> "_Cache | None":
        if not self.cache_dir:
            return None
        directory = root / CACHE_DIR if self.cache_dir is True else _absolute(Path(self.cache_dir))
        settings = self.settings
        # everything, which has an influence on the result of a file
        how: list[Any] = [
            settings.expand_macros,
            settings.resolve_ifdefs,
            settings.defines,
            [str(path) for path in self.inc_dirs],
        ]
        if settings.closed_world:
            # a file depends on the macros all others define
            names = "\n".join(sorted(self.maybe_defined)).encode()
            how.append(hashlib.sha256(names).hexdigest())
        return _Cache(directory, root, self.inc_dirs, json.dumps(how, sort_keys=True))

    def _parse(self, root: Path, paths: Iterable[Path]) -> list[dm.File]:
        """Parse the files at `paths`, or take them from the cache."""
        files: dict[Path, dm.File | None] = dict.fromkeys(paths)
        if self.cache is not None:
            for path in files:
                files[path] = self.cache.load(path)
        todo = [path for path, file in files.items() if file is None]
        settings = self.settings
        job = _Job(
            root,
            settings.expand_macros,
            settings.resolve_ifdefs,
            self.macros,
            tuple(self.inc_dirs),
            settings.closed_world,
            self.maybe_defined,
        )
        # the garbage collector finds nothing in the many items created, but takes its time to look at them
        collecting = gc.isenabled()
        gc.disable()
        try:
            parsed = self._parse_files(todo, job)
        finally:
            if collecting:
                gc.enable()
        for path, file in zip(todo, parsed, strict=True):
            files[path] = file
            if self.cache is not None:
                self.cache.store(path, file)
        result: list[dm.File] = list(files.values())  # type: ignore[arg-type]
        # parsed or taken from the cache: all are reported, in the order of the files
        for file in result:
            _log(file)
        return result

    def _parse_files(self, paths: list[Path], job: "_Job") -> list[dm.File]:
        """Parse the files at `paths`, by several processes if this pays off."""
        jobs = min(self.jobs, len(paths) // MIN_FILES_PER_JOB)
        if jobs > 1:
            # large files first: the processes are loaded equally. Some files per task: less overhead.
            order = sorted(range(len(paths)), key=lambda idx: _size(paths[idx]), reverse=True)
            chunksize = max(min(len(paths) // (jobs * 8), 16), 1)
            try:
                with ProcessPoolExecutor(jobs, initializer=_init_worker, initargs=(job,)) as pool:
                    parsed = list(pool.map(_work, [paths[idx] for idx in order], chunksize=chunksize))
            except (OSError, ImportError, BrokenProcessPool) as exc:
                # no processes here (sandbox, missing semaphores, ...)
                LOGGER.debug("cannot parse by %d processes (%s): parsing by one.", jobs, exc)
            else:
                return [file for _, file in sorted(zip(order, parsed, strict=True), key=lambda pair: pair[0])]
        return [_parse_file(path, job) for path in paths]


class _Job(NamedTuple):
    """How Files Are Parsed."""

    root: Path
    expand_macros: bool
    resolve_ifdefs: bool
    macros: Macros | None
    inc_dirs: tuple[Path, ...]
    closed_world: bool = False
    maybe_defined: frozenset[str] = frozenset()


def _parse_file(path: Path, job: _Job) -> dm.File:
    """Parse the file at `path`. A file which cannot be read or parsed is a file with a diagnostic.

    Paths are relative to the root. Nothing is logged: see `_log`.
    """
    with silent():
        return _parse_silent(path, job)


def _parse_silent(path: Path, job: _Job) -> dm.File:
    root = job.root
    rel = Path(_relative(path, root))
    try:
        file = parse_file(
            path,
            expand_macros=job.expand_macros,
            macros=job.macros,
            inc_dirs=job.inc_dirs,
            resolve_ifdefs=job.resolve_ifdefs,
            closed_world=job.closed_world,
            maybe_defined=job.maybe_defined,
        )
    except FileNotFoundError:
        return _failed(rel, "file-not-found", "file not found.")
    except (OSError, UnicodeError) as exc:
        return _failed(rel, "file-unreadable", f"cannot read file: {exc}")
    except Exception as exc:
        # never a crash: the other files are still of use
        return _failed(rel, "parse-failed", f"cannot parse file: {type(exc).__name__}: {exc}")
    includes = tuple(_relative(Path(include), root) for include in file.includes)
    diagnostics = tuple(_relative_file(diagnostic, root) for diagnostic in file.diagnostics)
    return file.model_copy(update={"path": rel, "includes": includes, "diagnostics": diagnostics})


def _log(file: dm.File) -> None:
    """Log the diagnostics of `file`, with paths relative to the root. By this process, in the order of the files."""
    for diagnostic in file.diagnostics:
        log_diagnostic(file.file_id, diagnostic)


# --- worker process ---

_WORKER_JOB: _Job | None = None


def _init_worker(job: _Job) -> None:  # pragma: no cover
    global _WORKER_JOB  # noqa: PLW0603
    _WORKER_JOB = job


def _work(path: Path) -> dm.File:  # pragma: no cover
    return _parse_file(path, _WORKER_JOB)  # type: ignore[arg-type]


def _cpu_count() -> int:
    """Number of CPUs this process may use."""
    affinity = getattr(os, "sched_getaffinity", None)  # not on macOS/Windows
    if affinity is not None:
        return len(affinity(0))
    return os.cpu_count() or 1


def _size(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


_RE_QUOTED = re.compile(r"'([^']*)'")


class _Cache:
    """Results Of Files, Kept In `directory`.

    The result of a file is used again, as long as nothing it depends on changed:

    * the file itself and the files it includes, by their content,
    * included files which have not been found: they are still not there,
    * `how` the file is parsed, its path within the project, and the code of the parser.
    """

    def __init__(self, directory: Path, root: Path, inc_dirs: list[Path], how: str):
        self.directory = directory
        self.root = root
        self.inc_dirs = inc_dirs
        self.how = f"{_parser_version()} {SCHEMA_VERSION} {how}"
        self.hashes: dict[Path, str | None] = {}

    def _hash(self, path: Path) -> str | None:
        """Hash of the content of the file at `path`. `None` if it cannot be read."""
        if path not in self.hashes:
            try:
                self.hashes[path] = hashlib.sha256(path.read_bytes()).hexdigest()
            except OSError:
                self.hashes[path] = None
        return self.hashes[path]

    def _entry(self, path: Path) -> Path:
        """Path of the cache entry of the file at `path`."""
        key = hashlib.sha256(f"{_relative(path, self.root)} {self.how}".encode()).hexdigest()
        return self.directory / f"{key}.json"

    @staticmethod
    def _missing(file: dm.File) -> list[str]:
        """Names of the included files, which have not been found."""
        return [
            name
            for diagnostic in file.diagnostics
            if diagnostic.code == "include-not-found"
            for name in _RE_QUOTED.findall(diagnostic.message)[:1]
        ]

    def _is_there(self, name: str, path: Path, file: dm.File) -> bool:
        """The included file `name`, which has not been found, is there now."""
        dirs = [path.parent, *(self.root.joinpath(include).parent for include in file.includes), *self.inc_dirs]
        return any((directory / name).is_file() for directory in dirs)

    def load(self, path: Path) -> dm.File | None:
        """Result of the file at `path`. `None`, if there is none or it is not valid any more."""
        try:
            entry = json.loads(self._entry(path).read_text(encoding="utf-8"))
            file = dm.File.model_validate(entry["file"])
            depends = dict(entry["depends"])
        except (OSError, ValueError, KeyError, TypeError):
            # no entry, or one which is damaged
            return None
        if depends.pop("", None) != self._hash(path):
            return None
        if any(self._hash(self.root.joinpath(include)) != digest for include, digest in depends.items()):
            return None
        if any(self._is_there(name, path, file) for name in self._missing(file)):
            return None
        return file

    def store(self, path: Path, file: dm.File) -> None:
        """Keep the result `file` of the file at `path`. A file which cannot be read is not kept."""
        digest = self._hash(path)
        if digest is None:
            return
        depends = {"": digest, **{include: self._hash(self.root.joinpath(include)) for include in file.includes}}
        entry = {"depends": depends, "file": file.model_dump(mode="json", exclude_defaults=True)}
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            ignore = self.directory / ".gitignore"
            if not ignore.exists():
                ignore.write_text("*\n", encoding="utf-8")
            self._entry(path).write_text(json.dumps(entry), encoding="utf-8")
        except OSError:
            # a cache which cannot be written is no cache
            return


@cache
def _parser_version() -> str:
    """Version of the parser: the hash of its code. Any change of the parser makes all cached results invalid."""
    digest = hashlib.sha256()
    for path in sorted(Path(__file__).parent.rglob("*.py")):
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _relative_file(diagnostic: dm.Diagnostic, root: Path) -> dm.Diagnostic:
    """`diagnostic` with its file relative to `root`."""
    if not diagnostic.file:
        return diagnostic
    return diagnostic.model_copy(update={"file": _relative(_absolute(Path(diagnostic.file)), root)})


def _absolute(path: Path) -> Path:
    """Absolute `path` without `..`. Symbolic links are kept."""
    return Path(os.path.normpath(path.absolute()))


def _relative(path: Path, root: Path) -> str:
    """`path` relative to `root`: `rtl/top.sv`, or `../lib/cells.v` if located elsewhere.

    The result never depends on the current directory. Windows: a path on another drive stays absolute.
    """
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        pass
    try:
        return Path(os.path.relpath(path, root)).as_posix()
    except ValueError:
        return path.as_posix()


def _failed(path: Path, code: str, message: str) -> dm.File:
    diagnostics = Diagnostics(path.as_posix())
    diagnostics.add(code, message)
    lang = "vhdl" if LANGMAP.get(path.suffix) == "vhdl" else "sv"
    return dm.File(path=path, lang=lang, diagnostics=tuple(diagnostics.items))  # type: ignore[arg-type]


def _link(project: Project) -> Project:
    """Report what is found by looking at all files: duplicate definitions and undefined modules."""
    found: dict[str, Diagnostics] = {}

    def report(file: dm.File, code: str, message: str, item: dm.Module | dm.Package | dm.ModuleInstance) -> None:
        diagnostics = found.setdefault(file.file_id, Diagnostics(file.file_id))
        diagnostics.add(code, message, item.loc, item=item.id)

    for index in (project._modules, project._packages):
        for definitions in index.groups():
            used = definitions[0]
            for definition in definitions[1:]:
                kind = "package" if isinstance(definition.unit, dm.Package) else "module"
                message = f"{kind} '{definition.unit.name}' is defined in '{used.file.file_id}' too, which is used."
                report(definition.file, "duplicate-definition", message, definition.unit)
            if len(definitions) > 1:
                kind = "package" if isinstance(used.unit, dm.Package) else "module"
                others = ", ".join(f"'{definition.file.file_id}'" for definition in definitions[1:])
                message = f"{kind} '{used.unit.name}' is defined in {others} too. This one is used."
                report(used.file, "duplicate-definition", message, used.unit)
    for file, inst in project._undefined:
        message = f"module '{inst.module}' of instance '{inst.name}' is not defined in the project."
        report(file, "undefined-module", message, inst)
    if not found:
        return project
    files = tuple(_add_diagnostics(file, found.get(file.file_id)) for file in project.files)
    # a new project: the indices of `project` refer to its files
    fields = {name: getattr(project, name) for name in type(project).model_fields}
    return type(project)(**{**fields, "files": files})


def _add_diagnostics(file: dm.File, diagnostics: Diagnostics | None) -> dm.File:
    if diagnostics is None:
        return file

    def position(diagnostic: dm.Diagnostic) -> tuple[int, int]:
        return (diagnostic.loc.line, diagnostic.loc.col) if diagnostic.loc else (0, 0)

    merged = tuple(sorted((*file.diagnostics, *diagnostics.items), key=position))
    return file.model_copy(update={"diagnostics": merged})
