FROM node:24-alpine AS build

WORKDIR /workspace
COPY package.json package-lock.json ./
COPY packages/frontend ./packages/frontend
COPY demo ./demo
RUN npm ci && npm run build

FROM caddy:2-alpine
COPY demo/Caddyfile /etc/caddy/Caddyfile
COPY --from=build /workspace/demo/dist /srv
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=3s --retries=3 \
  CMD wget -q -O /dev/null http://127.0.0.1:8080/ || exit 1
