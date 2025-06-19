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

from importlib.resources import files

from jinja2 import Environment, FileSystemLoader
from rich.table import Table, box

from .datamodel import Module

template_path = files("hdl_parser.Templates")


def escape_brackets(s):
    return s.replace("[", r"\[") if s else "1"


def gen_instance(mod):
    port_lst = [port.name for port in mod.ports]
    param_lst = [param.name for param in mod.params]

    environment = Environment(loader=FileSystemLoader(template_path))

    if param_lst:
        inst_temp = environment.get_template("instance_with_param_template")

        instance_file = inst_temp.render(module_name=mod.name, param_list=param_lst, port_list=port_lst)
    else:
        inst_temp = environment.get_template("instance_template")

        instance_file = inst_temp.render(module_name=mod.name, port_list=port_lst)

    return instance_file


def gen_markdown_table(module: Module, width: int | None = None) -> tuple[Table | None, Table | None, Table | None]:
    if module.params:
        params = Table(box=box.MARKDOWN, width=width)

        params.add_column("Name", no_wrap=True)
        params.add_column("Dimension", no_wrap=True)
        params.add_column("Default", no_wrap=True)
        params.add_column("Functional Description")

        for param in module.params:
            param_name = f"{param.name} {param.dim_unpacked}" if param.dim_unpacked else param.name
            dim = f"`{escape_brackets(param.dim)}`" if param.dim else ""
            default = f"`{param.default}`" if param.default else ""
            params.add_row(f"`{param_name}`", dim, default, "\n".join(param.comment or ()))
    else:
        params = None

    if module.ports:
        ports = Table(box=box.MARKDOWN, width=width)

        ports.add_column("Name", no_wrap=True)
        ports.add_column("Dimension", no_wrap=True)
        ports.add_column("I/O", no_wrap=True)
        ports.add_column("Functional Description")

        for port in module.ports:
            dim = escape_brackets(port.dim) if port.dim else "1"
            port_name = f"{port.name} {port.dim_unpacked}" if port.dim_unpacked else port.name
            ports.add_row(f"`{port_name}`", f"`{dim}`", f"`{port.direction}`", "\n".join(port.comment or ()))
    else:
        ports = None

    if module.insts:
        insts = Table(box=box.MARKDOWN, width=width)

        insts.add_column("Name", no_wrap=True)
        insts.add_column("Module", no_wrap=True)

        for inst in module.insts:
            insts.add_row(f"`{inst.name}`", f"`{inst.module}`")
    else:
        insts = None

    return params, ports, insts
