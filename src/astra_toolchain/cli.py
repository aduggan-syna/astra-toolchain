"""Command line interface for astra-toolchain."""

from __future__ import annotations

import argparse
import dataclasses
import os
import sys
from typing import List, Optional

from astra_toolchain import __version__, docker, releases
from astra_toolchain.naming import DEFAULT_IMAGE, ToolchainSpec, parse_asset

DEFAULT_CACHE = os.path.join(
    os.environ.get("XDG_CACHE_HOME", os.path.expanduser("~/.cache")), "astra-toolchain"
)


def _spec_from_args(args, spec: Optional[ToolchainSpec] = None) -> ToolchainSpec:
    """Apply the command line overrides on top of a parsed spec."""
    if spec is None:
        if not args.machine:
            raise SystemExit("error: --machine is required (for example --machine sl1680)")
        spec = ToolchainSpec(machine=args.machine, image=args.image or DEFAULT_IMAGE)
    overrides = {}
    if args.machine:
        overrides["machine"] = args.machine
    if args.image:
        overrides["image"] = args.image
    if args.release:
        overrides["release"] = args.release
        overrides["codename"] = args.release.split("_", 1)[0]
    return dataclasses.replace(spec, **overrides)


def _resolve_installer(args):
    """Return (installer_path, spec), downloading the toolchain when needed."""
    if args.toolchain:
        path = os.path.abspath(args.toolchain)
        if not os.path.isfile(path):
            raise SystemExit("error: no such toolchain installer: {}".format(path))
        spec = parse_asset(os.path.basename(path))
        return path, _spec_from_args(args, spec)

    local = releases.find_local_installer(args.dir, args.machine, args.image)
    if local is not None:
        path, spec = local
        print("Using toolchain installer {}".format(path))
        return path, _spec_from_args(args, spec)

    if not args.machine:
        raise SystemExit(
            "error: no toolchain installer found in {}; pass --machine (and optionally "
            "--image/--release) to download one".format(args.dir)
        )

    remote = releases.find_toolchain(args.machine, args.image or DEFAULT_IMAGE, args.release)
    print("Downloading toolchain for {}".format(remote.spec.describe()))
    path = releases.download_toolchain(remote, args.cache)
    return path, _spec_from_args(args, remote.spec)


def cmd_build(args) -> int:
    path, spec = _resolve_installer(args)
    name = args.name or spec.docker_name
    if docker.image_exists(name) and not args.force:
        print("Image {} already exists (use --force to rebuild)".format(name))
        return 0
    print("Building {} from {}".format(name, os.path.basename(path)))
    docker.build_image(
        spec,
        path,
        name=name,
        base_image=args.base_image,
        no_cache=args.no_cache,
        platform_name=args.platform or docker.default_platform(spec.host_arch),
    )
    print("Built {}".format(name))
    return 0


def _resolve_name(args) -> str:
    if getattr(args, "name", None):
        return args.name
    if args.machine or args.release or args.image:
        return _spec_from_args(args).docker_name
    images = docker.list_images()
    names = sorted({image["Repository"] for image in images})
    if len(names) == 1:
        return names[0]
    if not names:
        raise SystemExit("error: no Astra toolchain images found; run 'astra-toolchain build' first")
    raise SystemExit(
        "error: several toolchains available, pick one:\n  " + "\n  ".join(names)
    )


def cmd_run(args) -> int:
    name = _resolve_name(args)
    platform_name = args.platform or docker.default_platform(docker.image_arch(name))
    return docker.run_shell(name, args.workdir, args.command or None, platform_name=platform_name)


