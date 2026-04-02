-- =============================================================================
-- Testman: extend winetest_runs (todo/skipped rollups, build_number, facets)
-- =============================================================================
-- Run once against the `testman` database after deploying the new PHP.
--
-- Example (as root / DBA):
--   mysql testman < /path/to/migration_winetest_runs_extend.sql
--   # or:
--   sudo mysql testman < /srv/www/.../migration_winetest_runs_extend.sql
--
-- If this errors with "Duplicate column" or "Duplicate key", the migration
-- already ran (or partially ran); fix manually with SHOW COLUMNS / SHOW INDEX.
-- =============================================================================

USE `testman`;

ALTER TABLE `winetest_runs`
  ADD COLUMN `todo` int(10) unsigned NOT NULL DEFAULT '0' AFTER `failures`,
  ADD COLUMN `skipped` int(10) unsigned NOT NULL DEFAULT '0' AFTER `todo`,
  ADD COLUMN `build_number` int(10) unsigned DEFAULT NULL AFTER `skipped`,
  ADD COLUMN `compiler` varchar(32) COLLATE latin1_general_ci DEFAULT NULL AFTER `build_number`,
  ADD COLUMN `vm` varchar(32) COLLATE latin1_general_ci DEFAULT NULL AFTER `compiler`,
  ADD COLUMN `host_os` varchar(32) COLLATE latin1_general_ci DEFAULT NULL AFTER `vm`,
  ADD COLUMN `target_arch` varchar(16) COLLATE latin1_general_ci DEFAULT NULL AFTER `host_os`,
  ADD KEY `idx_winetest_runs_timestamp` (`timestamp`),
  ADD KEY `idx_winetest_runs_build_number` (`build_number`),
  ADD KEY `idx_winetest_runs_compiler` (`compiler`),
  ADD KEY `idx_winetest_runs_vm` (`vm`),
  ADD KEY `idx_winetest_runs_host_os` (`host_os`),
  ADD KEY `idx_winetest_runs_target_arch` (`target_arch`);

UPDATE `winetest_runs` r
SET
  r.todo = (SELECT COALESCE(SUM(wr.todo), 0) FROM winetest_results wr WHERE wr.test_id = r.id),
  r.skipped = (SELECT COALESCE(SUM(wr.skipped), 0) FROM winetest_results wr WHERE wr.test_id = r.id)
WHERE r.finished = 1;

-- Optional: backfill build_number from comment text like "Build 123, ..." (submit_result format)
UPDATE `winetest_runs`
SET `build_number` = CAST(SUBSTRING_INDEX(SUBSTRING_INDEX(`comment`, 'Build ', -1), ',', 1) AS UNSIGNED)
WHERE `build_number` IS NULL
  AND `comment` LIKE 'Build %'
  AND SUBSTRING_INDEX(SUBSTRING_INDEX(`comment`, 'Build ', -1), ',', 1) REGEXP '^[0-9]+$';
