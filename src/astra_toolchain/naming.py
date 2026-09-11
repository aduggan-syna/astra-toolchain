"""Parsing of Astra SDK toolchain asset names and the derived Docker names."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Optional, Tuple

# Yocto release codenames used by the Astra SDK release tags.
CODENAMES = ("scarthgap", "kirkstone", "nanbield", "mickledore", "langdale", "dunfell")

DEFAULT_IMAGE = "default"

# sl1680_oobe_scarthgap-poky-glibc-x86_64-astra-media-oobe-cortexa73-sl1680-toolchain-5.0.9.sh
# Custom-built toolchains may instead target an aarch64 build host.
_INSTALLER_RE = re.compile(
    r"^(?P<prefix>.+?)-poky-glibc-(?P<host_arch>x86_64|aarch64|arm64)-.+-toolchain-(?P<version>[0-9][0-9.]*)\.sh$"
)

# get_sl1680_oobe_scarthgap_6.12_v2.5.0_toolchain.sh
_WRAPPER_RE = re.compile(r"^get_(?P<prefix>.+)_toolchain\.sh$")


@dataclass(frozen=True)
class ToolchainSpec:
    """Identity of a single toolchain: chip, image and release."""

    machine: str
    image: str = DEFAULT_IMAGE
    release: Optional[str] = None
    codename: Optional[str] = None
    version: Optional[str] = None
    installer: Optional[str] = None
    # Build-host architecture the installer targets, e.g. "x86_64" or "aarch64".
    host_arch: Optional[str] = None

    @property
    def docker_name(self) -> str:
        parts = ["astra"]
        if self.release:
            parts.append(self.release.replace("_", "-"))
        elif self.codename:
            parts.append(self.codename)
            if self.version:
                parts.append(self.version)
        if self.image != DEFAULT_IMAGE:
            parts.append(self.image.replace("_", "-"))
        parts.append(self.machine)
        return "-".join(parts).lower()

    def describe(self) -> str:
        return "{}/{} ({})".format(
            self.machine, self.image, self.release or self.codename or "unknown release"
        )


def _split_prefix(
    prefix: str, release: Optional[str]
) -> Tuple[str, str, Optional[str], Optional[str]]:
    """Split an asset prefix into (machine, image, codename, release)."""
    codename = release.split("_", 1)[0] if release else None

    if release and prefix.endswith("_" + release):
        prefix = prefix[: -(len(release) + 1)]
    else:
        tokens = prefix.split("_")
        for index, token in enumerate(tokens):
            if index == 0 or token not in CODENAMES:
                continue
            codename = token
            # A trailing "<codename>_<kernel>_<version>" is an embedded release tag.
            if index < len(tokens) - 1:
                release = "_".join(tokens[index:])
            prefix = "_".join(tokens[:index])
            break

    tokens = prefix.split("_")
    machine = tokens[0]
    image = "_".join(tokens[1:]) or DEFAULT_IMAGE
    return machine, image, codename, release


def parse_asset(name: str, release: Optional[str] = None) -> Optional[ToolchainSpec]:
    """Return the spec for a toolchain asset name, or None if it is not one."""
    match = _INSTALLER_RE.match(name)
    if match:
        machine, image, codename, release = _split_prefix(match.group("prefix"), release)
        return ToolchainSpec(
            machine=machine,
            image=image,
            release=release,
            codename=codename,
            version=match.group("version"),
            installer=name,
            host_arch=match.group("host_arch").replace("arm64", "aarch64"),
        )

    match = _WRAPPER_RE.match(name)
    if match:
        machine, image, codename, release = _split_prefix(match.group("prefix"), release)
        return ToolchainSpec(
            machine=machine,
            image=image,
            release=release,
            codename=codename,
        )
    return None
