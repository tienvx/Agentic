"""Deterministic Python project generator.

This is what powers ``agentic``'s offline ``mock`` mode: given requirements and
an architecture it emits a real, importable, tested Python package. It is a
fixture for exercising the *pipeline* (build -> verify -> review -> fix) with
zero API keys — it is not a substitute for a real model.

Every behaviour below is a real implementation with a real test, so the
generated project genuinely passes ``pytest``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field


@dataclass(frozen=True)
class Behaviour:
    key: str
    keywords: tuple[str, ...]
    func: str
    signature: str
    doc: str
    body: str
    test: str
    cli_kind: str = "text"  # text | values | pair | none
    imports: tuple[str, ...] = ()


BEHAVIOURS: tuple[Behaviour, ...] = (
    Behaviour(
        key="normalize_text",
        keywords=("normalize", "normalise", "clean", "slug", "standardi", "sanitiz"),
        func="normalize_text",
        signature="(text: str) -> str",
        doc="Lowercase text and collapse every run of non-alphanumerics into single hyphens.",
        body=(
            "    lowered = text.strip().lower()\n"
            "    return '-'.join(part for part in re.split(r'[^a-z0-9]+', lowered) if part)"
        ),
        test=(
            '    assert normalize_text("  Hello   World! ") == "hello-world"\n'
            '    assert normalize_text("A.B.C") == "a-b-c"\n'
            '    assert normalize_text("") == ""'
        ),
    ),
    Behaviour(
        key="word_count",
        keywords=("word", "count", "tally", "token"),
        func="word_count",
        signature="(text: str) -> int",
        doc="Count whitespace-separated words in text.",
        body="    return len(text.split())",
        test=(
            '    assert word_count("one two three") == 3\n'
            '    assert word_count("   ") == 0\n'
            '    assert word_count("single") == 1'
        ),
    ),
    Behaviour(
        key="total",
        keywords=("sum", "total", "aggregate", "gross"),
        func="total",
        signature="(values: Iterable[float]) -> float",
        doc="Sum an iterable of numbers.",
        body="    return float(sum(values))",
        test="    assert total([1, 2, 3]) == 6.0\n    assert total([]) == 0.0",
        cli_kind="values",
        imports=("from collections.abc import Iterable",),
    ),
    Behaviour(
        key="mean",
        keywords=("average", "mean", "avg"),
        func="mean",
        signature="(values: Iterable[float]) -> float",
        doc="Arithmetic mean; returns 0.0 for an empty iterable.",
        body="    items = list(values)\n    return float(sum(items)) / len(items) if items else 0.0",
        test="    assert mean([2, 4]) == 3.0\n    assert mean([]) == 0.0",
        cli_kind="values",
        imports=("from collections.abc import Iterable",),
    ),
    Behaviour(
        key="unique",
        keywords=("unique", "dedupe", "duplicate", "distinct", "de-dup"),
        func="unique",
        signature="(items: Iterable[T]) -> list[T]",
        doc="Return items with duplicates removed, preserving first-seen order.",
        body=(
            "    seen: set[T] = set()\n"
            "    out: list[T] = []\n"
            "    for item in items:\n"
            "        if item not in seen:\n"
            "            seen.add(item)\n"
            "            out.append(item)\n"
            "    return out"
        ),
        test="    assert unique([1, 1, 2, 3, 3]) == [1, 2, 3]\n    assert unique([]) == []",
        cli_kind="values",
        imports=("from collections.abc import Iterable", "from typing import TypeVar"),
    ),
    Behaviour(
        key="chunk",
        keywords=("chunk", "batch", "page", "paginate", "split"),
        func="chunk",
        signature="(items: Iterable[T], size: int = 3) -> list[list[T]]",
        doc="Split items into consecutive lists of at most ``size`` elements.",
        body=(
            "    if size < 1:\n"
            "        raise ValueError('size must be >= 1')\n"
            "    data = list(items)\n"
            "    return [data[i : i + size] for i in range(0, len(data), size)]"
        ),
        test="    assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]\n    assert chunk([], 2) == []",
        cli_kind="values",
        imports=("from collections.abc import Iterable", "from typing import TypeVar"),
    ),
    Behaviour(
        key="truncate",
        keywords=("truncate", "shorten", "preview", "excerpt", "limit"),
        func="truncate",
        signature="(text: str, limit: int = 80) -> str",
        doc="Shorten text to ``limit`` characters, appending an ellipsis when cut.",
        body=(
            "    if limit < 1:\n"
            "        raise ValueError('limit must be >= 1')\n"
            "    return text if len(text) <= limit else text[: limit - 1].rstrip() + '\\u2026'"
        ),
        test='    assert truncate("abcdefghij", 5) == "abcd\\u2026"\n    assert truncate("short", 80) == "short"',
    ),
    Behaviour(
        key="is_valid_email",
        keywords=("email", "validate", "valid", "verify", "check", "sanity"),
        func="is_valid_email",
        signature="(value: str) -> bool",
        doc="Return True when value looks like an email address.",
        body=(
            "    pattern = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\\.[A-Za-z]{2,}$')\n"
            "    return bool(pattern.match(value.strip()))"
        ),
        test=(
            '    assert is_valid_email("user@example.com") is True\n'
            '    assert is_valid_email("nope") is False\n'
            '    assert is_valid_email("a@b") is False'
        ),
    ),
    Behaviour(
        key="parse_key_value",
        keywords=("parse", "config", "query", "key-value", "kv", "input"),
        func="parse_key_value",
        signature="(text: str) -> dict[str, str]",
        doc="Parse ``a=1&b=2`` style text into a dictionary.",
        body=(
            "    out: dict[str, str] = {}\n"
            "    for pair in text.split('&'):\n"
            "        if '=' not in pair:\n"
            "            continue\n"
            "        key, _, value = pair.partition('=')\n"
            "        if key.strip():\n"
            "            out[key.strip()] = value.strip()\n"
            "    return out"
        ),
        test=(
            '    assert parse_key_value("a=1&b=2") == {"a": "1", "b": "2"}\n'
            '    assert parse_key_value("junk") == {}'
        ),
    ),
    Behaviour(
        key="celsius_to_fahrenheit",
        keywords=("celsius", "fahrenheit", "temperature", "convert", "unit"),
        func="celsius_to_fahrenheit",
        signature="(celsius: float) -> float",
        doc="Convert a Celsius temperature to Fahrenheit.",
        body="    return float(celsius) * 9.0 / 5.0 + 32.0",
        test="    assert celsius_to_fahrenheit(0) == 32.0\n    assert celsius_to_fahrenheit(100) == 212.0",
        cli_kind="values",
    ),
    Behaviour(
        key="format_currency",
        keywords=("currency", "money", "price", "amount", "cost", "cents", "invoice"),
        func="format_currency",
        signature="(cents: int, symbol: str = '$') -> str",
        doc="Format an integer number of cents as a currency string.",
        body=(
            "    sign = '-' if cents < 0 else ''\n"
            "    units, remainder = divmod(abs(int(cents)), 100)\n"
            "    return f'{sign}{symbol}{units:,}.{remainder:02d}'"
        ),
        test=(
            '    assert format_currency(1234) == "$12.34"\n'
            '    assert format_currency(-500) == "-$5.00"\n'
            '    assert format_currency(0) == "$0.00"'
        ),
    ),
    Behaviour(
        key="clamp",
        keywords=("clamp", "bound", "range", "min", "max", "cap"),
        func="clamp",
        signature="(value: float, low: float, high: float) -> float",
        doc="Constrain value to the inclusive range [low, high].",
        body=(
            "    if low > high:\n"
            "        raise ValueError('low must be <= high')\n"
            "    return max(low, min(high, value))"
        ),
        test="    assert clamp(5, 0, 10) == 5\n    assert clamp(-1, 0, 10) == 0\n    assert clamp(99, 0, 10) == 10",
    ),
    Behaviour(
        key="percentage",
        keywords=("percent", "ratio", "share", "rate", "proportion"),
        func="percentage",
        signature="(part: float, whole: float) -> float",
        doc="Express part as a percentage of whole; 0.0 when whole is zero.",
        body="    return 0.0 if whole == 0 else (float(part) / float(whole)) * 100.0",
        test="    assert percentage(1, 4) == 25.0\n    assert percentage(1, 0) == 0.0",
    ),
    Behaviour(
        key="mask_secret",
        keywords=("mask", "redact", "anonym", "secret", "privacy", "hide", "pii"),
        func="mask_secret",
        signature="(value: str, visible: int = 4) -> str",
        doc="Mask all but the last ``visible`` characters of a secret.",
        body=(
            "    if visible < 0:\n"
            "        raise ValueError('visible must be >= 0')\n"
            "    if len(value) <= visible:\n"
            "        return '*' * len(value)\n"
            "    return '*' * (len(value) - visible) + value[-visible:] if visible else '*' * len(value)"
        ),
        test=(
            '    assert mask_secret("supersecret") == "*******cret"\n'
            '    assert mask_secret("ab", 4) == "**"'
        ),
    ),
    Behaviour(
        key="initials",
        keywords=("initial", "name", "person", "user", "display"),
        func="initials",
        signature="(full_name: str) -> str",
        doc="Build up to two uppercase initials from a display name.",
        body=(
            "    parts = [p for p in re.split(r'\\s+', full_name.strip()) if p]\n"
            "    return ''.join(p[0].upper() for p in parts[:2])"
        ),
        test='    assert initials("Ada Lovelace") == "AL"\n    assert initials("madonna") == "M"\n    assert initials("") == ""',
    ),
    Behaviour(
        key="top_k",
        keywords=("top", "leaderboard", "rank", "frequent", "popular", "score"),
        func="top_k",
        signature="(items: Iterable[T], k: int = 3) -> list[tuple[T, int]]",
        doc="Return the ``k`` most frequent items as (item, count) pairs.",
        body=(
            "    counter = Counter(items)\n"
            "    ranked = sorted(counter.items(), key=lambda pair: (-pair[1], str(pair[0])))\n"
            "    return ranked[: max(0, k)]"
        ),
        test=(
            '    assert top_k(["a", "b", "a"], 1) == [("a", 2)]\n'
            '    assert top_k([], 3) == []'
        ),
        cli_kind="values",
        imports=("from collections import Counter", "from collections.abc import Iterable", "from typing import TypeVar"),
    ),
    Behaviour(
        key="running_total",
        keywords=("running", "cumulative", "ledger", "balance", "track", "history", "log"),
        func="running_total",
        signature="(values: Iterable[float]) -> list[float]",
        doc="Cumulative running total of a sequence of numbers.",
        body=(
            "    out: list[float] = []\n"
            "    acc = 0.0\n"
            "    for value in values:\n"
            "        acc += float(value)\n"
            "        out.append(acc)\n"
            "    return out"
        ),
        test="    assert running_total([1, 2, 3]) == [1.0, 3.0, 6.0]\n    assert running_total([]) == []",
        cli_kind="values",
        imports=("from collections.abc import Iterable",),
    ),
    Behaviour(
        key="is_palindrome",
        keywords=("palindrome", "mirror", "reverse"),
        func="is_palindrome",
        signature="(text: str) -> bool",
        doc="True when text reads the same both ways, ignoring case and punctuation.",
        body=(
            "    cleaned = re.sub(r'[^a-z0-9]', '', text.lower())\n"
            "    return cleaned == cleaned[::-1]"
        ),
        test='    assert is_palindrome("A man, a plan, a canal: Panama") is True\n    assert is_palindrome("nope") is False',
    ),
    Behaviour(
        key="sort_by_length",
        keywords=("sort", "order", "arrange", "sequence", "list"),
        func="sort_by_length",
        signature="(items: Iterable[str], reverse: bool = False) -> list[str]",
        doc="Sort strings by length, ties broken alphabetically.",
        body=(
            "    return sorted(items, key=lambda s: (len(s), s), reverse=reverse)"
        ),
        test=(
            '    assert sort_by_length(["bbb", "a", "cc"]) == ["a", "cc", "bbb"]\n'
            '    assert sort_by_length(["a", "b"]) == ["a", "b"]'
        ),
        imports=("from collections.abc import Iterable",),
    ),
)

_FALLBACK = Behaviour(
    key="describe_text",
    keywords=(),
    func="describe_text",
    signature="(text: str) -> dict[str, int]",
    doc="Summarise text as character and word counts.",
    body=(
        "    return {\n"
        "        'characters': len(text),\n"
        "        'characters_stripped': len(text.strip()),\n"
        "        'words': len(text.split()),\n"
        "    }"
    ),
    test=(
        '    assert describe_text("hi there") == {"characters": 8, "characters_stripped": 8, "words": 2}\n'
        '    assert describe_text("")["words"] == 0'
    ),
)


def select_behaviours(texts: list[str], count: int) -> list[Behaviour]:
    """Pick ``count`` distinct behaviours matching the requirement keywords."""
    haystack = " ".join(t.lower() for t in texts)
    chosen: list[Behaviour] = []
    for behaviour in BEHAVIOURS:
        if any(keyword in haystack for keyword in behaviour.keywords):
            chosen.append(behaviour)
        if len(chosen) >= count:
            return dedupe_behaviours(chosen)
    dedupe_behaviours(chosen)
    pool = list(BEHAVIOURS)
    index = 0
    while len(chosen) < count and pool:
        candidate = pool[index % len(pool)]
        if candidate not in chosen:
            chosen.append(candidate)
        index += 1
        if index > len(pool) * 3:
            break
    if not chosen:
        chosen.append(_FALLBACK)
    return chosen


def dedupe_behaviours(behaviours: list[Behaviour]) -> list[Behaviour]:
    seen: set[str] = set()
    out: list[Behaviour] = []
    for behaviour in behaviours:
        if behaviour.key not in seen:
            seen.add(behaviour.key)
            out.append(behaviour)
    return out


# How each behaviour is invoked from the CLI. Keys are behaviour keys; the
# expression may reference args.text, args.values (list[float]) or args.words.
CLI_CALL: dict[str, str] = {
    "total": "core.total(args.values)",
    "mean": "core.mean(args.values)",
    "running_total": "core.running_total(args.values)",
    "unique": "core.unique(args.words)",
    "sort_by_length": "core.sort_by_length(args.words)",
    "top_k": "core.top_k(args.words, k=int(args.k))",
    "chunk": "core.chunk(args.words, size=int(args.size))",
    "truncate": "core.truncate(args.text, limit=int(args.limit))",
    "mask_secret": "core.mask_secret(args.text, visible=int(args.visible))",
    "celsius_to_fahrenheit": "core.celsius_to_fahrenheit(args.values[0])",
    "format_currency": "core.format_currency(int(args.values[0]))",
    "clamp": "core.clamp(args.values[0], args.values[1], args.values[2])",
    "percentage": "core.percentage(args.values[0], args.values[1])",
}

# Extra argparse options per behaviour.
CLI_OPTIONS: dict[str, list[tuple[str, str]]] = {
    "top_k": [("--k", "3")],
    "chunk": [("--size", "3")],
    "truncate": [("--limit", "80")],
    "mask_secret": [("--visible", "4")],
}


def cli_expression(behaviour: "Behaviour") -> str:
    """The Python expression that calls this behaviour from the CLI."""
    explicit = CLI_CALL.get(behaviour.key)
    if explicit:
        return explicit
    if behaviour.cli_kind == "text":
        return f"core.{behaviour.func}(args.text)"
    if behaviour.cli_kind == "values":
        return f"core.{behaviour.func}(args.values[0])"
    return f"core.{behaviour.func}(args.text)"


def cli_arg_kind(behaviour: "Behaviour") -> str:
    """Which argparse positional this behaviour needs."""
    expression = CLI_CALL.get(behaviour.key, "")
    if "args.words" in expression:
        return "words"
    if "args.values" in expression:
        return "numbers"
    return "text"


def python_package(name: str) -> str:
    ident = re.sub(r"[^a-zA-Z0-9]+", "_", name.strip()).strip("_").lower()
    if not ident or not ident.isidentifier():
        ident = "app"
    if ident[0].isdigit():
        ident = f"app_{ident}"
    return ident


def _oneline(text: str, limit: int = 200) -> str:
    """Collapse to a single line safe to embed in a docstring or TOML string."""
    collapsed = " ".join(str(text or "").split())
    collapsed = collapsed.replace('"""', "'").replace("\\", "").replace('"', "'")
    return collapsed[:limit]


