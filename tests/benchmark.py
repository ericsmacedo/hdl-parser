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
"""Performance regression guard: measure ``parse_text`` relative to stock Pygments.

Absolute timings differ wildly between machines, so the measurement is a **ratio**: the time
:func:`hdl_parser.parse_text` needs for a generated workload divided by the time the stock Pygments
``SystemVerilogLexer`` needs to tokenize the same text in the same process. The reference uses the same regex engine
and Pygments machinery, so machine and interpreter speed mostly cancel out.

The measurement runs in a subprocess without coverage tracing (tracing would slow ``hdl_parser`` much more than
Pygments). ``tests/test_benchmark.py`` uses :func:`measure`. To re-record the baseline run::

    uv run python tests/benchmark.py --update

The baseline is kept per Python ``X.Y`` (falling back to ``default``); use ``--update --default`` for the fallback.
Without ``--update`` the script only prints the measurements.
"""

import argparse
import datetime
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from pygments.lexers import SystemVerilogLexer

from hdl_parser import parse_text

BASELINE_PATH = Path(__file__).with_name("benchmark_baseline.json")
REPEATS = 5


def make_body() -> tuple[str, dict[str, int]]:
    """Large modules: 200 ports, 300 instances and 300 ``always_ff`` blocks each."""
    big = (
        "module m%d #(parameter int W = 8) (\n"
        + "".join(f"  input logic [W-1:0] a{i},  // port {i}\n" for i in range(200))
        + "  output logic q\n);\n"
        + "".join(
            f"  sub u{i} (.clk(a0), .d(a{i}));\n  always_ff @(posedge a0) begin x{i} <= a{i}; end\n" for i in range(300)
        )
        + "endmodule\n"
    )
    text = "".join(big % i for i in range(10))
    return text, {"modules": 10, "ports": 2010, "insts": 3000}


def make_macros() -> tuple[str, dict[str, int]]:
    """Many small modules whose headers use function-like macros."""
    head = (
        "`define CLK_RST_PORTS \\\n"
        "    input  logic clk_i,   /* Clock */ \\\n"
        "    input  logic rst_ni   /* Reset */\n"
        "`define STREAM_PORTS(prefix, dir_req, dir_rsp, width=8) \\\n"
        "    dir_req logic             prefix``_valid, \\\n"
        "    dir_req logic [width-1:0] prefix``_data, \\\n"
        "    dir_rsp logic             prefix``_ready\n"
        "`define WIDTH_PARAM(name, value) parameter int name = value\n"
    )
    mod = (
        "module mm%d #(\n"
        "    `WIDTH_PARAM(IN_WIDTH, 16),\n"
        "    `WIDTH_PARAM(OUT_WIDTH, 8)\n"
        ") (\n"
        "    `CLK_RST_PORTS,\n"
        "    `STREAM_PORTS(in, input, output, IN_WIDTH),\n"
        "    `STREAM_PORTS(out, output, input),\n"
        "    output logic busy_o // Busy\n"
        ");\n"
        "  sub u0 (.clk(clk_i), .d(in_data));\n"
        "endmodule\n"
    )
    n = 400
    return head + "".join(mod % i for i in range(n)), {"modules": n, "ports": 9 * n, "insts": n, "params": 2 * n}


WORKLOADS = {"body": make_body, "macros": make_macros}


def _best(func, repeats: int) -> float:
    func()  # warm up
    best = float("inf")
    for _ in range(repeats):
        start = time.perf_counter()
        func()
        best = min(best, time.perf_counter() - start)
    return best


def _check(name: str, file, expected: dict[str, int]) -> None:
    mods = file.modules
    got = {
        "modules": len(mods),
        "ports": sum(len(m.ports) for m in mods),
        "insts": sum(len(m.insts) for m in mods),
        "params": sum(len(m.params) for m in mods),
    }
    for key, value in expected.items():
        if got[key] != value:
            raise AssertionError(f"workload {name!r}: expected {value} {key}, parsed {got[key]}")


