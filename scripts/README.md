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
py -m pip install requests pymysql
py fetch_builds.py --base-url https://reactos.org --count 80 --suites 8 --delay 0.25 --output builds_data.json

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
py submit_builds.py `
  --input builds_data.json `
  --url http://216.128.144.135/testman/webservice/index.php `
  --sourceid 1 `
  --password '51505150'
```

For this **educational VM** repo, MySQL users and the default Testman source share **`51505150`**: put that in `TESTMAN_DB_PASS` on the server and use `UPDATE sources SET password = MD5('51505150') WHERE id = 1` if the row still uses another secret. `submit_builds.py` defaults to `--password 51505150`.

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

- Run metadata (source, revision, platform, comment) via `ajax-search.php` and `export.php`
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
