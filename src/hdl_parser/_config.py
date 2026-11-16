# MIT License
#
# Copyright (c) 2026 ericsmacedo
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

"""Project Configuration File.

A file `hdl-parser.toml` holds the options which create the project, so they are not repeated on every call:

```toml
filelist = "sim/lint/list.f"
expand_macros = true
resolve_ifdefs = true
closed_world = true
defines = { SYNTHESIS = "", WIDTH = "8" }
cache_dir = "~/.cache/hdl-parser"
blackbox = ["*_cell_*"]
```

It is searched in the current directory and its parents. Paths are relative to the directory of the file.
"""

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

CONFIG_NAME = "hdl-parser.toml"
"""Name of the configuration file."""


class ConfigError(ValueError):
    """Configuration File Is Not Valid."""


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise TypeError("true or false")
    return value


def _int(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise TypeError("an integer")
    return value


def _str(value: Any) -> str:
    if not isinstance(value, str):
        raise TypeError("a string")
    return value


def _strs(value: Any) -> tuple[str, ...]:
    if isinstance(value, str):
        return (value,)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise TypeError("a string or a list of strings")
    return tuple(value)


def _defines(value: Any) -> tuple[str, ...]:
    if not isinstance(value, dict):
        raise TypeError('a table of names and values: { NAME = "VALUE" }')
    for name, val in value.items():
        if isinstance(val, bool) or not isinstance(val, (str, int)):
            raise TypeError(f"a string or an integer as value of '{name}'")
    return tuple(f"{name}={val}" for name, val in value.items())


_PATH = "path"
_PATHS = "paths"

# key: parameter of the command line, conversion
_KEYS: dict[str, tuple[str, Callable[[Any], Any] | str]] = {
    "filelist": ("filelist", _PATH),
    "paths": ("paths", _PATHS),
    "root": ("root", _PATH),
    "exclude": ("exclude", _strs),
    "expand_macros": ("expand_macros", _bool),
    "resolve_ifdefs": ("resolve_ifdefs", _bool),
    "closed_world": ("closed_world", _bool),
    "defines": ("defines", _defines),
    "inc_dirs": ("inc_dirs", _PATHS),
    "cache": ("cache", _bool),
    "cache_dir": ("cache_dir", _PATH),
    "jobs": ("jobs", _int),
    "blackbox": ("blackboxes", _strs),
    "passthrough": ("passthrough", _strs),
    "exclude_problems": ("excludes", _strs),
}
"""Keys of the file."""

KEYS = tuple(_KEYS)
"""Known keys of the configuration file."""


def find_config(start: Path) -> Path | None:
    """The configuration file within `start` or the closest parent directory. `None` if there is none."""
    start = start.absolute()
    for directory in (start, *start.parents):
        path = directory / CONFIG_NAME
        if path.is_file():
            return path
    return None


def read_config(path: Path) -> dict[str, Any]:
    """Read the configuration file at `path`: values by name of the command line parameter.

    Paths are absolute: relative ones are relative to the directory of the file, `~` is expanded.

    Raises:
        ConfigError: the file is not valid.
    """
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from None
    base = path.parent.absolute()

    def to_path(value: Any) -> Path:
        return base / Path(_str(value)).expanduser()

    values: dict[str, Any] = {}
    for key, value in data.items():
        if key not in _KEYS:
            raise ConfigError(f"{path}: unknown key '{key}'. Known: {', '.join(KEYS)}.")
        param, convert = _KEYS[key]
        try:
            if convert == _PATH:
                values[param] = to_path(value)
            elif convert == _PATHS:
                values[param] = tuple(to_path(item) for item in _strs(value))
            else:
                values[param] = convert(value)  # type: ignore[operator]
        except TypeError as exc:
            raise ConfigError(f"{path}: '{key}' must be {exc}.") from None
    if "filelist" in values and "paths" in values:
        raise ConfigError(f"{path}: give either 'filelist' or 'paths'.")
    return values