def worker() -> dict:
    """Run all measurements in this process and return the results."""
    if sys.gettrace() is not None or (getattr(sys, "monitoring", None) and _monitoring_active()):
        raise RuntimeError("tracing/coverage is active in the benchmark worker; the measurement would be meaningless")
    lexer = SystemVerilogLexer()
    results = {}
    for name, make in WORKLOADS.items():
        text, expected = make()
        _check(name, parse_text(text), expected)
        lines = text.count("\n")
        parser_s = _best(lambda t=text: parse_text(t), REPEATS)
        ref_s = _best(lambda t=text: list(lexer.get_tokens_unprocessed(t)), REPEATS)
        results[name] = {
            "parser_s": parser_s,
            "reference_s": ref_s,
            "ratio": parser_s / ref_s,
            "lines": lines,
            "klines_per_s": lines / parser_s / 1000,
        }
    return results


def _monitoring_active() -> bool:
    """Whether any ``sys.monitoring`` tool (Python 3.12+) is registered, e.g. coverage."""
    return any(sys.monitoring.get_tool(tool_id) is not None for tool_id in range(6))


def measure() -> dict:
    """Run the worker in a clean subprocess (no coverage) and return its results."""
    env = {k: v for k, v in os.environ.items() if not k.startswith("COV_CORE_") and k != "COVERAGE_PROCESS_START"}
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve()), "--worker"],
        capture_output=True,
        text=True,
        env=env,
        check=False,
        timeout=300,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"benchmark worker failed ({proc.returncode}):\n{proc.stdout}\n{proc.stderr}")
    return json.loads(proc.stdout)


def _describe() -> str:
    try:
        out = subprocess.run(
            ["git", "describe", "--always", "--dirty"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent,
            check=False,
        )
        return out.stdout.strip() or "unknown"
    except OSError:
        return "unknown"


def load_baseline() -> dict:
    """Return the baseline workloads for this interpreter: its ``X.Y`` entry, else ``default``."""
    entries = json.loads(BASELINE_PATH.read_text())["entries"]
    return entries.get(f"{sys.version_info.major}.{sys.version_info.minor}", entries["default"])["workloads"]


def update_baseline(*, default: bool = False) -> dict:
    """Measure (best of three runs per workload) and store the baseline for this Python version.

    The entry is stored under ``default`` when `default` is set, else under the running ``X.Y`` version.
    """
    runs = [measure() for _ in range(3)]
    workloads = {}
    for name in WORKLOADS:
        best = min((run[name] for run in runs), key=lambda r: r["ratio"])
        workloads[name] = {"ratio": round(best["ratio"], 3), "lines": best["lines"]}
    entry = {
        "date": datetime.date.today().isoformat(),
        "python": platform.python_version(),
        "platform": platform.platform(),
        "hdl_parser": _describe(),
        "workloads": workloads,
    }
    data = json.loads(BASELINE_PATH.read_text()) if BASELINE_PATH.exists() else {"entries": {}}
    data["entries"]["default" if default else f"{sys.version_info.major}.{sys.version_info.minor}"] = entry
    data["note"] = "ratio = parse_text time / stock Pygments SystemVerilogLexer time; best of 3 subprocess runs"
    BASELINE_PATH.write_text(json.dumps(data, indent=2) + "\n")
    return data


def main() -> None:
    """Command line entry point."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--worker", action="store_true", help="internal: run the measurement and print JSON")
    parser.add_argument("--update", action="store_true", help="re-record the baseline of this Python version")
    parser.add_argument("--default", action="store_true", help="with --update: record the fallback `default` entry")
    args = parser.parse_args()
    if args.worker:
        print(json.dumps(worker()))
    elif args.update:
        print(json.dumps(update_baseline(default=args.default), indent=2))
    else:
        print(json.dumps(measure(), indent=2))


if __name__ == "__main__":
    main()