@dataclass
class GeneratedProject:
    files: dict[str, str] = field(default_factory=dict)
    behaviours: list[Behaviour] = field(default_factory=list)
    package: str = "app"

    def paths(self) -> list[str]:
        return sorted(self.files)


def render_core(package: str, behaviours: list[Behaviour], summary: str) -> str:
    imports: list[str] = ["from __future__ import annotations", "", "import re"]
    extra = sorted({imp for b in behaviours for imp in b.imports})
    imports.extend(extra)
    typevars = "\nT = TypeVar(\"T\")\n" if any("TypeVar" in imp for imp in extra) else ""
    doc = _oneline(summary) or "generated by agentic."
    parts = [
        f'"""{package} core: {doc}"""\n',
        "\n".join(imports) + "\n",
        typevars,
    ]
    for behaviour in behaviours:
        parts.append(
            f"\n\ndef {behaviour.func}{behaviour.signature}:\n"
            f'    """{behaviour.doc}"""\n{behaviour.body}\n'
        )
    parts.append("\n\n__all__ = [" + ", ".join(f'"{b.func}"' for b in behaviours) + "]\n")
    return "".join(parts)


def render_tests(package: str, behaviours: list[Behaviour]) -> str:
    header = (
        '"""Generated tests: one behavioural check per implemented requirement."""\n\n'
        "from __future__ import annotations\n\n"
        f"from {package}.core import (\n"
        + "".join(f"    {b.func},\n" for b in behaviours)
        + ")\n"
    )
    cases = []
    for behaviour in behaviours:
        cases.append(f"\n\ndef test_{behaviour.func}():\n{behaviour.test}\n")
    return header + "".join(cases) + "\n"


