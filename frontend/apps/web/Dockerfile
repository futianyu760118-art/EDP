# 构建上下文必须为 frontend/（pnpm workspace 根，需要根 package.json + pnpm-lock.yaml）

FROM node:22-alpine AS builder
WORKDIR /workspace
# 固定 pnpm 版本与本地/CI 一致（pnpm-lock.yaml 由 10.13.1 生成）
RUN corepack enable && corepack prepare pnpm@10.13.1 --activate
COPY . .
# VITE_API_BASE 为构建期常量：容器内显式置空 = 同源相对路径（nginx /api 反代到 api 服务）
ARG VITE_API_BASE=""
ENV VITE_API_BASE=$VITE_API_BASE
RUN pnpm install --frozen-lockfile
RUN pnpm --filter web build

FROM nginx:alpine AS runtime
COPY --from=builder /workspace/apps/web/dist /usr/share/nginx/html
COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
