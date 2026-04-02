<?php
/*
 * PROJECT:     ReactOS Testman
 * LICENSE:     GPL-2.0-or-later (https://spdx.org/licenses/GPL-2.0-or-later)
 * PURPOSE:     Facet column helpers for search filters (compiler / VM / OS / arch)
 * COPYRIGHT:   Copyright 2026 ReactOS Contributors
 */

	function testman_facet_columns()
	{
		return array("compiler", "vm", "host_os", "target_arch");
	}

	function testman_merge_facet_values(PDO $dbh, $column)
	{
		$allowed = testman_facet_columns();
		if (!in_array($column, $allowed, true))
			throw new InvalidArgumentException("Invalid facet column");

		// Only values that actually appear in the DB. Merging canonical presets caused
		// extra checkboxes (e.g. Win2003_x64) with no rows; unchecking one sent IN (...)
		// and excluded every run with NULL in that column → zero results.
		$stmt = $dbh->query(
			"SELECT DISTINCT `" . $column . "` AS v FROM winetest_runs WHERE finished = 1 AND `" . $column . "` IS NOT NULL AND `" . $column . "` != '' ORDER BY v"
		);
		$db = $stmt ? $stmt->fetchAll(PDO::FETCH_COLUMN, 0) : array();
		return array_values(array_unique($db));
	}

	/**
	 * SQL fragment: effective arch (target_arch column if set, else i386/amd64 from reactos.N platform).
	 * Expects alias r for winetest_runs.
	 */
	function testman_sql_effective_target_arch_expr()
	{
		return "COALESCE(NULLIF(TRIM(r.target_arch), ''), " .
			"CASE WHEN r.platform LIKE 'reactos.%' THEN " .
			"CASE SUBSTRING_INDEX(r.platform, '.', -1) WHEN '0' THEN 'i386' WHEN '9' THEN 'amd64' ELSE NULL END " .
			"ELSE NULL END)";
	}

	/** Distinct effective arch values for filter UI (includes reactos.* when target_arch is NULL). */
	function testman_merge_arch_facet_values(PDO $dbh)
	{
		$e = testman_sql_effective_target_arch_expr();
		$stmt = $dbh->query(
			"SELECT DISTINCT sub.v FROM (" .
			" SELECT (" . $e . ") AS v FROM winetest_runs r WHERE r.finished = 1" .
			") sub WHERE sub.v IS NOT NULL AND sub.v != '' ORDER BY sub.v"
		);
		$rows = $stmt ? $stmt->fetchAll(PDO::FETCH_COLUMN, 0) : array();
		return array_values(array_unique($rows));
	}
