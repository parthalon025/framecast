#!/bin/bash -e
set -u -o pipefail
: "${ROOTFS_DIR:?ROOTFS_DIR must be set by pi-gen runner}"
if [ ! -d "${ROOTFS_DIR}" ]; then
    copy_previous
fi
