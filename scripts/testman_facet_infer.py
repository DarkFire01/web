#!/usr/bin/env python3
"""
Infer Testman facet fields from upstream builder/source display names.

`host_os` is the **OS under test** (guest), not the hypervisor host:
  - Test KVM / KVM_x64 / Test VBox → ReactOS (ISO under test)
  - Test WHS / Win2003_x64 → Windows

Upstream reactos.org sources.name examples:
  "Build GCCLin_x86 on Test KVM"    → GCC, KVM, ReactOS, i386
  "Build MSVC_x64 on Test KVM_x64" → MSVC, KVM, ReactOS, amd64
  "Test WHS"                       → GCC, WHS, Windows, i386
  "Test Win2003_x64"               → MSVC, Win2003_x64, Windows, amd64

Shared by submit_builds.py (JSON "source") and backport_testman_run_metadata.py (DB sources.name).

There is **no** inference for the generic name "Lab Buildbot": if you use one DB source for all
uploads, facets must come from submit_builds (JSON "source") + gettestid meta. Otherwise step [5]
would wrongly force GCC/KVM on WHS/Win2003 rows.

**reactos.0 vs KVM_x64:** Some exports still use the compact platform prefix ``reactos.0`` for jobs that
are actually **amd64 ReactOS** on a **KVM_x64** worker (``Test KVM_x64`` in the builder string).
``normalize_platform_for_amd64_kvm_worker()`` maps those to ``reactos.9`` / ``reactos9`` so Testman
filters and ``GetPlatformString`` match reality. Plain ``Test KVM`` (no ``KVM_x64``) is unchanged.

No DB dependencies.
"""

from __future__ import annotations

import re


def infer_facets_from_source_name(name: str) -> dict[str, str | None]:
    # DB / PHP may include trailing spaces or odd whitespace.
    name = " ".join((name or "").split())
    nf = name.casefold()

    # Exact labels from production Testman (must run before generic "WHS" substring rules).
    if nf == "test whs":
        return {
            "compiler": "GCC",
            "vm": "WHS",
            "host_os": "Windows",
            "target_arch": "i386",
        }
    if nf == "test win2003_x64":
        return {
            "compiler": "MSVC",
            "vm": "Win2003_x64",
            "host_os": "Windows",
            "target_arch": "amd64",
        }

    out: dict[str, str | None] = {
        "compiler": None,
        "vm": None,
        "host_os": None,
        "target_arch": None,
    }

    if "MSVC" in name.upper():
        out["compiler"] = "MSVC"
    elif "GCCLIN" in name.upper() or "GCCWIN" in name.upper() or re.search(r"\bGCC\b", name, re.I):
        out["compiler"] = "GCC"

    un = name.upper()
    if "KVM" in un:
        out["vm"] = "KVM"
    elif "VBOX" in un or "VIRTUALBOX" in un:
        out["vm"] = "VBox"
    elif "WHS" in un:
        out["vm"] = "WHS"
    elif "WIN2003" in un:
        out["vm"] = "Win2003_x64"

    if out["vm"] in ("KVM", "VBox"):
        out["host_os"] = "ReactOS"
    elif out["vm"] in ("WHS", "Win2003_x64"):
        out["host_os"] = "Windows"
    elif "GCCWIN" in un or "WIN7" in un:
        out["host_os"] = "Windows"

    # Builder string arch when platform may be non-reactos.* (WHS / Win2003 handled above).
    if "GCCLIN_X86" in un or "GCCWIN_X86" in un:
        out["target_arch"] = out["target_arch"] or "i386"
    elif "MSVC_X64" in un or "KVM_X64" in un:
        out["target_arch"] = out["target_arch"] or "amd64"

    return out


def is_amd64_kvm_worker_source(name: str) -> bool:
    """True if builder label refers to the KVM_x64 worker (amd64 ReactOS KVM), not plain Test KVM."""
    return bool(re.search(r"kvm[_ ]?x64", name or "", re.I))


def normalize_platform_for_amd64_kvm_worker(platform: str, source: str) -> str:
    """
    If source names KVM_x64 but the stored platform still uses the i386 reactos prefix, rewrite to
    the amd64 prefix (upstream export quirk).
    """
    if not is_amd64_kvm_worker_source(source):
        return (platform or "").strip()
    p = (platform or "").strip()
    if re.match(r"^reactos\.0(\.|$)", p):
        return "reactos.9" + p[9:]
    if re.match(r"^reactos0([^0-9]|$)", p):
        return "reactos9" + p[8:]
    return p


def target_arch_from_platform(platform: str) -> str | None:
    """Match ajax-search / facets.inc: reactos.0 / reactos.9 and rosautotest reactos0 / reactos9."""
    p = (platform or "").strip()
    if re.match(r"^reactos\.0(\.|$)", p):
        return "i386"
    if re.match(r"^reactos\.9(\.|$)", p):
        return "amd64"
    if re.match(r"^reactos0([^0-9]|$)", p):
        return "i386"
    if re.match(r"^reactos9([^0-9]|$)", p):
        return "amd64"
    return None


def build_number_from_comment(comment: str) -> int | None:
    m = re.search(r"\bBuild\s+(\d+)\b", comment or "", re.IGNORECASE)
    if not m:
        return None
    try:
        return int(m.group(1))
    except ValueError:
        return None
