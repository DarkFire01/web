<?php
/*
 * PROJECT:     ReactOS Testman
 * LICENSE:     GPL-2.0+ (https://spdx.org/licenses/GPL-2.0+)
 * PURPOSE:     AJAX Backend for the Search feature
 * COPYRIGHT:   Copyright 2008-2017 Colin Finck (colin@reactos.org)
 *              Copyright 2026 ReactOS Contributors
 */

	header("Content-type: text/xml");

	require_once("config.inc.php");
	require_once(ROOT_PATH . "../www.reactos.org_config/testman-connect.php");
	require_once("utils.inc.php");
	require_once("facets.inc.php");
	require_once(ROOT_PATH . "rosweb/exceptions.php");
	require_once(ROOT_PATH . "rosweb/gitinfo.php");
	require_once(ROOT_PATH . "rosweb/rosweb.php");

	function testman_parse_datetime_input($s, $end_of_day)
	{
		$s = trim((string)$s);
		if ($s === "")
			return null;

		$dt = DateTime::createFromFormat("Y-m-d H:i", $s);
		if (!$dt)
			$dt = DateTime::createFromFormat("Y-m-d", $s);
		if (!$dt)
			return null;

		if ($end_of_day && preg_match("/^[0-9]{4}-[0-9]{2}-[0-9]{2}$/", $s))
			$dt->setTime(23, 59, 59);

		return $dt;
	}

	function testman_ajax_apply_dimension(PDO $dbh, $get_key, $column, &$where, &$params)
	{
		if (!isset($_GET[$get_key]))
			return;

		$raw = $_GET[$get_key];
		if ($raw === "")
			return;

		$req = array_filter(array_map("trim", explode(",", $raw)));
		$full = testman_merge_facet_values($dbh, $column);
		if (count($full) === 0)
			return;

		$sel = array_values(array_intersect($req, $full));

		if (count($sel) === 0)
		{
			$where[] = "0=1";
			return;
		}

		if (count($sel) === count($full))
			return;

		$placeholders = implode(",", array_fill(0, count($sel), "?"));
		// Strict match: NULL/empty host_os/compiler/vm must be backfilled (see backport script)
		// or they do not match any ticked value — otherwise "uncheck Windows" still shows Win runs.
		$where[] = "r.`" . $column . "` IN (" . $placeholders . ")";
		foreach ($sel as $v)
			$params[] = $v;
	}

	function testman_ajax_apply_arch_filter(PDO $dbh, &$where, &$params)
	{
		$get_key = "arches";

		if (!isset($_GET[$get_key]))
			return;

		$raw = $_GET[$get_key];
		if ($raw === "")
			return;

		$req = array_filter(array_map("trim", explode(",", $raw)));
		$full = testman_merge_arch_facet_values($dbh);
		if (count($full) === 0)
			return;

		$sel = array_values(array_intersect($req, $full));

		if (count($sel) === 0)
		{
			$where[] = "0=1";
			return;
		}

		if (count($sel) === count($full))
			return;

		$eff = testman_sql_effective_target_arch_expr();
		$placeholders = implode(",", array_fill(0, count($sel), "?"));
		$where[] = "(" . $eff . ") IN (" . $placeholders . ")";
		foreach ($sel as $v)
			$params[] = $v;
	}

	$rw = new RosWeb();
	$lang = $rw->getLanguage();
	require_once(ROOT_PATH . "rosweb/lang/$lang.inc.php");

	try
	{
		if (!array_key_exists("page", $_GET))
			throw new ErrorMessageException("Necessary information not specified");

		$page = (int)$_GET["page"];
		if ($page < 1)
			throw new RuntimeException("page is out of range");

		$gi = new GitInfo();

		$dbh = new PDO("mysql:host=" . TESTMAN_DB_HOST . ";dbname=" . TESTMAN_DB_NAME, TESTMAN_DB_USER, TESTMAN_DB_PASS);
		$dbh->setAttribute(PDO::ATTR_ERRMODE, PDO::ERRMODE_EXCEPTION);

		$where = array("r.finished = 1");
		$params = array();

		$all_source_ids = $dbh->query("SELECT id FROM sources ORDER BY id")->fetchAll(PDO::FETCH_COLUMN, 0);

		if (array_key_exists("source_ids", $_GET) && $_GET["source_ids"] !== "")
		{
			$ids = array_unique(array_map("intval", explode(",", $_GET["source_ids"])));
			$ids = array_values(array_intersect($ids, $all_source_ids));

			if (count($ids) === 0)
				$where[] = "0=1";
			elseif (count($ids) < count($all_source_ids))
			{
				$where[] = "r.source_id IN (" . implode(",", $ids) . ")";
			}
		}

		if (array_key_exists("source", $_GET) && $_GET["source"] !== "")
			$where[] = "src.name LIKE " . $dbh->quote("%" . $_GET["source"] . "%");

		if (array_key_exists("startrev", $_GET) && array_key_exists("endrev", $_GET) && $_GET["startrev"] !== "" && $_GET["endrev"] !== "")
		{
			$startrev = $_GET["startrev"];
			$endrev = $_GET["endrev"];
			$git_hex = '/^[0-9a-f]{7,40}$/i';

			if (preg_match($SVN_PATTERN, $startrev) && preg_match($SVN_PATTERN, $endrev))
			{
				$range = range((int)$startrev, (int)$endrev);
				if (count($range) > REV_RANGE_LIMIT)
					throw new RuntimeException(sprintf($shared_langres["rangelimitexceeded"], REV_RANGE_LIMIT));

				$quoted = array();
				foreach ($range as $h)
					$quoted[] = $dbh->quote((string)$h);

				$where[] = "r.revision IN (" . implode(",", $quoted) . ")";
			}
			else
			{
				$start_hash = $gi->getLongHash($startrev);
				$end_hash = $gi->getLongHash($endrev);

				if ($start_hash && $end_hash)
				{
					$range = $gi->getRevisionRange($start_hash, $end_hash);
					if (count($range) > REV_RANGE_LIMIT)
						throw new RuntimeException(sprintf($shared_langres["rangelimitexceeded"], REV_RANGE_LIMIT));

					$quoted = array();
					foreach ($range as $h)
						$quoted[] = $dbh->quote($h);

					$where[] = "r.revision IN (" . implode(",", $quoted) . ")";
				}
				elseif (preg_match($git_hex, $startrev) && preg_match($git_hex, $endrev))
				{
					// Gitinfo DB often lacks full history on lab mirrors; short hashes from the UI still work via prefix.
					if (strcasecmp($startrev, $endrev) === 0)
					{
						$where[] = "r.revision LIKE ?";
						$params[] = $startrev . '%';
					}
					else
					{
						$where[] = "(r.revision LIKE ? OR r.revision LIKE ?)";
						$params[] = $startrev . '%';
						$params[] = $endrev . '%';
					}
				}
				else
				{
					throw new RuntimeException($shared_langres["invalidinput"]);
				}
			}
		}

		if (array_key_exists("platform", $_GET) && $_GET["platform"] !== "")
			$where[] = "r.platform LIKE " . $dbh->quote($_GET["platform"] . "%");

		$df = array_key_exists("date_from", $_GET) ? testman_parse_datetime_input($_GET["date_from"], false) : null;
		if ($df)
		{
			$where[] = "r.timestamp >= ?";
			$params[] = $df->format("Y-m-d H:i:s");
		}

		$dt = array_key_exists("date_to", $_GET) ? testman_parse_datetime_input($_GET["date_to"], true) : null;
		if ($dt)
		{
			$where[] = "r.timestamp <= ?";
			$params[] = $dt->format("Y-m-d H:i:s");
		}

		if (array_key_exists("search_comment", $_GET) && $_GET["search_comment"] !== "")
		{
			$where[] = "r.comment LIKE ?";
			$needle = "%" . str_replace(array("\\", "%", "_"), array("\\\\", "\\%", "\\_"), $_GET["search_comment"]) . "%";
			$params[] = $needle;
		}

		if (array_key_exists("build_number", $_GET) && $_GET["build_number"] !== "")
		{
			$bn = (int)$_GET["build_number"];
			if ($bn > 0)
			{
				$where[] = "r.build_number = ?";
				$params[] = $bn;
			}
		}

		testman_ajax_apply_dimension($dbh, "compilers", "compiler", $where, $params);
		testman_ajax_apply_dimension($dbh, "vms", "vm", $where, $params);
		testman_ajax_apply_dimension($dbh, "host_oses", "host_os", $where, $params);
		testman_ajax_apply_arch_filter($dbh, $where, $params);

		if (array_key_exists("limit", $_GET))
		{
			$limit = (int)$_GET["limit"];
			if ($limit < 1)
				throw new RuntimeException("limit is out of range");

			$limit_count = min(RESULTS_PER_PAGE, $limit);
		}
		else
		{
			$limit_count = RESULTS_PER_PAGE;
		}

		$where_sql = implode(" AND ", $where);
		$base_from = "FROM winetest_runs r JOIN sources src ON r.source_id = src.id WHERE " . $where_sql;

		$output = "<results>";

		$stmt = $dbh->prepare("SELECT COUNT(*) " . $base_from);
		$stmt->execute($params);
		$total_matches = (int)$stmt->fetchColumn();

		$limit_offset = ($page - 1) * RESULTS_PER_PAGE;
		$result_count = max(0, $total_matches - $limit_offset);

		if (isset($limit) && $result_count > $limit)
			$result_count = $limit;

		if ($result_count)
		{
			$order = array_key_exists("desc", $_GET) ? "DESC" : "ASC";
			$limit_offset = (int)$limit_offset;
			$limit_count = (int)$limit_count;

			if (array_key_exists("resultlist", $_GET))
			{
				$sql = "SELECT r.id, UNIX_TIMESTAMP(r.timestamp) AS timestamp, src.name, r.revision, r.platform, r.comment, r.count, r.failures, r.todo " .
					$base_from . " ORDER BY r.id " . $order . " LIMIT $limit_offset, $limit_count";

				$stmt = $dbh->prepare($sql);
				$stmt->execute($params);

				while (($row = $stmt->fetch(PDO::FETCH_ASSOC)) !== false)
				{
					$output .= "<result>";
					$output .= "<id>" . $row["id"] . "</id>";
					$output .= "<date>" . GetDateString($row["timestamp"]) . "</date>";
					$output .= "<source>" . htmlspecialchars($row["name"]) . "</source>";
					$output .= "<revision>" . $gi->getShortHash($row["revision"]) . "</revision>";
					$output .= "<platform>" . GetPlatformString($row["platform"]) . "</platform>";
					$output .= "<comment>" . htmlspecialchars($row["comment"]) . "</comment>";
					$output .= "<count>" . $row["count"] . "</count>";
					$output .= "<failures>" . $row["failures"] . "</failures>";
					$output .= "<todo>" . (int)$row["todo"] . "</todo>";
					$output .= "</result>";

					if (!isset($first_revision))
						$first_revision = $gi->getShortHash($row["revision"]);

					$last_revision = $gi->getShortHash($row["revision"]);
				}
			}
			else
			{
				$sql = "SELECT r.revision " . $base_from . " ORDER BY r.id " . $order . " LIMIT $limit_offset, 1";
				$stmt = $dbh->prepare($sql);
				$stmt->execute($params);
				$first_revision = $gi->getShortHash($stmt->fetchColumn());

				$sql = "SELECT r.revision " . $base_from . " ORDER BY r.id " . $order . " LIMIT " . ($limit_offset + $limit_count - 1) . ", 1";
				$stmt = $dbh->prepare($sql);
				$stmt->execute($params);
				$last_revision = $gi->getShortHash($stmt->fetchColumn());
			}

			$output .= "<firstrev>$first_revision</firstrev>";
			$output .= "<lastrev>$last_revision</lastrev>";
		}

		$output .= "<resultcount>$result_count</resultcount>";
		$output .= "</results>";
		die($output);
	}
	catch (ErrorMessageException $e)
	{
		die("<error>" . $e->getMessage() . "</error>");
	}
	catch (Exception $e)
	{
		die("<error>" . $e->getFile() . ":" . $e->getLine() . " - " . $e->getMessage() . "</error>");
	}
