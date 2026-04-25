"""Benchmark per-image pipeline throughput. V0.5+."""

from pathlib import Path


def main(folder: Path) -> None:
    raise NotImplementedError("V0.5: bench on a folder, report images/sec, per-stage timing")


if __name__ == "__main__":
    import sys
    main(Path(sys.argv[1]))
