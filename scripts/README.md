# Scripts

Utilities for populating a local Docker Testman **or** the **lab VPS** with data from the live ReactOS server.

## Lab server (this project)

| Item | Value |
|------|--------|
| SSH | `ssh darkfire@216.128.144.135` |
| Testman UI | http://216.128.144.135/testman/ |
| Webservice URL (for `submit_builds.py`, curl) | `http://216.128.144.135/testman/webservice/index.php` |
| On-server DB config (typical) | `/srv/www/www.reactos.org_config/testman-connect.php` |

### Copy scripts + JSON to the lab, then submit over SSH

From **Windows** (PowerShell), repo path adjusted if yours differs:

```powershell
cd C:\Users\DarkFire\Desktop\WebsiteNew\web\scripts
python -m pip install requests pymysql
python fetch_builds.py --base-url https://reactos.org --count 80 --suites 8 --delay 0.25 --output builds_data.json

scp builds_data.json submit_builds.py backport_testman_run_metadata.py darkfire@216.128.144.135:/home/darkfire/
```

On the **server**:

```bash
ssh darkfire@216.128.144.135
python3 -m pip install --user requests pymysql
cd /home/darkfire

python3 submit_builds.py \
  --input builds_data.json \
  --url http://127.0.0.1/testman/webservice/index.php \
  --sourceid 1 \
  --password '51505150'

python3 backport_testman_run_metadata.py \
  --config /srv/www/www.reactos.org_config/testman-connect.php
```

Submit from your **PC** against the public URL (no SSH) if the host is reachable:

```powershell
python submit_builds.py `
  --input builds_data.json `
  --url http://216.128.144.135/testman/webservice/index.php `
  --sourceid 1 `
  --password '51505150'
```

For this **educational VM** repo, MySQL users and the default Testman source share **`51505150`**: put that in `TESTMAN_DB_PASS` on the server and use `UPDATE sources SET password = MD5('51505150') WHERE id = 1` if the row still uses another secret. `submit_builds.py` defaults to `--password 51505150`.

On **Windows**, use `python` (not `py`) for the commands in this README.

## Requirements

```bash
pip install requests pymysql
```

## Workflow (Docker on your machine)

### 1. Fetch data from the live server

```bash
python fetch_builds.py [--base-url https://reactos.org] [--count N] [--output FILE] [--delay SECS] [--suites N]
```

Queries Testman (default **reactos.org**) and saves test run data locally as JSON.

For each run it fetches:

- Run metadata (source, revision, comment) via `ajax-search.php` and `export.php`
- **`platform` in the JSON is the compact value from `export.php`** (same as the DB / webservice), not the long `GetPlatformString()` text from the search list. `--platform-display-contains` only filters on that display text.
- The raw log for every suite result via `detail.php`

| Option | Default | Description |
|--------|---------|-------------|
| `--base-url` | `https://reactos.org` | Testman site root |
| `--count` | 50 | Number of test runs to fetch |
| `--output` | `builds_data.json` | Output file |
| `--delay` | 0.2 | Seconds between requests (be polite to the live server) |
| `--suites` | 10 | Max suite logs per run |

Each run can have many suite results, so the total number of HTTP requests is
roughly `count × suites_per_run`. Increase `--delay` if fetching large counts.

**More variety (arches / platforms / builders):** pass the same filters Testman’s search uses:

| Option | Example | Meaning |
|--------|---------|--------|
| `--platform` | `reactos.0` | ReactOS **i386** runs (`reactos.9` ≈ amd64) |
| `--platform` | `Windows` | Host OS name prefix (matches `platform LIKE 'Windows%'`) |
| `--arches` | `i386,amd64` | Effective arch facet (`ajax-search` `arches=`) |
| `--source-ids` | `1,2` | Only those `sources.id` values on the upstream server |
| `--platform-display-contains` | `AMD64` | Client-side filter on the **human-readable** platform in search XML (fixes empty `builds_amd64.json` when `--platform reactos.9` / `--arches amd64` match nothing) |
| `--source-display-contains` | `KVM` | Client-side filter on builder `<source>` name (e.g. `Test_KVM` on reactos.org) |

Example: KVM x64 builder runs only (no Windows-only bias from `AMD64` alone):

```powershell
python fetch_builds.py --count 80 --source-display-contains KVM --platform-display-contains AMD64 --output builds_kvm_amd64.json
```

**Why `builds_amd64.json` can be empty:** `ajax-search` lists platforms with `GetPlatformString()` (e.g. `Windows Server 2008 … AMD64`), but `platform=` and `arches=` filter on **raw** DB values. Windows amd64 rows often have **no** effective `target_arch` in SQL, so `arches=amd64` returns no rows; `reactos.9` is empty if the live site has few amd64 ReactOS runs. Use **`--platform-display-contains AMD64`** (no server filter) to page through mixed results and keep amd64-looking rows.

Typical pattern: fetch several JSON files (or one big `--count`), then submit each:

```powershell
python fetch_builds.py --count 60 --platform reactos.0 --output builds_i386.json
python fetch_builds.py --count 60 --platform-display-contains AMD64 --output builds_amd64.json
python submit_builds.py --input builds_i386.json --url http://216.128.144.135/testman/webservice/index.php --password 51505150
python submit_builds.py --input builds_amd64.json --url http://216.128.144.135/testman/webservice/index.php --password 51505150
```

After import, run `backport_testman_run_metadata.py` on the server so `compiler` / `vm` / `host_os` / `target_arch` fill in where the script can infer them.

### 2. Start Docker

```bash
cd …/web
docker compose up
```

### 3. Submit data to the local Docker instance

```bash
python submit_builds.py [--input FILE] [--url URL] [--sourceid N] [--password PW]
```

Replays each stored run through the testman webservice HTTP API:
`gettestid` → `getsuiteid` → `submit` → `finish`

| Option | Default | Description |
|--------|---------|-------------|
| `--input` | `builds_data.json` | Input file from fetch step |
| `--url` | `http://localhost/testman/webservice/index.php` | Testman webservice URL |
| `--sourceid` | `1` | Source ID to authenticate as |
| `--password` | `51505150` | Source password (matches Docker `sources` row) |

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

On **darkfire@216.128.144.135**, use:

```bash
python3 backport_testman_run_metadata.py --config /srv/www/www.reactos.org_config/testman-connect.php
```

Edit `MANUAL_SOURCE_OVERRIDES` inside `backport_testman_run_metadata.py` for sources whose names do not
match the built-in heuristics (e.g. `"Lab Buildbot"`).

## Second “builder” on the lab (optional UI test)

```bash
sudo mysql testman -e "
INSERT INTO sources (name, password)
SELECT 'Second lab bot', password FROM sources WHERE id = 1 LIMIT 1;
SELECT id, name FROM sources;
"
# Use the new id as --sourceid, then:
python3 submit_builds.py --input builds_data.json \
  --url http://127.0.0.1/testman/webservice/index.php \
  --sourceid 2 \
  --password '51505150'
python3 backport_testman_run_metadata.py --config /srv/www/www.reactos.org_config/testman-connect.php
```

## Re-running

`submit_builds.py` is not idempotent — submitting the same run twice will
create duplicate entries. Reset the testman database between runs with:

```bash
docker compose down -v && docker compose up
```
