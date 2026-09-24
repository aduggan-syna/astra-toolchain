#!/bin/bash
# Copyright 2026 Synaptics Inc.
#
# Licensed under the Apache License v2.0
# SPDX-License-Identifier: Apache-2.0

# Source the Yocto SDK environment, then run the requested command.

set -e

args=("$@")
set --
for env_setup in "${ASTRA_TOOLCHAIN_DIR}"/environment-setup-*; do
    if [ -f "${env_setup}" ]; then
        # shellcheck disable=SC1090
        . "${env_setup}"
    fi
done

if [ ${#args[@]} -eq 0 ]; then
    exec /bin/bash
fi
exec "${args[@]}"
