from __future__ import annotations

import argparse
from pathlib import Path

from utils.diff import compare_submissions


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare two submissions for regression analysis")
    parser.add_argument("reference", type=Path)
    parser.add_argument("candidate", type=Path)
    args = parser.parse_args()
    print(compare_submissions(args.reference, args.candidate))


if __name__ == "__main__":
    main()
