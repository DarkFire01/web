#!/usr/bin/env python3
"""
Fetch Testman runs for the main ReactOS *test* builders (not compile-only builders).

Uses fetch_builds.py with --source-display-contains patterns that match official
reactos.org <source> strings:

  Test KVM (ReactOS i386, sysreg on KVM)
    → "Build … on Test KVM" but not KVM_x64 → match GCCLin_x86 tail uniquely.

  Test KVM_x64 (ReactOS amd64)
    → substring "KVM_x64"

  Test Win2003_x64 (rostests on Windows; platform shows "Windows Server 2008 …")
    → "Win2003_x64" (buildbot builder name in sources.name)

  Test WHS
    → "Test WHS"

Examples:
  python fetch_testman_buildbot_tests.py --all --count 40 --suites 8
  python fetch_testman_buildbot_tests.py --kvm-i386 --output my_kvm.json
  python fetch_testman_buildbot_tests.py --base-url https://reactos.org --all
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FETCH_BUILDS = HERE / "fetch_builds.py"

# (flag, output default, extra fetch_builds argv after --source-display-contains)
TARGETS: list[tuple[str, str, list[str]]] = [
    (
        "kvm-i386",
        "builds_test_kvm_i386.json",
        # Only "Build GCCLin_x86 on Test KVM"; avoids matching "… on Test KVM_x64".
        ["--source-display-contains", "Lin_x86 on Test KVM"],
    ),
    (
        "kvm-x64",
        "builds_test_kvm_x64.json",
        ["--source-display-contains", "KVM_x64"],
    ),
    (
        "win2003-x64",
        "builds_test_win2003_x64.json",
        [
            "--source-display-contains",
            "Win2003_x64",
        ],
    ),
    (
        "whs",
        "builds_test_whs.json",
        ["--source-display-contains", "Test WHS"],
    ),
]


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Wrapper: fetch Testman data for Test KVM / KVM_x64 / Win2003_x64 / WHS."
    )
    ap.add_argument("--all", action="store_true", help="Run all four targets")
    for flag, default_out, _ in TARGETS:
        ap.add_argument(
            f"--{flag}",
            action="store_true",
            help=f"Fetch only this target (default output: {default_out})",
        )
    ap.add_argument("--base-url", default="https://reactos.org", help="Testman site root")
    ap.add_argument("--count", type=int, default=50, help="Runs per target (default 50)")
    ap.add_argument("--suites", type=int, default=10, help="Suite logs per run")
    ap.add_argument("--delay", type=float, default=0.2, help="Delay between search pages")
    ap.add_argument("--workers", type=int, default=5, help="Parallel log fetch workers")
    args, passthrough = ap.parse_known_args()

    selected: list[tuple[str, str, list[str]]] = []
    if args.all:
        selected = list(TARGETS)
    else:
        for flag, default_out, argv in TARGETS:
            if getattr(args, flag.replace("-", "_"), False):
                selected.append((flag, default_out, argv))

    if not selected:
        ap.print_help()
        print("\nSelect --all or one of: --kvm-i386 --kvm-x64 --win2003-x64 --whs", file=sys.stderr)
        sys.exit(2)

    common = [
        str(FETCH_BUILDS),
        "--base-url",
        args.base_url,
        "--count",
        str(args.count),
        "--suites",
        str(args.suites),
        "--delay",
        str(args.delay),
        "--workers",
        str(args.workers),
    ]
    common.extend(passthrough)

    for flag, default_out, needle_argv in selected:
        out = default_out
        cmd = [sys.executable, *common, *needle_argv, "--output", out]
        print("+", " ".join(cmd), flush=True)
        r = subprocess.run(cmd, cwd=str(HERE))
        if r.returncode != 0:
            sys.exit(r.returncode)

    print("Done.", file=sys.stderr)


if __name__ == "__main__":
    main()
