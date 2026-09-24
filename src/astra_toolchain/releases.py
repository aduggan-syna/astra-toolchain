# Copyright 2026 Synaptics Inc.
#
# Licensed under the Apache License v2.0
# SPDX-License-Identifier: Apache-2.0

"""Discovery and download of Astra SDK toolchains from GitHub releases."""

from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from astra_toolchain.naming import ToolchainSpec, host_arch, parse_asset

SDK_REPO = "synaptics-astra/sdk"
GITHUB_API = "https://api.github.com/repos/{}/releases".format(SDK_REPO)

# Only these hosts are accepted for asset downloads, including the URLs that are
# read out of the upstream "get_*_toolchain.sh" helper scripts.
ALLOWED_HOSTS = frozenset(
    {
        "github.com",
        "api.github.com",
        "objects.githubusercontent.com",
        "release-assets.githubusercontent.com",
    }
)

_WGET_URL_RE = re.compile(r'^\s*wget\s+(?:-\S+\s+)*"?(?P<url>https://\S+?)"?\s*$', re.M)
_FILE_RE = re.compile(r'^FILE="(?P<file>[^"]+)"\s*$', re.M)
_MD5_RE = re.compile(r'^EXPECTED_MD5="(?P<md5>[0-9a-fA-F]{32})"\s*$', re.M)


class ReleaseError(RuntimeError):
    pass


@dataclass
class RemoteToolchain:
    spec: ToolchainSpec
    url: str
    is_wrapper: bool


def _check_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ReleaseError("Refusing to download from untrusted URL: {}".format(url))
    return url


def _open(url: str, token: Optional[str] = None, accept: Optional[str] = None):
    headers = {"User-Agent": "astra-toolchain"}
    if accept:
        headers["Accept"] = accept
    if token:
        headers["Authorization"] = "Bearer {}".format(token)
    request = urllib.request.Request(_check_url(url), headers=headers)
    return urllib.request.urlopen(request, timeout=120)  # noqa: S310 - scheme/host checked


def github_token() -> Optional[str]:
    return os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")


def fetch_releases(token: Optional[str] = None, max_pages: int = 5) -> List[dict]:
    """Return the SDK releases, newest first."""
    token = token or github_token()
    releases: List[dict] = []
    for page in range(1, max_pages + 1):
        url = "{}?per_page=100&page={}".format(GITHUB_API, page)
        try:
            with _open(url, token, "application/vnd.github+json") as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as error:
            raise ReleaseError(
                "GitHub API request failed ({}). Set GITHUB_TOKEN if you are rate limited.".format(
                    error.code
                )
            ) from error
        if not payload:
            break
        releases.extend(payload)
    if not releases:
        raise ReleaseError("No releases found for {}".format(SDK_REPO))
    return releases


def select_release(releases: List[dict], tag: Optional[str] = None) -> dict:
    if tag:
        for release in releases:
            if release.get("tag_name") == tag:
                return release
        raise ReleaseError("Release '{}' not found".format(tag))
    for release in releases:
        if not release.get("draft") and not release.get("prerelease"):
            return release
    return releases[0]


def toolchains_in_release(release: dict) -> Dict[Tuple[str, str], RemoteToolchain]:
    """Map (machine, image) to the best download candidate in a release."""
    found: Dict[Tuple[str, str], RemoteToolchain] = {}
    tag = release.get("tag_name")
    local_arch = host_arch()
    for asset in release.get("assets", []):
        name = asset.get("name", "")
        spec = parse_asset(name, tag)
        if spec is None:
            continue
        candidate = RemoteToolchain(
            spec=spec,
            url=asset["browser_download_url"],
            is_wrapper=spec.installer is None,
        )
        key = (spec.machine, spec.image)
        previous = found.get(key)
        if previous is None or _better_candidate(candidate, previous, local_arch):
            found[key] = candidate
    return found


def _better_candidate(candidate: RemoteToolchain, previous: RemoteToolchain, local_arch: str) -> bool:
    """True if ``candidate`` should replace ``previous`` for the same machine/image."""
    # Prefer a toolchain built for this host's architecture, then a direct
    # installer over the split-file helper script.
    candidate_native = candidate.spec.host_arch == local_arch
    previous_native = previous.spec.host_arch == local_arch
    if candidate_native != previous_native:
        return candidate_native
    return previous.is_wrapper and not candidate.is_wrapper


