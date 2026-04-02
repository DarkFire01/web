#!/usr/bin/env python3
"""
Fetches test run data (including per-suite logs) from a ReactOS Testman
instance and stores it locally as JSON for later submission.

For each test run the full suite results are fetched via the XML export
endpoint, then the raw log for each suite is extracted from detail.php.

Usage:
    python fetch_builds.py [--base-url URL] [--count N] [--output FILE] [--delay SECS]
        [--platform PREFIX] [--arches LIST] [--source-ids IDS]

Optional filters are passed to ajax-search.php (same as the Testman UI). Examples:

    # More history (mixed platforms)
    python fetch_builds.py --count 200 --suites 12

    # Mostly amd64 ReactOS runs (platform tail 9 = amd64 in Testman encoding)
    python fetch_builds.py --count 40 --platform reactos.9

    # i386 ReactOS runs
    python fetch_builds.py --count 40 --platform reactos.0

    # By effective arch facet (when the server has arch data / COALESCE logic)
    python fetch_builds.py --count 40 --arches i386,amd64

    # AMD64 / Windows amd64 rows (server --arches/--platform often miss these):
    python fetch_builds.py --count 40 --platform-display-contains AMD64

Default --base-url is the official site (https://reactos.org).

Requirements:
    pip install requests
"""

import argparse
import html
import json
import re
import time
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests


def get(url, params, retries=5, backoff=5):
    """GET with retry on timeout or connection error."""
    for attempt in range(1, retries + 1):
        try:
            resp = requests.get(url, params=params, timeout=30)
            resp.raise_for_status()
            return resp
        except (requests.Timeout, requests.ConnectionError) as exc:
            if attempt == retries:
                raise
            wait = backoff * attempt
            print(f"    timeout/connection error ({exc}), retrying in {wait}s "
                  f"(attempt {attempt}/{retries})")
            time.sleep(wait)


def search_runs(base_url, page, limit, filter_params=None):
    base = base_url.rstrip("/")
    url = f"{base}/testman/ajax-search.php"
    params = {"page": page, "resultlist": "1", "desc": "1", "limit": limit}
    if filter_params:
        params.update(filter_params)
    return ET.fromstring(get(url, params).text)


def _export_find_run_el(root):
    """First <run> element; handles optional XML namespaces ({uri}run)."""
    if root.tag == "run" or (isinstance(root.tag, str) and root.tag.endswith("}run")):
        return root
    for el in root.iter():
        if el.tag == "run" or (isinstance(el.tag, str) and el.tag.endswith("}run")):
            return el
    return None


def _platform_from_export_raw(text):
    """Parse platform=\"...\" from raw export XML (ET often drops attrs when a DOCTYPE is present)."""
    m = re.search(r"<run\b[^>]*?\bplatform=\"([^\"]*)\"", text, re.DOTALL | re.IGNORECASE)
    if m:
        return html.unescape(m.group(1).strip())
    m = re.search(r"<run\b[^>]*?\bplatform='([^']*)'", text, re.DOTALL | re.IGNORECASE)
    if m:
        return html.unescape(m.group(1).strip())
    return ""


def export_run(base_url, run_id):
    """Return (parsed root, raw body text) for attribute recovery when ET drops DOCTYPE-tagged attrs."""
    base = base_url.rstrip("/")
    url = f"{base}/testman/export.php"
    resp = get(url, {"f": "xml", "ids": str(run_id)})
    text = resp.text.lstrip("\ufeff \t\n\r")
    root = ET.fromstring(text)
    return root, text


def fetch_log(base_url, result_id):
    """Fetch detail.php for a suite result and return the raw log text."""
    base = base_url.rstrip("/")
    url = f"{base}/testman/detail.php"
    resp = get(url, {"id": str(result_id)})

    match = re.search(r"<pre>(.*?)</pre>", resp.text, re.DOTALL)
    if not match:
        return ""

    raw = re.sub(r"<[^>]+>", "", match.group(1))
    return html.unescape(raw)


