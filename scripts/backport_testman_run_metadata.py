#!/usr/bin/env python3
"""
Backport / backfill winetest_runs metadata for older or replayed rows.

Fills in:
  - todo, skipped       — SUM from winetest_results
  - build_number        — from comment "Build N, ..."
  - target_arch         — from platform reactos.0 / reactos.9 when column is empty
  - host_os             — from platform (reactos.* → ReactOS; 6.0.6003… NT-style → Windows),
                          then sources.name; any still NULL → 'Unknown' (searchable) unless --keep-null-host-os
  - compiler, vm, host_os — from sources.name heuristics where still empty (+ MANUAL_SOURCE_OVERRIDES)

Usage:
  python backport_testman_run_metadata.py [--config PATH] [--dry-run]

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

try:
    import pymysql
except ImportError:
    print("Install PyMySQL: pip install pymysql", file=sys.stderr)
    sys.exit(1)

# Optional: force facet values by source_id when name heuristics are wrong.
MANUAL_SOURCE_OVERRIDES: dict[int, dict[str, str]] = {
    # 1: {"compiler": "GCC", "vm": "KVM", "host_os": "Linux"},
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


def infer_facets_from_source_name(name: str) -> dict[str, str | None]:
    out: dict[str, str | None] = {"compiler": None, "vm": None, "host_os": None}

    if "MSVC" in name.upper():
        out["compiler"] = "MSVC"
    elif "GCCLIN" in name.upper() or "GCCWIN" in name.upper() or re.search(r"\bGCC\b", name, re.I):
        out["compiler"] = "GCC"

    un = name.upper()
    if "KVM" in un:
        out["vm"] = "KVM"
    elif "VBOX" in un or "VIRTUALBOX" in un:
        out["vm"] = "VBox"
    elif "WHS" in un:
        out["vm"] = "WHS"
    elif "WIN2003" in un:
        out["vm"] = "Win2003_x64"

    if out["vm"] in ("KVM", "VBox"):
        out["host_os"] = "Linux"
    elif out["vm"] in ("WHS", "Win2003_x64"):
        out["host_os"] = "Windows"
    elif "GCCWIN" in un or "WIN7" in un:
        out["host_os"] = "Windows"

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
                print(f"    rows affected: {cur.rowcount}")

            cur.execute(
                "SELECT COUNT(*) FROM winetest_runs WHERE finished = 1 "
                "AND (target_arch IS NULL OR TRIM(target_arch) = '') AND platform LIKE 'reactos.%'"
            )
            n3 = int(cur.fetchone()[0])
            print(f"[3] Derive target_arch from reactos.0 / reactos.9 ({n3} rows)...")
            sql3 = """
            UPDATE winetest_runs
            SET target_arch = CASE SUBSTRING_INDEX(platform, '.', -1)
              WHEN '0' THEN 'i386'
              WHEN '9' THEN 'amd64'
              ELSE target_arch
            END
            WHERE finished = 1
              AND (target_arch IS NULL OR TRIM(target_arch) = '')
              AND platform LIKE 'reactos.%'
            """
            if args.dry_run:
                print("    (dry-run: skipped)")
            else:
                cur.execute(sql3)
                print(f"    rows affected: {cur.rowcount}")

            cur.execute(
                "SELECT COUNT(*) FROM winetest_runs WHERE finished = 1 "
                "AND (host_os IS NULL OR TRIM(host_os) = '') "
                "AND (platform LIKE 'reactos.%%' OR platform REGEXP '^[0-9]+\\\\.[0-9]+\\\\.[0-9]+')"
            )
            n4 = int(cur.fetchone()[0])
            print(f"[4] Derive host_os from platform (ReactOS vs Windows NT-style) ({n4} rows)...")
            sql4 = """
            UPDATE winetest_runs
            SET host_os = CASE
              WHEN platform LIKE 'reactos.%' THEN 'ReactOS'
              WHEN platform REGEXP '^[0-9]+\\.[0-9]+\\.[0-9]+' THEN 'Windows'
              ELSE host_os
            END
            WHERE finished = 1
              AND (host_os IS NULL OR TRIM(host_os) = '')
              AND (
                platform LIKE 'reactos.%'
                OR platform REGEXP '^[0-9]+\\.[0-9]+\\.[0-9]+'
              )
            """
            if args.dry_run:
                print("    (dry-run: skipped)")
            else:
                cur.execute(sql4)
                print(f"    rows affected: {cur.rowcount}")

            print("[5] Infer compiler, vm, host_os from sources.name...")
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
                print(f'    source {sid} "{sname}" — updated {cur.rowcount} runs → {summary}')

            if not args.keep_null_host_os:
                cur.execute(
                    "SELECT COUNT(*) FROM winetest_runs WHERE finished = 1 "
                    "AND (host_os IS NULL OR TRIM(host_os) = '')"
                )
                n6 = int(cur.fetchone()[0])
                print(
                    f"[6] Set host_os = 'Unknown' where still NULL/empty ({n6} rows) "
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
                    print(f"    rows affected: {cur.rowcount}")
            else:
                print("[6] Skipped (--keep-null-host-os): rows with empty host_os stay SQL NULL.")

        if not args.dry_run:
            conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print("-" * 60)
    print("Dry-run finished." if args.dry_run else "Backport finished.")


if __name__ == "__main__":
    main()
