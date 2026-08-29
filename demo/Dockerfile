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
