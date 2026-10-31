# syntax=docker/dockerfile:1
# EDP staging patroni/pgbackrest 镜像（T14 / EDP-021）。
#
# 为什么自建：本机网络实测 ghcr.io/zalando/patroni 与 Docker Hub 用户命名空间
# （zalando/patroni、bitnami/*）均不可拉取（详见 docs/demo/staging-drill.md 拓扑实测），
# 故以 postgres:16-bookworm 为底 + patroni[etcd3] + pgbackrest + curl（healthcheck 用）
# 构建等价镜像（含 PG16，行为与 zalando/patroni 镜像一致：`patroni /etc/patroni.yml`）。
# 版本固定为 2026-09-18 冒烟实测通过的组合（patroni 4.1.5 / pgbackrest 2.59.1 / PG 16.15）。

FROM postgres:16-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends pgbackrest python3-pip curl \
    && pip3 install --break-system-packages --no-cache-dir \
        "patroni[etcd3]==4.1.5" "psycopg2-binary==2.9.13" \
    && rm -rf /var/lib/apt/lists/*

# 以 postgres 用户运行：`--user postgres` + `command: patroni /etc/patroni.yml`（见 compose）
