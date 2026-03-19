#!/bin/bash -e
set -u -o pipefail
if [ ! -d "${ROOTFS_DIR}" ]; then
    copy_previous
fi
