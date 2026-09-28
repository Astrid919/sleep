"""Regenerate all main-manuscript figures from independently reproduced TSVs."""

from __future__ import annotations

import argparse
from pathlib import Path

import create_causal_figures_20260808 as causal_figures
import create_survey_validated_figures_20260808 as survey_figures


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-dir", type=Path, required=True)
    parser.add_argument("--extension-dir", type=Path, required=True)
    args = parser.parse_args()
    base = args.base_dir.resolve()
    extension = args.extension_dir.resolve()
    base.mkdir(parents=True, exist_ok=True)
    extension.mkdir(parents=True, exist_ok=True)

    causal_figures.OUT = base
    causal_figures.main()

    survey_figures.BASE = base
    survey_figures.EXT = extension
    survey_figures.main()
    print(base)
    print(extension)


if __name__ == "__main__":
    main()
