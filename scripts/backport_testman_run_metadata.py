#!/usr/bin/env python3
"""
Backport / backfill winetest_runs metadata for older or replayed rows.

Fills in:
  - todo, skipped       — SUM from winetest_results
  - build_number        — from comment "Build N, ..."
  - platform            — reactos.0→reactos.9 when vm=KVM and target_arch=amd64 (KVM_x64 export quirk)
  - target_arch         — from platform reactos.0 / reactos.9 when column is empty or wrong
  - host_os             — from platform (reactos.* → ReactOS; 6.0.6003… NT-style → Windows),
                          then sources.name; any still NULL → 'Unknown' (searchable) unless --keep-null-host-os
  - compiler, vm, host_os, target_arch — from sources.name heuristics where still empty (+ MANUAL_SOURCE_OVERRIDES)

Usage:
  python backport_testman_run_metadata.py [--config PATH] [--dry-run] [--diagnose]

Examples:
  python backport_testman_run_metadata.py \\
    --config /srv/www/www.reactos.org_config/testman-connect.php

  python backport_testman_run_metadata.py --dry-run

Requirements:
  pip install pymysql
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from testman_facet_infer import infer_facets_from_source_name

try:
    import pymysql
except ImportError:
    print("Install PyMySQL: pip install pymysql", file=sys.stderr)
    sys.exit(1)

# Optional: force facet values by Testman sources.id (= winetest_runs.source_id, same ints as
# fetch_builds.py --source-ids). Verify on server: SELECT id, name FROM sources;
# builds*.json "source" is the display name; re-fetch after deploy includes "source_id" from ajax-search.
MANUAL_SOURCE_OVERRIDES: dict[int, dict[str, str]] = {
    # Example after confirming id: 1: {"compiler": "GCC", "vm": "KVM", "host_os": "Linux"},
}

DEFINE_RE = re.compile(
    r'define\s*\(\s*["\'](TESTMAN_DB_[A-Z_]+)["\']\s*,\s*["\']([^"\']*)["\']\s*\)',
    re.IGNORECASE,
)


def parse_testman_connect(path: Path) -> dict[str, str]:
    text = path.read_text(encoding="utf-8", errors="replace")
    out: dict[str, str] = {}
    for m in DEFINE_RE.finditer(text):
        out[m.group(1).upper()] = m.group(2)
    need = ("TESTMAN_DB_HOST", "TESTMAN_DB_USER", "TESTMAN_DB_PASS", "TESTMAN_DB_NAME")
    for k in need:
        if k not in out:
            raise SystemExit(f"Missing {k} in {path}")
    return out


def default_config_paths() -> list[Path]:
    here = Path(__file__).resolve().parent
    return [
        here.parent / "www" / "www.reactos.org_config" / "testman-connect.php",
        here.parent / "docker" / "config" / "testman-connect.php",
    ]


def main() -> None:
    ap = argparse.ArgumentParser(description="Backfill Testman winetest_runs metadata.")
    ap.add_argument(
        "--config",
        type=Path,
        help="Path to testman-connect.php (defines TESTMAN_DB_*)",
    )
    ap.add_argument("--dry-run", action="store_true", help="No UPDATE statements")
    ap.add_argument(
        "--keep-null-host-os",
        action="store_true",
        help="Leave host_os as SQL NULL when heuristics cannot infer it (no 'Unknown' tag).",
    )
    ap.add_argument(
        "--diagnose",
        action="store_true",
        help="Print facet/platform/source samples (read-only) and exit; use when all steps show 0 rows.",
    )
    args = ap.parse_args()

    cfg_path = args.config
    if not cfg_path:
        for p in default_config_paths():
            if p.is_file():
                cfg_path = p
                break
    if not cfg_path or not cfg_path.is_file():
        print(
            "Pass --config=/path/to/testman-connect.php "
            "(or place config under ../www/www.reactos.org_config/).",
            file=sys.stderr,
        )
        sys.exit(1)

    db = parse_testman_connect(cfg_path)
    print(f"Using config: {cfg_path}")
    print("DRY-RUN (no writes)" if args.dry_run else "APPLYING updates")
    print("-" * 60)

    conn = pymysql.connect(
        host=db["TESTMAN_DB_HOST"],
        user=db["TESTMAN_DB_USER"],
        password=db["TESTMAN_DB_PASS"],
        database=db["TESTMAN_DB_NAME"],
        charset="utf8mb4",
        autocommit=False,
    )

    try:
        with conn.cursor() as cur:
            updates_applied = 0
            if args.diagnose:
                print("DIAGNOSE (read-only)")
                print("-" * 60)
                cur.execute("SELECT COUNT(*) FROM winetest_runs WHERE finished = 1")
                print(f"finished runs: {int(cur.fetchone()[0])}")
                for label, q in (
                    (
                        "target_arch empty + reactos platform (step 3 scope)",
                        "SELECT COUNT(*) FROM winetest_runs WHERE finished = 1 "
                        "AND (target_arch IS NULL OR TRIM(target_arch) = '') "
                        "AND (platform LIKE 'reactos.%' OR platform REGEXP '^reactos0([^0-9]|$)' "
                        "OR platform REGEXP '^reactos9([^0-9]|$)')",
                    ),
                    (
                        "host_os empty + derivable platform (step 4 scope)",
                        "SELECT COUNT(*) FROM winetest_runs WHERE finished = 1 "
                        "AND (host_os IS NULL OR TRIM(host_os) = '') "
                        "AND (platform LIKE 'reactos.%' OR platform REGEXP '^reactos[0-9]' "
                        "OR platform REGEXP '^[0-9]+\\\\.[0-9]+\\\\.[0-9]+')",
                    ),
                    (
                        "host_os still empty (step 7 would tag Unknown)",
                        "SELECT COUNT(*) FROM winetest_runs WHERE finished = 1 "
                        "AND (host_os IS NULL OR TRIM(host_os) = '')",
                    ),
                    (
                        "build_number empty + comment Build … (step 2 scope)",
                        "SELECT COUNT(*) FROM winetest_runs WHERE (build_number IS NULL OR build_number = 0) "
                        "AND comment LIKE 'Build %'",
                    ),
                ):
                    cur.execute(q)
                    print(f"  {label}: {int(cur.fetchone()[0])}")
                print("  DISTINCT platform (finished, up to 20):")
                cur.execute(
                    "SELECT platform, COUNT(*) AS c FROM winetest_runs WHERE finished = 1 "
                    "GROUP BY platform ORDER BY c DESC LIMIT 20"
                )
                for row in cur.fetchall():
                    print(f"    {row[0]!r}: {row[1]}")
                print("  sources:")
                cur.execute("SELECT id, name FROM sources ORDER BY id")
                for row in cur.fetchall():
                    print(f"    id={row[0]} name={row[1]!r}")
                print("-" * 60)
                print(
                    "If step-4/5/7 counts are 0, metadata is already filled or platforms "
                    "do not match reactos.* / NT-style. Step [1] rowcount can be 0 when "
                    "todo/skipped already match sums. Step [5] skips generic source names "
                    '(e.g. "Lab Buildbot"); use MANUAL_SOURCE_OVERRIDES only if one source '
                    "maps to one fixed facet set."
                )
                return

            cur.execute("SELECT COUNT(*) FROM winetest_runs WHERE finished = 1")
            n1 = int(cur.fetchone()[0])
            print(f"[1] Sync todo/skipped from winetest_results ({n1} finished runs)...")
            sql1 = """
            UPDATE winetest_runs r
            SET
              r.todo = (SELECT COALESCE(SUM(wr.todo), 0) FROM winetest_results wr WHERE wr.test_id = r.id),
              r.skipped = (SELECT COALESCE(SUM(wr.skipped), 0) FROM winetest_results wr WHERE wr.test_id = r.id)
            WHERE r.finished = 1
            """
            if args.dry_run:
                print("    (dry-run: skipped)")
            else:
                cur.execute(sql1)
                updates_applied += cur.rowcount
                print(f"    rows affected: {cur.rowcount}")

            cur.execute(
                "SELECT COUNT(*) FROM winetest_runs WHERE (build_number IS NULL OR build_number = 0) "
                "AND comment LIKE 'Build %'"
            )
            n2 = int(cur.fetchone()[0])
            print(f"[2] Backfill build_number from comment (up to {n2} candidates)...")
            sql2 = """
            UPDATE winetest_runs
            SET build_number = CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(comment, 'Build ', -1), ',', 1) AS UNSIGNED)
            WHERE (build_number IS NULL OR build_number = 0)
              AND comment LIKE 'Build %'
              AND SUBSTRING_INDEX(SUBSTRING_INDEX(comment, 'Build ', -1), ',', 1) REGEXP '^[0-9]+$'
            """
            if args.dry_run:
                print("    (dry-run: skipped)")
            else:
                cur.execute(sql2)
                updates_applied += cur.rowcount
                print(f"    rows affected: {cur.rowcount}")

            cur.execute(
                "SELECT COUNT(*) FROM winetest_runs WHERE finished = 1 "
                "AND vm = 'KVM' AND target_arch = 'amd64' "
                "AND (platform REGEXP '^reactos\\.0(\\.|$)' OR platform REGEXP '^reactos0([^0-9]|$)')"
            )
            n_kvm_plat = int(cur.fetchone()[0])
            print(
                f"[3] Fix platform for KVM + amd64 still on reactos.0/reactos0 "
                f"(export quirk, {n_kvm_plat} rows)..."
            )
            sql_kvm_plat = """
            UPDATE winetest_runs
            SET platform = CASE
              WHEN platform REGEXP '^reactos\\.0(\\.|$)' THEN CONCAT('reactos.9', SUBSTRING(platform, 10))
              WHEN platform REGEXP '^reactos0([^0-9]|$)' THEN CONCAT('reactos9', SUBSTRING(platform, 9))
              ELSE platform
            END
            WHERE finished = 1
              AND vm = 'KVM'
              AND target_arch = 'amd64'
              AND (
                platform REGEXP '^reactos\\.0(\\.|$)'
                OR platform REGEXP '^reactos0([^0-9]|$)'
              )
            """
            if args.dry_run:
                print("    (dry-run: skipped)")
            else:
                cur.execute(sql_kvm_plat)
                updates_applied += cur.rowcount
                print(f"    rows affected: {cur.rowcount}")

            cur.execute(
                "SELECT COUNT(*) FROM winetest_runs WHERE finished = 1 "
                "AND ("
                "  ("
                "    (platform REGEXP '^reactos\\.0(\\.|$)' OR platform REGEXP '^reactos0([^0-9]|$)')"
                "    AND (target_arch IS NULL OR TRIM(target_arch) = '' OR target_arch <> 'i386')"
                "  ) OR ("
                "    (platform REGEXP '^reactos\\.9(\\.|$)' OR platform REGEXP '^reactos9([^0-9]|$)')"
                "    AND (target_arch IS NULL OR TRIM(target_arch) = '' OR target_arch <> 'amd64')"
                "  )"
                ")"
            )
            n3 = int(cur.fetchone()[0])
            print(
                f"[4] Align target_arch with reactos.0/9 and reactos0/9 (empty or wrong, {n3} rows)..."
            )
            # One backslash before "." in the pattern (same as facets.inc.php / MySQL REGEXP).
            sql3 = """
            UPDATE winetest_runs
            SET target_arch = CASE
              WHEN platform REGEXP '^reactos\\.0(\\.|$)' OR platform REGEXP '^reactos0([^0-9]|$)'
                THEN 'i386'
              WHEN platform REGEXP '^reactos\\.9(\\.|$)' OR platform REGEXP '^reactos9([^0-9]|$)'
                THEN 'amd64'
              ELSE target_arch
            END
            WHERE finished = 1
              AND (
                (
                  (platform REGEXP '^reactos\\.0(\\.|$)' OR platform REGEXP '^reactos0([^0-9]|$)')
                  AND (target_arch IS NULL OR TRIM(target_arch) = '' OR target_arch <> 'i386')
                ) OR (
                  (platform REGEXP '^reactos\\.9(\\.|$)' OR platform REGEXP '^reactos9([^0-9]|$)')
                  AND (target_arch IS NULL OR TRIM(target_arch) = '' OR target_arch <> 'amd64')
                )
              )
            """
            if args.dry_run:
                print("    (dry-run: skipped)")
            else:
                cur.execute(sql3)
                updates_applied += cur.rowcount
                print(f"    rows affected: {cur.rowcount}")

            cur.execute(
                "SELECT COUNT(*) FROM winetest_runs WHERE finished = 1 "
                "AND (host_os IS NULL OR TRIM(host_os) = '') "
                "AND (platform LIKE 'reactos.%%' OR platform REGEXP '^reactos[0-9]' "
                "OR platform REGEXP '^[0-9]+\\\\.[0-9]+\\\\.[0-9]+')"
            )
            n4 = int(cur.fetchone()[0])
            print(f"[5] Derive host_os from platform (ReactOS vs Windows NT-style) ({n4} rows)...")
            sql4 = """
            UPDATE winetest_runs
            SET host_os = CASE
              WHEN platform LIKE 'reactos.%' OR platform REGEXP '^reactos[0-9]' THEN 'ReactOS'
              WHEN platform REGEXP '^[0-9]+\\.[0-9]+\\.[0-9]+' THEN 'Windows'
              ELSE host_os
            END
            WHERE finished = 1
              AND (host_os IS NULL OR TRIM(host_os) = '')
              AND (
                platform LIKE 'reactos.%'
                OR platform REGEXP '^reactos[0-9]'
                OR platform REGEXP '^[0-9]+\\.[0-9]+\\.[0-9]+'
              )
            """
            if args.dry_run:
                print("    (dry-run: skipped)")
            else:
                cur.execute(sql4)
                updates_applied += cur.rowcount
                print(f"    rows affected: {cur.rowcount}")

            print("[6] Infer compiler, vm, host_os, target_arch from sources.name...")
            cur.execute("SELECT id, name FROM sources ORDER BY id")
            sources = cur.fetchall()

            for sid, sname in sources:
                sid = int(sid)
                inf = infer_facets_from_source_name(sname)
                if sid in MANUAL_SOURCE_OVERRIDES:
                    for k, v in MANUAL_SOURCE_OVERRIDES[sid].items():
                        if v:
                            inf[k] = v

                sets: list[str] = []
                params: list[Any] = []
                if inf.get("compiler"):
                    sets.append("compiler = IF(compiler IS NULL OR TRIM(compiler) = '', %s, compiler)")
                    params.append(inf["compiler"])
                if inf.get("vm"):
                    sets.append("vm = IF(vm IS NULL OR TRIM(vm) = '', %s, vm)")
                    params.append(inf["vm"])
                if inf.get("host_os"):
                    sets.append("host_os = IF(host_os IS NULL OR TRIM(host_os) = '', %s, host_os)")
                    params.append(inf["host_os"])
                if inf.get("target_arch"):
                    sets.append(
                        "target_arch = IF(target_arch IS NULL OR TRIM(target_arch) = '', %s, target_arch)"
                    )
                    params.append(inf["target_arch"])

                if not sets:
                    print(
                        f'    source {sid} "{sname}" — no heuristic match '
                        f"(edit MANUAL_SOURCE_OVERRIDES in {Path(__file__).name} if needed)"
                    )
                    continue

                null_checks: list[str] = []
                if inf.get("compiler"):
                    null_checks.append("(compiler IS NULL OR TRIM(compiler) = '')")
                if inf.get("vm"):
                    null_checks.append("(vm IS NULL OR TRIM(vm) = '')")
                if inf.get("host_os"):
                    null_checks.append("(host_os IS NULL OR TRIM(host_os) = '')")
                if inf.get("target_arch"):
                    null_checks.append("(target_arch IS NULL OR TRIM(target_arch) = '')")

                count_sql = (
                    "SELECT COUNT(*) FROM winetest_runs WHERE source_id = %s AND finished = 1 AND ("
                    + " OR ".join(null_checks)
                    + ")"
                )
                cur.execute(count_sql, (sid,))
                cnt = int(cur.fetchone()[0])
                if cnt == 0:
                    print(f'    source {sid} "{sname}" — nothing to fill (facets already set)')
                    continue

                summary = json.dumps({k: v for k, v in inf.items() if v}, ensure_ascii=False)
                if args.dry_run:
                    print(f'    source {sid} "{sname}" — would update {cnt} runs → {summary}')
                    continue

                upd_sql = f"UPDATE winetest_runs SET {', '.join(sets)} WHERE source_id = %s AND finished = 1"
                params.append(sid)
                cur.execute(upd_sql, params)
                updates_applied += cur.rowcount
                print(f'    source {sid} "{sname}" — updated {cur.rowcount} runs → {summary}')

            if not args.keep_null_host_os:
                cur.execute(
                    "SELECT COUNT(*) FROM winetest_runs WHERE finished = 1 "
                    "AND (host_os IS NULL OR TRIM(host_os) = '')"
                )
                n6 = int(cur.fetchone()[0])
                print(
                    f"[7] Set host_os = 'Unknown' where still NULL/empty ({n6} rows) "
                    "(facet for unknown host OS; use --keep-null-host-os to skip)..."
                )
                sql6 = """
                UPDATE winetest_runs
                SET host_os = 'Unknown'
                WHERE finished = 1
                  AND (host_os IS NULL OR TRIM(host_os) = '')
                """
                if args.dry_run:
                    print("    (dry-run: skipped)")
                else:
                    cur.execute(sql6)
                    updates_applied += cur.rowcount
                    print(f"    rows affected: {cur.rowcount}")
            else:
                print("[7] Skipped (--keep-null-host-os): rows with empty host_os stay SQL NULL.")

        if not args.dry_run:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("-" * 60)
    if not args.dry_run and not args.diagnose and updates_applied == 0:
        print(
            "Note: No column values were changed this run (MySQL reports rows actually modified). "
            "Numbers in parentheses for [2]–[7] are candidate counts before UPDATE; 0 means nothing matched. "
            "[1] is often 0 when todo/skipped already equal per-result sums. "
            '"Lab Buildbot" in [6] is expected unless you add MANUAL_SOURCE_OVERRIDES. '
            "Use --diagnose to list platform and source rows."
        )
    print("Dry-run finished." if args.dry_run else "Backport finished.")


if __name__ == "__main__":
    main()
