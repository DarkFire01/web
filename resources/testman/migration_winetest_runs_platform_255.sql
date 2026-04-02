-- =============================================================================
-- Testman: widen winetest_runs.platform (legacy was VARCHAR(24))
-- =============================================================================
-- Long host descriptions from WineTest (e.g. "Windows Server 2008 - Build ...")
-- exceed 24 characters. Run once on existing DBs:
--
--   sudo mysql testman < migration_winetest_runs_platform_255.sql
-- =============================================================================

USE `testman`;

ALTER TABLE `winetest_runs`
  MODIFY `platform` varchar(255) COLLATE latin1_general_ci NOT NULL;
