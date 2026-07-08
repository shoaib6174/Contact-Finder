"""Command-line interface."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

from contact_finder.config import Config
from contact_finder.pipeline import enrich_csv


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Find verified business contacts for debtor rows.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    enrich = subparsers.add_parser("enrich", help="Enrich a CSV of debtor rows.")
    enrich.add_argument("input", type=Path, help="Input CSV path.")
    enrich.add_argument("--output", type=Path, default=Path("out/enriched.csv"))
    enrich.add_argument("--provenance", type=Path, default=Path("out/provenance.jsonl"))
    enrich.add_argument("--run-report", type=Path, default=Path("out/run_report.json"))
    enrich.add_argument("--max-calls", type=int, default=None)
    enrich.add_argument("--model", type=str, default=None)
    enrich.add_argument("--threshold", type=float, default=None)
    enrich.add_argument(
        "--agent-mode",
        choices=["tool", "fast"],
        default="fast",
        help="tool = native Groq tool-calling loop; fast = single LLM call with pre-fetched sources.",
    )

    args = parser.parse_args(argv)

    if args.command == "enrich":
        config = Config()
        if args.max_calls is not None:
            config.max_tool_calls = args.max_calls
        if args.model is not None:
            config.default_model = args.model
        if args.threshold is not None:
            config.confidence_threshold = args.threshold
        config.agent_mode = args.agent_mode

        if not config.groq_api_key:
            print("Error: GROQ_API_KEY is required.", file=sys.stderr)
            return 1

        asyncio.run(
            enrich_csv(
                input_path=args.input,
                output_path=args.output,
                provenance_path=args.provenance,
                run_report_path=args.run_report,
                config=config,
            )
        )
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
