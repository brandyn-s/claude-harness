"""Orphan script in dirty-skill — D3c SHOULD fire (never referenced).
Also serves as the C7 fixture: __main__ block + sys.argv access with
NO argparse and NO --help short-circuit. Running this with `--help`
would treat --help as a positional argument."""
import sys


def main():
    # Hand-rolled positional handling; no --help short-circuit.
    if len(sys.argv) < 2:
        sys.exit("usage: orphan.py <target>")
    target = sys.argv[1]
    print(f"would process {target}")


if __name__ == "__main__":
    main()
