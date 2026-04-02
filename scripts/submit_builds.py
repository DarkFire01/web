#!/usr/bin/env python3
"""
Submits locally stored test run data to a Testman instance via its webservice.

Reads the JSON file produced by fetch_builds.py and replays each run through
the normal testman webservice HTTP API:
  gettestid → getsuiteid → submit (per suite) → finish

The actual log text fetched from the live server is submitted as-is.

Facets (compiler, vm, host_os) and build_number are sent on gettestid when the
JSON has a "source" string (e.g. "Build MSVC_x64 on Test KVM_x64") so the lab DB
matches upstream builder names even though authentication uses one sources row
(e.g. "Lab Buildbot"). Requires an updated webservice index.php on the server.

Usage:
    python submit_builds.py [--input FILE] [--url URL] [--sourceid N] [--password PW]

Lab VPS (this project): copy with `scp ... darkfire@216.128.144.135:~/` then
either submit from your PC or on the server. API password is plaintext whose
MD5 is in `sources.password`.

From your PC:

    python submit_builds.py --input builds_data.json \\
      --url http://216.128.144.135/testman/webservice/index.php \\
      --sourceid 1 --password '51505150'

On the server (after ssh darkfire@216.128.144.135):

    python3 submit_builds.py --input builds_data.json \\
      --url http://127.0.0.1/testman/webservice/index.php \\
      --sourceid 1 --password '51505150'

Requirements:
    pip install requests

The default credentials (sourceid=1, password=51505150) match the test source
in Docker init.sql. Re-run `docker compose down -v && docker compose up` to
reset the database if needed.
"""

import argparse
import json
import sys
from pathlib import Path

import requests

# Same directory as this script (works when run as python submit_builds.py).
_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from testman_facet_infer import (
    build_number_from_comment,
    infer_facets_from_source_name,
    normalize_platform_for_amd64_kvm_worker,
    target_arch_from_platform,
)

WEBSERVICE_URL = "http://localhost/testman/webservice/index.php"
DEFAULT_SOURCE_ID = 1
DEFAULT_PASSWORD = "51505150"


def ws_post(url, **fields):
    """POST to the webservice and return the response text."""
    resp = requests.post(url, data=fields, timeout=30)
    resp.raise_for_status()
    return resp.text.strip()


def main():
    parser = argparse.ArgumentParser(description="Submit test run data to a local Testman via its webservice.")
    parser.add_argument("--input", default="builds_data.json",
                        help="Input JSON file produced by fetch_builds.py (default: builds_data.json)")
    parser.add_argument("--url", default=WEBSERVICE_URL,
                        help=f"Testman webservice URL (default: {WEBSERVICE_URL})")
    parser.add_argument("--sourceid", type=int, default=DEFAULT_SOURCE_ID,
                        help=f"Source ID to authenticate as (default: {DEFAULT_SOURCE_ID})")
    parser.add_argument("--password", default=DEFAULT_PASSWORD,
                        help=f"Source password (default: {DEFAULT_PASSWORD!r})")
    args = parser.parse_args()

    with open(args.input, encoding="utf-8") as f:
        runs = json.load(f)

    print(f"Loaded {len(runs)} runs from '{args.input}'")

    submitted = 0
    failed = 0

    for run in runs:
        revision = run["revision"]
        comment = run.get("comment", "")
        suites = run.get("suites", [])
        label = run.get("source") or ""
        platform = normalize_platform_for_amd64_kvm_worker(run["platform"], label)

        try:
            # 1. Register the test run and get a local test ID (include facets from JSON "source").
            get_fields = {
                "sourceid": args.sourceid,
                "password": args.password,
                "action": "gettestid",
                "revision": revision,
                "platform": platform,
                "comment": comment,
            }
            facets = infer_facets_from_source_name(label)
            bn = build_number_from_comment(comment)
            if bn is not None:
                get_fields["build_number"] = str(bn)
            for k in ("compiler", "vm", "host_os"):
                v = facets.get(k)
                if v:
                    get_fields[k] = v
            # Platform reactos.0 / reactos.9 (and rosautotest reactos0/9) beats builder label for arch.
            ta = target_arch_from_platform(platform)
            if ta:
                get_fields["target_arch"] = ta
            elif facets.get("target_arch"):
                get_fields["target_arch"] = facets["target_arch"]

            test_id = ws_post(args.url, **get_fields)

            if not test_id.isdigit():
                raise RuntimeError(f"gettestid returned: {test_id!r}")

            # 2. Submit each suite result.
            for suite in suites:
                suite_id = ws_post(
                    args.url,
                    sourceid=args.sourceid,
                    password=args.password,
                    action="getsuiteid",
                    module=suite["module"],
                    test=suite["test"],
                )

                if not suite_id.isdigit():
                    raise RuntimeError(f"getsuiteid returned: {suite_id!r}")

                log = suite["log"]

                result = ws_post(
                    args.url,
                    sourceid=args.sourceid,
                    password=args.password,
                    action="submit",
                    testid=test_id,
                    suiteid=suite_id,
                    log=log,
                )

                if result != "OK":
                    raise RuntimeError(f"submit returned: {result!r}")

            # 3. Mark the run as finished.
            result = ws_post(
                args.url,
                sourceid=args.sourceid,
                password=args.password,
                action="finish",
                testid=test_id,
            )

            if result != "OK":
                raise RuntimeError(f"finish returned: {result!r}")

            submitted += 1
            print(f"  [{run['id']}] {revision} / {platform} — {len(suites)} suites submitted")

        except Exception as exc:
            failed += 1
            print(f"  [{run['id']}] {revision} / {platform} — FAILED: {exc}")

    print(f"\nDone: {submitted} submitted, {failed} failed.")


if __name__ == "__main__":
    main()
