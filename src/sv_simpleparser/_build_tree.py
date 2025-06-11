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

import pathlib
from concurrent.futures import ProcessPoolExecutor, as_completed

from anytree import Node, RenderTree
from rich.progress import Progress

from .datamodel import Module
from .parser import parse_file


def _build_tree(
    module_dict: dict[str, Module], top: str, inst_name: str | None = None, parent: Node | None = None
) -> Node:
    """Recursive function used to build tree of modules."""
    # Create node for the current module
    if inst_name:
        current_node = Node(f"{top} ({inst_name})", parent=parent)
    else:
        current_node = Node(f"{top}", parent=parent)

    module = module_dict.get(top)
    if not module:
        return current_node  # No module definition found

    # Recursively create nodes for each instance
    for inst in module.insts:
        inst_node = Node(f"{inst.module} ({inst.name})", parent=current_node)
        _build_tree(module_dict, inst.module, inst.name, parent=inst_node)

    return current_node


def _show_tree(file_path: pathlib.Path, top_name: str):
    # Read the file and extract paths (strip whitespace and skip empty lines)
    with file_path.open("r") as file:
        file_list = [line.strip() for line in file if line.strip()]

    results = []
    with Progress() as progress:
        task = progress.add_task("Processing...", total=len(file_list))

        with ProcessPoolExecutor() as executor:
            futures = {executor.submit(parse_file, file): file for file in file_list}

            for future in as_completed(futures):
                results.append(future.result())
                progress.update(task, advance=1)

    # Create a list with all parsed modules
    all_modules = [module for file in results for module in file.modules]

    # Dictionary key: Module.name, value: Module
    module_dict = {mod.name: mod for mod in all_modules}

    root = _build_tree(module_dict, top=top_name)

    # Display tree
    for pre, _, node in RenderTree(root):
        print(f"{pre}{node.name}")