def render_cli(package: str, behaviours: list[Behaviour], title: str) -> str:
    lines = [
        '"""Command line interface."""',
        "",
        "from __future__ import annotations",
        "",
        "import argparse",
        "import sys",
        "",
        "from . import core",
        "",
        "",
        "def build_parser() -> argparse.ArgumentParser:",
        f'    parser = argparse.ArgumentParser(prog="{package}", description="{_oneline(title, 70)}")',
        "    sub = parser.add_subparsers(dest='command', required=True)",
    ]
    for behaviour in behaviours:
        var = f"p_{behaviour.func}"
        kind = cli_arg_kind(behaviour)
        lines.append(f"    {var} = sub.add_parser('{behaviour.func}', help={_oneline(behaviour.doc, 60)!r})")
        if kind == "numbers":
            lines.append(f"    {var}.add_argument('values', nargs='+', type=float)")
        elif kind == "words":
            lines.append(f"    {var}.add_argument('words', nargs='+')")
        else:
            lines.append(f"    {var}.add_argument('text')")
        for flag, default in CLI_OPTIONS.get(behaviour.key, []):
            name = flag.lstrip("-")
            lines.append(f"    {var}.add_argument({flag!r}, dest={name!r}, default={default!r})")
    lines += [
        "    return parser",
        "",
        "",
        "def dispatch(args: argparse.Namespace) -> object:",
        "    command = args.command",
    ]
    for behaviour in behaviours:
        keyword = "if" if behaviour is behaviours[0] else "elif"
        lines.append(f"    {keyword} command == '{behaviour.func}':")
        lines.append(f"        return {cli_expression(behaviour)}")
    lines += [
        "    raise ValueError(f'unknown command: {command}')",
        "",
        "",
        "def main(argv: list[str] | None = None) -> int:",
        "    args = build_parser().parse_args(argv)",
        "    try:",
        "        result = dispatch(args)",
        "    except (ValueError, TypeError, IndexError) as exc:",
        "        print(f'error: {exc}', file=sys.stderr)",
        "        return 2",
        "    print(result)",
        "    return 0",
        "",
        "",
        'if __name__ == "__main__":',
        "    raise SystemExit(main())",
        "",
    ]
    return "\n".join(lines)


