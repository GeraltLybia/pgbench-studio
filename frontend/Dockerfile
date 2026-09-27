# syntax=docker/dockerfile:1.7
FROM node:22-alpine AS build
WORKDIR /src
# Non-interactive pnpm: without CI it may wait for a confirmation prompt.
ENV CI=true
RUN corepack enable
COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm build

FROM nginx:1.29-alpine
ENV PROXY_READ_TIMEOUT_S=14460 \
    TRUSTED_PROXIES=""
RUN rm /etc/nginx/conf.d/default.conf
COPY docker/40-trusted-proxies.sh /docker-entrypoint.d/40-trusted-proxies.sh
COPY docker/proxy_headers.conf /etc/nginx/snippets/proxy_headers.conf
COPY docker/default.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
  CMD wget -qO /dev/null http://127.0.0.1:8080/healthz || exit 1