def cmd_list(args) -> int:
    images = docker.list_images()
    containers = {c["Names"]: c for c in docker.list_containers()}
    if not images and not containers:
        print("No Astra toolchains installed.")
        return 0

    rows = []
    for image in images:
        name = image["Repository"]
        container = containers.pop(name, None)
        rows.append((name, image.get("Size", "-"), container["State"] if container else "-"))
    for name, container in sorted(containers.items()):
        rows.append((name, "-", container["State"]))

    width = max(len(row[0]) for row in rows)
    print("{:<{w}}  {:>10}  {}".format("TOOLCHAIN", "SIZE", "CONTAINER", w=width))
    for name, size, state in sorted(rows):
        print("{:<{w}}  {:>10}  {}".format(name, size, state, w=width))
    return 0


def cmd_releases(args) -> int:
    available = releases.fetch_releases()
    if args.release or args.all:
        tags = [args.release] if args.release else [r["tag_name"] for r in available]
        for tag in tags:
            release = releases.select_release(available, tag)
            print(release["tag_name"])
            for key in sorted(releases.toolchains_in_release(release)):
                print("  {}/{}".format(*key))
        return 0
    for release in available:
        print(release["tag_name"])
    return 0


def cmd_remove(args) -> int:
    docker.remove(_resolve_name(args), keep_image=args.keep_image)
    return 0


def _add_selectors(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--machine", "--chip", dest="machine", help="chip, e.g. sl1680")
    parser.add_argument("--image", help="image variant, e.g. oobe (default: %(default)s)",
                        default=None)
    parser.add_argument("--release", help="SDK release tag, e.g. scarthgap_6.12_v2.5.0")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="astra-toolchain",
        description="Manage Synaptics Astra Yocto toolchains in Docker containers.",
    )
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="subcommand", required=True)

    build = subparsers.add_parser("build", help="build a toolchain container image")
    _add_selectors(build)
    build.add_argument("--toolchain", help="path to a toolchain installer .sh")
    build.add_argument("--dir", default=os.getcwd(), help="directory to search for an installer")
    build.add_argument("--cache", default=DEFAULT_CACHE, help="download cache directory")
    build.add_argument("--name", help="override the Docker image name")
    build.add_argument("--base-image", default="ubuntu:22.04", help="container base image")
    build.add_argument(
        "--platform",
        help="container platform (default: linux/amd64 on non-x86_64 hosts)",
    )
    build.add_argument("--no-cache", action="store_true", help="pass --no-cache to docker build")
    build.add_argument("--force", action="store_true", help="rebuild even if the image exists")
    build.set_defaults(func=cmd_build)

    run = subparsers.add_parser("run", help="get a shell in a toolchain container")
    run.add_argument("name", nargs="?", help="toolchain container name")
    _add_selectors(run)
    run.add_argument("-w", "--workdir", default=os.getcwd(), help="host directory to mount")
    run.add_argument(
        "--platform",
        help="container platform (default: linux/amd64 on non-x86_64 hosts)",
    )
    run.add_argument("command", nargs=argparse.REMAINDER, help="command to run instead of a shell")
    run.set_defaults(func=cmd_run)

    listing = subparsers.add_parser("list", help="list installed Astra toolchains")
    listing.set_defaults(func=cmd_list)

    remote = subparsers.add_parser("releases", help="list available SDK releases")
    remote.add_argument("release", nargs="?", help="show the toolchains in this release")
    remote.add_argument("--all", action="store_true", help="show toolchains for every release")
    remote.set_defaults(func=cmd_releases)

    remove = subparsers.add_parser("rm", help="remove a toolchain container and image")
    remove.add_argument("name", nargs="?", help="toolchain container name")
    _add_selectors(remove)
    remove.add_argument("--keep-image", action="store_true", help="only remove the container")
    remove.set_defaults(func=cmd_remove)

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    trailing: List[str] = []
    if "--" in argv:
        index = argv.index("--")
        argv, trailing = argv[:index], argv[index + 1 :]
    args = build_parser().parse_args(argv)
    if hasattr(args, "command"):
        args.command = list(args.command) + trailing
    try:
        return args.func(args)
    except (releases.ReleaseError, docker.DockerError) as error:
        print("error: {}".format(error), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
