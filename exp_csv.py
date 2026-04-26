import argparse

from console_utils import configure_console_output
import database


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Export OSINT datasets to CSV.")
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="Export only the baseline NLP dataset.",
    )
    return parser


def main() -> int:
    configure_console_output()
    args = build_parser().parse_args()
    database.init_db()

    baseline = database.export_baseline_csv()
    print(f"Baseline dataset exported to {baseline}")

    if not args.baseline_only:
        enriched = database.export_enriched_csv()
        report = database.export_osint_report_csv()
        print(f"Enriched dataset exported to {enriched}")
        print(f"OSINT report exported to {report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
