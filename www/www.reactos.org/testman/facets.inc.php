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

	function testman_canonical_facets()
	{
		return array(
			"compiler" => array("GCC", "MSVC"),
			"vm" => array("KVM", "VBox", "WHS", "Win2003_x64"),
			"host_os" => array("Linux", "Windows", "ReactOS"),
			"target_arch" => array("i386", "amd64"),
		);
	}

	function testman_merge_facet_values(PDO $dbh, $column)
	{
		$allowed = testman_facet_columns();
		if (!in_array($column, $allowed, true))
			throw new InvalidArgumentException("Invalid facet column");

		$canonical = testman_canonical_facets();
		$base = isset($canonical[$column]) ? $canonical[$column] : array();

		$stmt = $dbh->query(
			"SELECT DISTINCT `" . $column . "` AS v FROM winetest_runs WHERE finished = 1 AND `" . $column . "` IS NOT NULL AND `" . $column . "` != '' ORDER BY v"
		);
		$db = $stmt ? $stmt->fetchAll(PDO::FETCH_COLUMN, 0) : array();
		$merged = array_values(array_unique(array_merge($base, $db)));
		sort($merged);
		return $merged;
	}
