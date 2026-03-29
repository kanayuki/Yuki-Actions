"""Local proxy verification tool.

Run this on your own machine to test proxies from alive.txt (or any link file)
through the real engine chain and generate your personal best list.

Server-side results may not match your local network -- this tool gives you
accurate results for YOUR connection.

Usage:
    cd proxy
    python local_verify.py dataset/alive.txt
    python local_verify.py dataset/alive.txt --top 50 --output my_best.txt
    python local_verify.py dataset/alive.txt --engine mihomo --timeout 8000
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.progress import (
    BarColumn,
    MofNCompleteColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeElapsedColumn,
)

from engine import TestResult, get_engine_chain, test_with_chain

console = Console(highlight=False)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Local proxy verification -- test links with real engines",
    )
    parser.add_argument(
        "input", type=Path, help="Input file with proxy share links"
    )
    parser.add_argument(
        "--top", type=int, default=100, help="Keep top N by latency (default: 100)"
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("my_best.txt"),
        help="Output file (default: my_best.txt)",
    )
    parser.add_argument(
        "--engine",
        default="auto",
        help="Engine: auto | xray | singbox | mihomo | tcp (default: auto)",
    )
    parser.add_argument(
        "--timeout", type=int, default=6000, help="Timeout in ms (default: 6000)"
    )
    parser.add_argument(
        "--concurrency", type=int, default=50, help="Parallel tests (default: 50)"
    )
    parser.add_argument(
        "--test-url",
        default="http://www.gstatic.com/generate_204",
        help="URL for connectivity test",
    )

    args = parser.parse_args()

    if not args.input.exists():
        console.print(f"[red]File not found: {args.input}[/red]")
        sys.exit(1)

    # Read links
    links = [
        line.strip()
        for line in args.input.read_text(encoding="utf-8").splitlines()
        if line.strip() and "://" in line
    ]
    if not links:
        console.print("[yellow]No links found in input file[/yellow]")
        sys.exit(1)

    console.print(f"Loaded [bold]{len(links)}[/bold] links from {args.input}")

    # Build engine chain
    chain = get_engine_chain(args.engine)
    engine_names = [e.name() for e in chain]
    console.print(f"Engines: [bold]{' -> '.join(engine_names)}[/bold]")

    # Test with progress
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        console=console,
        transient=False,
    ) as progress:
        task = progress.add_task("Testing...", total=len(links))

        def _on_done(r: TestResult) -> None:
            progress.advance(task)

        results = test_with_chain(
            links,
            chain,
            timeout_ms=args.timeout,
            concurrency=args.concurrency,
            test_url=args.test_url,
            on_done=_on_done,
        )

    # Sort and output
    passed = sorted(
        [r for r in results if r.ok], key=lambda r: r.latency_ms
    )[: args.top]

    if not passed:
        console.print("[red]No proxies passed the test[/red]")
        sys.exit(1)

    args.output.write_text(
        "\n".join(r.link for r in passed) + "\n", encoding="utf-8"
    )

    # Summary
    best_lat = passed[0].latency_ms if passed else 0
    avg_lat = sum(r.latency_ms for r in passed) / len(passed)

    console.print(
        Panel(
            f"Tested: {len(results)}  |  "
            f"Passed: [green bold]{len(passed)}[/green bold]  |  "
            f"Best: [bold]{best_lat:.0f}ms[/bold]  |  "
            f"Avg: {avg_lat:.0f}ms\n"
            f"Saved to: [bold]{args.output}[/bold]",
            title="[bold]Local Verify Result[/bold]",
            border_style="green",
        )
    )


if __name__ == "__main__":
    main()
