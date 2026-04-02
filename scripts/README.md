# Scripts

Utilities for populating the local Docker environment with data from the live ReactOS server.

## Requirements

```bash
pip install requests pymysql
```

## Workflow

### 1. Fetch data from the live server

```bash
python fetch_builds.py [--count N] [--output FILE] [--delay SECS]
```

Queries the live Testman at reactos.org and saves test run data locally as JSON.

For each run it fetches:
- Run metadata (source, revision, platform, comment) via `ajax-search.php` and `export.php`
- The raw log for every suite result via `detail.php`

| Option | Default | Description |
|--------|---------|-------------|
| `--count` | 50 | Number of test runs to fetch |
| `--output` | `builds_data.json` | Output file |
| `--delay` | 0.2 | Seconds between requests (be polite to the live server) |

Each run can have many suite results, so the total number of HTTP requests is
roughly `count × suites_per_run`. Increase `--delay` if fetching large counts.

### 2. Start Docker

```bash
docker compose up
```

### 3. Submit data to the local Docker instance

```bash
python submit_builds.py [--input FILE] [--url URL] [--sourceid N] [--password PW]
```

Replays each stored run through the testman webservice HTTP API:
`gettestid` → `getsuiteid` → `submit` → `finish`

The actual logs fetched from the live server are submitted as-is, so the local
instance ends up with identical data to what was on the live server.

| Option | Default | Description |
|--------|---------|-------------|
| `--input` | `builds_data.json` | Input file from fetch step |
| `--url` | `http://localhost/testman/webservice/index.php` | Testman webservice URL |
| `--sourceid` | `1` | Source ID to authenticate as |
| `--password` | `testpassword` | Source password |

The default credentials match the test source added to the Docker database by
`docker/mysql/init.sql`. If the database was already initialised without that
row, reset it with:

```bash
docker compose down -v && docker compose up
```

## Backfill metadata on existing rows (Python)

After importing runs (e.g. with `submit_builds.py`) or upgrading the schema,
facet columns may be NULL while `platform` / `comment` / `sources.name` carry
enough information to fill them. This script updates `winetest_runs` in place:

```bash
pip install pymysql
python backport_testman_run_metadata.py --config ../www/www.reactos.org_config/testman-connect.php
python backport_testman_run_metadata.py --dry-run   # preview only
```

On a VPS, point `--config` at your real `testman-connect.php`. Edit
`MANUAL_SOURCE_OVERRIDES` inside the script for sources whose names do not
match the built-in heuristics (e.g. `"Lab Buildbot"`).

## Re-running

`submit_builds.py` is not idempotent — submitting the same run twice will
create duplicate entries. Reset the testman database between runs with:

```bash
docker compose down -v && docker compose up
```
