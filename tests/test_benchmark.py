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
"""Performance regression guard. See `tests/benchmark.py` for what is measured and how to re-record the baseline."""

from . import benchmark

THRESHOLD = 1.5
IMPROVED = 0.7
RETRIES = 2


def test_parser_speed():
    """Parsing must not become more than 50% slower than the recorded baseline (relative to stock Pygments)."""
    baseline = benchmark.load_baseline()
    best: dict[str, dict] = {}
    for _ in range(1 + RETRIES):
        for name, result in benchmark.measure().items():
            if name not in best or result["ratio"] < best[name]["ratio"]:
                best[name] = result
        if all(best[name]["ratio"] <= baseline[name]["ratio"] * THRESHOLD for name in baseline):
            break

    assert set(best) == set(baseline), "workloads and tests/benchmark_baseline.json are out of sync"
    failures = []
    for name, base in baseline.items():
        result = best[name]
        limit = base["ratio"] * THRESHOLD
        if result["ratio"] > limit:
            failures.append(
                f"{name}: parse/pygments ratio {result['ratio']:.2f} vs baseline {base['ratio']:.2f} "
                f"(limit {limit:.2f}, {result['ratio'] / base['ratio']:.2f}x), {result['klines_per_s']:.1f} k-lines/s"
            )
        elif result["ratio"] < base["ratio"] * IMPROVED:
            print(
                f"\nHint: {name} ratio {result['ratio']:.2f} is much better than the baseline {base['ratio']:.2f}; "
                "re-record with `uv run python tests/benchmark.py --update` to keep the guard tight."
            )
    assert not failures, (
        "Parser performance regression:\n  "
        + "\n  ".join(failures)
        + "\nIf the slowdown is intended, re-record the baseline with `uv run python tests/benchmark.py --update`."
    )
