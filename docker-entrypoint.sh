#!/bin/sh
set -eu

PUID_VALUE="${PUID:-${DOCKER_UID:-10001}}"
PGID_VALUE="${PGID:-${DOCKER_GID:-999}}"
APP_UID="$(id -u)"
APP_GID="$(id -g)"

# 默认保持镜像内 cloud123 用户；也可通过 PUID/PGID 跟随宿主机用户。
TARGET_UID="$APP_UID"
TARGET_GID="$APP_GID"
if [ "$APP_UID" = "0" ]; then
    TARGET_UID="$PUID_VALUE"
    TARGET_GID="$PGID_VALUE"
fi

case "$TARGET_UID" in ''|*[!0-9]*) echo "[entrypoint] PUID/UID 必须是数字: $TARGET_UID" >&2; exit 1;; esac
case "$TARGET_GID" in ''|*[!0-9]*) echo "[entrypoint] PGID/GID 必须是数字: $TARGET_GID" >&2; exit 1;; esac

if [ "$APP_UID" = "0" ]; then
    mkdir -p "$DATA_DIR/logs"
    chown -R "$TARGET_UID:$TARGET_GID" "$DATA_DIR"
    chmod 755 "$DATA_DIR" "$DATA_DIR/logs"

    exec /usr/bin/env \
        CLOUD123_UID="$TARGET_UID" \
        CLOUD123_GID="$TARGET_GID" \
        python -c 'import os,sys; os.setgroups([]); os.setgid(int(os.environ["CLOUD123_GID"])); os.setuid(int(os.environ["CLOUD123_UID"])); os.environ["HOME"]="/home/cloud123"; os.execvp(sys.argv[1], sys.argv[1:])' \
        "$@"
fi

exec "$@"