def main():
    parser = argparse.ArgumentParser(
        description="Fetch Testman runs (with logs) from a ReactOS Testman server."
    )
    parser.add_argument(
        "--base-url",
        default="https://reactos.org",
        help="Testman site root (default: https://reactos.org), no trailing slash required",
    )
    parser.add_argument("--count", type=int, default=50,
                        help="Maximum number of test runs to fetch (default: 50)")
    parser.add_argument("--output", default="builds_data.json",
                        help="Output JSON file (default: builds_data.json)")
    parser.add_argument("--delay", type=float, default=0.2,
                        help="Delay between requests in seconds (default: 0.2)")
    parser.add_argument("--workers", type=int, default=5,
                        help="Parallel workers for fetching suite logs (default: 5)")
    parser.add_argument("--suites", type=int, default=10,
                        help="Max suite logs to fetch per run (default: 10)")
    parser.add_argument(
        "--platform",
        default="",
        help="ajax-search platform= prefix filter (e.g. reactos.0=i386, reactos.9=amd64)",
    )
    parser.add_argument(
        "--arches",
        default="",
        help="ajax-search arches= comma-list (e.g. i386 or i386,amd64)",
    )
    parser.add_argument(
        "--source-ids",
        default="",
        help="ajax-search source_ids= comma-list of numeric source ids",
    )
    parser.add_argument(
        "--platform-display-contains",
        default="",
        help=(
            "Keep only runs whose search-list platform string contains this substring "
            "(matches human-readable XML, e.g. AMD64 or ReactOS - AMD64). "
            "Use this when --platform/--arches return nothing: server filters use raw DB "
            "values, while ajax-search lists GetPlatformString() output."
        ),
    )
    parser.add_argument(
        "--source-display-contains",
        default="",
        help=(
            "Keep only runs whose search-list <source> (builder name) contains this substring, "
            "e.g. KVM or Test_KVM. Combine with --platform-display-contains for builder+arch slices."
        ),
    )
    args = parser.parse_args()

    base_url = args.base_url
    print(f"Source: {base_url.rstrip('/')}/testman/")

    filter_params = {}
    if args.platform.strip():
        filter_params["platform"] = args.platform.strip()
    if args.arches.strip():
        filter_params["arches"] = args.arches.strip()
    if args.source_ids.strip():
        filter_params["source_ids"] = args.source_ids.strip()
    if filter_params:
        print(f"Search filters: {filter_params}")

    display_needle = args.platform_display_contains.strip()
    if display_needle:
        print(f"Client filter: platform display must contain {display_needle!r}")
    source_needle = args.source_display_contains.strip()
    if source_needle:
        print(f"Client filter: source must contain {source_needle!r}")

    runs = []
    page = 1
    max_pages = 500

    while len(runs) < args.count and page <= max_pages:
        batch = args.count - len(runs)
        if display_needle or source_needle:
            batch = max(batch, 50)
        root = search_runs(base_url, page, batch, filter_params or None)
        time.sleep(args.delay)

        result_elements = root.findall("result")
        if not result_elements:
            break

        for result_el in result_elements:
            run_id   = int(result_el.findtext("id"))
            # Search XML uses GetPlatformString() (long, human-readable).
            platform_display = result_el.findtext("platform", "")
            source_display = result_el.findtext("source", "")
            source_id_raw = (result_el.findtext("source_id", "") or "").strip()
            source_id = int(source_id_raw) if source_id_raw.isdigit() else None
            comment  = result_el.findtext("comment", "")

            if display_needle and display_needle not in platform_display:
                continue
            if source_needle and source_needle not in source_display:
                continue

            if len(runs) >= args.count:
                break

            try:
                export_root, export_text = export_run(base_url, run_id)
                run_el = _export_find_run_el(export_root)
                if run_el is None:
                    print(f"  [{run_id}] no <run> in export, skipping")
                    continue

                # Webservice / DB expect the compact stored platform (export attribute), not the list display string.
                platform_raw = (run_el.get("platform") or "").strip()
                if not platform_raw:
                    platform_raw = _platform_from_export_raw(export_text)
                if not platform_raw:
                    platform_raw = platform_display

                suite_elements = run_el.findall("test")[:args.suites]
                total_suites = len(suite_elements)

                suite_meta = {
                    int(el.get("id")): {
                        "module": el.get("module", ""),
                        "test":   el.get("test", ""),
                        "status": el.get("status", "ok"),
                    }
                    for el in suite_elements
                }
                result_ids = [int(el.get("id")) for el in suite_elements]

                logs = {}
                done = 0
                with ThreadPoolExecutor(max_workers=args.workers) as pool:
                    futures = {pool.submit(fetch_log, base_url, rid): rid for rid in result_ids}
                    for future in as_completed(futures):
                        rid = futures[future]
                        logs[rid] = future.result()
                        done += 1
                        meta = suite_meta[rid]
                        print(f"  [{run_id}] {done}/{total_suites} "
                              f"{meta['module']}:{meta['test']} "
                              f"({len(logs[rid])} bytes)")

                suites = [
                    {**suite_meta[rid], "log": logs[rid]}
                    for rid in result_ids
                ]

                runs.append({
                    "id":         run_id,
                    "source_id":  source_id,
                    "source":     run_el.get("source", result_el.findtext("source", "")),
                    "revision":   run_el.get("revision", ""),
                    "platform": platform_raw,
                    "comment":  comment,
                    "suites":   suites,
                })

            except Exception as exc:
                print(f"  [{run_id}] FAILED: {exc}")

        if not display_needle and not source_needle:
            total = int(root.findtext("resultcount", 0))
            if len(runs) >= total:
                break
        page += 1

    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(runs, f, indent=2, ensure_ascii=False)

    print(f"\nSaved {len(runs)} runs to '{args.output}'")
    if len(runs) == 0 and (display_needle or source_needle):
        print(
            "No runs matched the client filters. Broaden --platform-display-contains / "
            "--source-display-contains or remove server-side --platform/--arches."
        )


if __name__ == "__main__":
    main()
