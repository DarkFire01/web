<?php
/*
 * PROJECT:     ReactOS Testman
 * LICENSE:     GPL-2.0-or-later (https://spdx.org/licenses/GPL-2.0-or-later)
 * PURPOSE:     Optional Buildbot builder ID → compiler / VM / OS / arch defaults
 * COPYRIGHT:   Copyright 2026 ReactOS Contributors
 *
 * Extend $TESTMAN_BUILDER_META on deployment so it matches build.reactos.org builder IDs.
 */

	function testman_sanitize_meta_token($value)
	{
		if (!is_string($value) || $value === "")
			return null;

		if (!preg_match("/^[a-zA-Z0-9_.-]{1,32}$/", $value))
			return null;

		return $value;
	}

	/**
	 * @return array{compiler: ?string, vm: ?string, host_os: ?string, target_arch: ?string}
	 */
	function testman_meta_for_builder_id($builder_id)
	{
		$TESTMAN_BUILDER_META = array(
			// Example entries — set real IDs to match your Buildbot installation.
			// 1 => array("compiler" => "GCC", "vm" => "KVM", "host_os" => "Linux", "target_arch" => "i386"),
		);

		if (!isset($TESTMAN_BUILDER_META[$builder_id]))
			return array("compiler" => null, "vm" => null, "host_os" => null, "target_arch" => null);

		$row = $TESTMAN_BUILDER_META[$builder_id];
		return array(
			"compiler" => isset($row["compiler"]) ? testman_sanitize_meta_token($row["compiler"]) : null,
			"vm" => isset($row["vm"]) ? testman_sanitize_meta_token($row["vm"]) : null,
			"host_os" => isset($row["host_os"]) ? testman_sanitize_meta_token($row["host_os"]) : null,
			"target_arch" => isset($row["target_arch"]) ? testman_sanitize_meta_token($row["target_arch"]) : null,
		);
	}
