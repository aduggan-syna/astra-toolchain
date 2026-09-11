"""Docker operations: building toolchain images, running shells and listing them."""

from __future__ import annotations

import json
import getpass
import os
import re
import shutil
import subprocess
import tempfile
from typing import List, Optional

from astra_toolchain.naming import ToolchainSpec, host_arch, normalize_arch

RESOURCES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "resources")
LABEL = "org.synaptics.astra.toolchain=1"
NAME_PREFIX = "astra-"
# The Astra toolchains are usually x86_64 Linux binaries, though custom builds
# may target aarch64.
TOOLCHAIN_PLATFORM = "linux/amd64"
_ARCH_TO_PLATFORM = {"x86_64": "linux/amd64", "aarch64": "linux/arm64"}


class DockerError(RuntimeError):
    pass


def docker_binary() -> str:
    docker = shutil.which("docker")
    if docker is None:
        raise DockerError("docker was not found on PATH")
    return docker


def _run(args: List[str], capture: bool = False) -> subprocess.CompletedProcess:
    command = [docker_binary()] + args
    return subprocess.run(command, check=False, text=True, capture_output=capture)


def _check(args: List[str], capture: bool = False) -> subprocess.CompletedProcess:
    result = _run(args, capture=capture)
    if result.returncode != 0:
        message = (result.stderr or "").strip() or "docker {} failed".format(args[0])
        raise DockerError(message)
    return result


def image_exists(name: str) -> bool:
    return _run(["image", "inspect", name], capture=True).returncode == 0


def image_arch(name: str) -> Optional[str]:
    """Return the normalized architecture (e.g. "x86_64") an image was built for."""
    result = _run(["image", "inspect", "--format", "{{.Architecture}}", name], capture=True)
    if result.returncode != 0:
        return None
    return normalize_arch(result.stdout.strip())


def container_state(name: str) -> Optional[str]:
    result = _run(["container", "inspect", "--format", "{{.State.Status}}", name], capture=True)
    if result.returncode != 0:
        return None
    return result.stdout.strip()


def container_user() -> str:
    name = re.sub(r"[^a-z0-9_-]", "", getpass.getuser().lower())
    return name or "astra"


def default_platform(toolchain_arch: Optional[str] = None) -> Optional[str]:
    """Pick the docker platform for a toolchain, emulating when the host differs."""
    arch = normalize_arch(toolchain_arch or "x86_64")
    if arch == host_arch():
        return None
    return _ARCH_TO_PLATFORM.get(arch, TOOLCHAIN_PLATFORM)


def build_image(
    spec: ToolchainSpec,
    installer_path: str,
    name: Optional[str] = None,
    base_image: str = "ubuntu:22.04",
    toolchain_dir: str = "/opt/astra/toolchain",
    no_cache: bool = False,
    platform_name: Optional[str] = None,
) -> str:
    """Build the toolchain container image and return its name."""
    name = name or spec.docker_name
    installer_name = os.path.basename(installer_path)

    context = tempfile.mkdtemp(prefix="astra-toolchain-")
    try:
        shutil.copy2(os.path.join(RESOURCES, "Dockerfile"), context)
        shutil.copy2(os.path.join(RESOURCES, "entrypoint.sh"), context)
        staged = os.path.join(context, installer_name)
        try:
            os.link(os.path.abspath(installer_path), staged)
        except OSError:
            shutil.copy2(installer_path, staged)

        args = [
            "build",
            "-t",
            name,
            "-f",
            os.path.join(context, "Dockerfile"),
            "--build-arg",
            "BASE_IMAGE={}".format(base_image),
            "--build-arg",
            "TOOLCHAIN_INSTALLER={}".format(installer_name),
            "--build-arg",
            "TOOLCHAIN_DIR={}".format(toolchain_dir),
            "--build-arg",
            "TOOLCHAIN_NAME={}".format(name),
            "--build-arg",
            "USER_NAME={}".format(container_user()),
            "--build-arg",
            "USER_UID={}".format(os.getuid()),
            "--build-arg",
            "USER_GID={}".format(os.getgid()),
        ]
        if no_cache:
            args.append("--no-cache")
        if platform_name:
            args += ["--platform", platform_name]
        args.append(context)
        _check(args)
    finally:
        shutil.rmtree(context, ignore_errors=True)
    return name


def run_shell(
    name: str,
    workdir: str,
    command: Optional[List[str]] = None,
    extra_args: Optional[List[str]] = None,
    platform_name: Optional[str] = None,
) -> int:
    """Open a shell (or run a command) in the container for ``name``."""
    if not image_exists(name):
        raise DockerError("No image '{}'. Run 'astra-toolchain build' first.".format(name))

    state = container_state(name)
    if state == "running":
        args = ["exec", "-it", "-w", "/workspace", name]
        args += command or ["/bin/bash"]
        return _run(args).returncode

    if state is not None:
        _check(["rm", name])

    args = [
        "run",
        "-it",
        "--name",
        name,
        "--hostname",
        name,
        "-v",
        "{}:/workspace".format(os.path.abspath(workdir)),
        "-w",
        "/workspace",
    ]
    if platform_name:
        args += ["--platform", platform_name]
    if extra_args:
        args += extra_args
    args.append(name)
    if command:
        args += command
    return _run(args).returncode


def list_images() -> List[dict]:
    result = _check(
        [
            "images",
            "--filter",
            "label={}".format(LABEL),
            "--format",
            "{{json .}}",
        ],
        capture=True,
    )
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def list_containers() -> List[dict]:
    result = _check(
        [
            "ps",
            "--all",
            "--filter",
            "name=^{}".format(NAME_PREFIX),
            "--format",
            "{{json .}}",
        ],
        capture=True,
    )
    return [json.loads(line) for line in result.stdout.splitlines() if line.strip()]


def remove(name: str, keep_image: bool = False) -> None:
    if container_state(name) is not None:
        _check(["rm", "-f", name])
    if not keep_image and image_exists(name):
        _check(["rmi", name])
