#!/usr/bin/env python3
"""List all empty directories under a root path."""
import os
import sys

def main():
    root = sys.argv[1] if len(sys.argv) > 1 else "/home/pearl"
    out = []
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        try:
            entries = os.listdir(dirpath)
            if not entries:
                out.append(dirpath)
        except OSError:
            pass
    out.sort()
    report_path = os.path.join(os.path.dirname(__file__), "empty_dirs_report.txt")
    with open(report_path, "w") as f:
        for p in out:
            f.write(p + "\n")
        f.write(f"\n# Total: {len(out)} empty directories\n")
    print(f"Wrote {len(out)} paths to {report_path}")

if __name__ == "__main__":
    main()
