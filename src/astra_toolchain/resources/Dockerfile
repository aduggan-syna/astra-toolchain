ARG BASE_IMAGE=ubuntu:22.04
FROM ${BASE_IMAGE}

ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
        bash \
        bc \
        bzip2 \
        ca-certificates \
        cmake \
        build-essential \
        device-tree-compiler \
        file \
        gawk \
        git \
        gzip \
        less \
        libncurses5-dev \
        locales \
        make \
        nano \
        ninja-build \
        pkg-config \
        python3 \
        python3-pip \
        rsync \
        sudo \
        tar \
        unzip \
        vim \
        wget \
        xz-utils \
        zstd \
 && rm -rf /var/lib/apt/lists/* \
 && locale-gen en_US.UTF-8
ENV LANG=en_US.UTF-8

# Create a user matching the caller so that files written to bind mounts keep
# the ownership they have on the host.
ARG USER_NAME=astra
ARG USER_UID=1000
ARG USER_GID=1000
RUN set -eux; \
    if getent group "${USER_GID}" >/dev/null; then \
        existing_group="$(getent group "${USER_GID}" | cut -d: -f1)"; \
        if [ "${existing_group}" != "${USER_NAME}" ]; then \
            groupmod -n "${USER_NAME}" "${existing_group}"; \
        fi; \
    else \
        groupadd -g "${USER_GID}" "${USER_NAME}"; \
    fi; \
    if getent passwd "${USER_UID}" >/dev/null; then \
        existing_user="$(getent passwd "${USER_UID}" | cut -d: -f1)"; \
        if [ "${existing_user}" != "${USER_NAME}" ]; then \
            usermod -l "${USER_NAME}" -d "/home/${USER_NAME}" -m "${existing_user}"; \
        fi; \
        usermod -g "${USER_GID}" -s /bin/bash "${USER_NAME}"; \
    else \
        useradd -m -u "${USER_UID}" -g "${USER_GID}" -s /bin/bash "${USER_NAME}"; \
    fi; \
    echo "${USER_NAME} ALL=(ALL) NOPASSWD:ALL" > "/etc/sudoers.d/${USER_NAME}"; \
    chmod 0440 "/etc/sudoers.d/${USER_NAME}"

# Bind-mounted /workspace can report ownership that doesn't exactly match the
# container user (notably over Docker Desktop's macOS file sharing), which
# trips git's dubious-ownership check on every clone done during a build.
RUN git config --system --add safe.directory '*'

ARG TOOLCHAIN_INSTALLER
ARG TOOLCHAIN_DIR=/opt/astra/toolchain
COPY ${TOOLCHAIN_INSTALLER} /tmp/astra-toolchain-installer.sh
RUN set -eux; \
    chmod +x /tmp/astra-toolchain-installer.sh; \
    /tmp/astra-toolchain-installer.sh -y -d "${TOOLCHAIN_DIR}"; \
    rm -f /tmp/astra-toolchain-installer.sh

ENV ASTRA_TOOLCHAIN_DIR=${TOOLCHAIN_DIR}
ARG TOOLCHAIN_NAME=unknown
ENV ASTRA_TOOLCHAIN=${TOOLCHAIN_NAME}
LABEL org.synaptics.astra.toolchain="1" \
      org.synaptics.astra.toolchain.name="${TOOLCHAIN_NAME}"

COPY entrypoint.sh /usr/local/bin/astra-entrypoint
RUN chmod 0755 /usr/local/bin/astra-entrypoint

USER ${USER_NAME}
WORKDIR /workspace
ENTRYPOINT ["/usr/local/bin/astra-entrypoint"]
CMD ["/bin/bash"]