def render_project(
    project_name: str,
    title: str,
    summary: str,
    requirement_texts: list[str],
    requirement_ids: list[str],
    *,
    max_functions: int = 6,
) -> GeneratedProject:
    """Produce a complete, runnable, tested Python package."""
    package = python_package(project_name)
    behaviours = select_behaviours(requirement_texts, max(1, min(max_functions, len(requirement_texts) or 1)))
    readme = "\n".join(
        [
            f"# {title}",
            "",
            summary.strip(),
            "",
            "## Layout",
            "",
            "```",
            f"{package}/",
            "  core.py    # one function per functional requirement",
            "  cli.py     # argparse CLI",
            "tests/       # pytest suite",
            "```",
            "",
            "## Run",
            "",
            "```bash",
            "uv sync",
            "uv run pytest -q",
            f"uv run python -m {package} {behaviours[0].func} \"hello world\"",
            "```",
            "",
            "## Requirements implemented",
            "",
        ]
        + [f"- `{req_id}` -> `{b.func}`" for req_id, b in zip(requirement_ids, behaviours)]
        + [""]
    )
    pyproject = "\n".join(
        [
            "[project]",
            f'name = "{package}"',
            'version = "0.1.0"',
            f'description = "{_oneline(summary, 100)}"',
            'requires-python = ">=3.10"',
            "dependencies = []",
            "",
            "[dependency-groups]",
            'dev = ["pytest>=8.0"]',
            "",
            "[build-system]",
            'requires = ["hatchling"]',
            'build-backend = "hatchling.build"',
            "",
            "[tool.hatch.build.targets.wheel]",
            f'packages = ["{package}"]',
            "",
            "[tool.pytest.ini_options]",
            'pythonpath = ["."]',
            'testpaths = ["tests"]',
            "",
        ]
    )
    files = {
        "pyproject.toml": pyproject,
        "README.md": readme,
        f"{package}/__init__.py": f'"""{title}."""\n\n__version__ = "0.1.0"\n',
        f"{package}/core.py": render_core(package, behaviours, summary),
        f"{package}/cli.py": render_cli(package, behaviours, title),
        f"{package}/__main__.py": "from .cli import main\n\nif __name__ == \"__main__\":\n    raise SystemExit(main())\n",
        "tests/test_core.py": render_tests(package, behaviours),
        ".gitignore": "__pycache__/\n*.pyc\n.pytest_cache/\n.venv/\n",
    }
    return GeneratedProject(files=files, behaviours=behaviours, package=package)