def find_toolchain(
    machine: str,
    image: str,
    release_tag: Optional[str] = None,
    token: Optional[str] = None,
) -> RemoteToolchain:
    releases = fetch_releases(token)
    release = select_release(releases, release_tag)
    toolchains = toolchains_in_release(release)
    key = (machine, image)
    if key not in toolchains:
        available = ", ".join(sorted("{}/{}".format(*k) for k in toolchains))
        raise ReleaseError(
            "No toolchain for {}/{} in {}. Available: {}".format(
                machine, image, release["tag_name"], available or "none"
            )
        )
    return toolchains[key]


def _download(url: str, destination: str, token: Optional[str] = None, append: bool = False) -> None:
    mode = "ab" if append else "wb"
    with _open(url, token) as response, open(destination, mode) as output:
        total = response.headers.get("Content-Length")
        total = int(total) if total else 0
        done = 0
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            output.write(chunk)
            done += len(chunk)
            if total and sys.stderr.isatty():
                sys.stderr.write(
                    "\r  {:>6.1f}% of {:.0f} MiB".format(done * 100.0 / total, total / 1048576.0)
                )
                sys.stderr.flush()
        if total and sys.stderr.isatty():
            sys.stderr.write("\n")


def _md5(path: str) -> str:
    digest = hashlib.md5()  # noqa: S324 - upstream publishes md5 only
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_toolchain(
    remote: RemoteToolchain, directory: str, token: Optional[str] = None
) -> str:
    """Download the toolchain installer into ``directory`` and return its path."""
    token = token or github_token()
    os.makedirs(directory, exist_ok=True)

    if not remote.is_wrapper:
        target = os.path.join(directory, remote.spec.installer)
        if os.path.exists(target):
            print("Using cached installer {}".format(target))
            return target
        print("Downloading {}".format(remote.spec.installer))
        partial = target + ".part"
        _download(remote.url, partial, token)
        os.replace(partial, target)
        return target

    with _open(remote.url, token) as response:
        script = response.read().decode("utf-8", "replace")

    file_match = _FILE_RE.search(script)
    if not file_match:
        raise ReleaseError("Could not determine the installer name from the release helper script")
    filename = os.path.basename(file_match.group("file"))
    target = os.path.join(directory, filename)
    expected_md5 = _MD5_RE.search(script)
    expected_md5 = expected_md5.group("md5").lower() if expected_md5 else None

    if os.path.exists(target):
        if expected_md5 is None or _md5(target) == expected_md5:
            print("Using cached installer {}".format(target))
            return target
        os.remove(target)

    urls = [_check_url(match.group("url")) for match in _WGET_URL_RE.finditer(script)]
    if not urls:
        raise ReleaseError("The release helper script did not list any download URLs")

    partial = target + ".part"
    if os.path.exists(partial):
        os.remove(partial)
    print("Downloading {} ({} parts)".format(filename, len(urls)))
    for index, url in enumerate(urls, start=1):
        print("  part {}/{}".format(index, len(urls)))
        _download(url, partial, token, append=True)

    if expected_md5 is not None and _md5(partial) != expected_md5:
        os.remove(partial)
        raise ReleaseError("Checksum mismatch for {}".format(filename))
    os.replace(partial, target)
    return target


def find_local_installer(directory: str, machine: Optional[str], image: Optional[str]):
    """Return (path, spec) of a matching toolchain installer already on disk."""
    matches = []
    for entry in sorted(os.listdir(directory)):
        path = os.path.join(directory, entry)
        if not os.path.isfile(path):
            continue
        spec = parse_asset(entry)
        if spec is None or spec.installer is None:
            continue
        if machine and spec.machine != machine:
            continue
        if image and spec.image != image:
            continue
        matches.append((path, spec))
    if not matches:
        return None
    if len(matches) > 1:
        names = ", ".join(os.path.basename(path) for path, _ in matches)
        raise ReleaseError(
            "Multiple toolchain installers found ({}). Use --toolchain, --machine or --image.".format(
                names
            )
        )
    return matches[0]
