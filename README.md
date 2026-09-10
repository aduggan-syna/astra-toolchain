# astra_toolchain

Manage multiple Yocto toolchains for Synaptics Astra devices. Each toolchain
(chip + image + SDK release) is installed into its own Docker image, so several
toolchains can live side by side on the same machine.

Toolchain installers are taken from the current directory when present,
otherwise they are downloaded from
<https://github.com/synaptics-astra/sdk/releases>.

## Install

```bash
pip install -e .
```

Requirements: Python 3.9+, Docker, and permission to run `docker`.

## Naming

Images and containers are named after the release, image variant and chip:

```
astra-scarthgap-6.12-v2.5.0-oobe-sl1680
astra-scarthgap-6.12-v2.5.0-sl1620
astra-kirkstone-5.15-v1.8.0-x11-sl1640
```

## Usage

Show the available SDK releases and the toolchains they contain:

```bash
astra-toolchain releases
astra-toolchain releases scarthgap_6.12_v2.5.0
```

Build a container. If a toolchain installer (`*-toolchain-*.sh`) is in the
current directory it is used, otherwise the matching one is downloaded and
cached under `~/.cache/astra-toolchain`:

```bash
astra-toolchain build --machine sl1680 --image oobe
astra-toolchain build --machine sl1620 --release scarthgap_6.12_v2.4.0
astra-toolchain build --toolchain ./sl1680_oobe_scarthgap-poky-...-toolchain-5.0.9.sh
```

Get a shell with the SDK environment already sourced. The current directory is
mounted at `/workspace`:

```bash
astra-toolchain run astra-scarthgap-6.12-v2.5.0-oobe-sl1680
astra-toolchain run --machine sl1680 --image oobe
astra-toolchain run --machine sl1680 --image oobe -- make
```

List the installed toolchains and their containers:

```bash
astra-toolchain list
```

Remove one:

```bash
astra-toolchain rm astra-scarthgap-6.12-v2.5.0-oobe-sl1680
```

## File ownership

At build time a user is created inside the container with the same UID, GID and
login name as the caller, so files produced in `/workspace` keep the ownership
they have on the host. The user has passwordless `sudo` inside the container.

## Notes

- Set `GITHUB_TOKEN` if you hit GitHub API rate limits.
- Large toolchains are published as split assets; the checksum published by the
  SDK release is verified after the parts are joined.
