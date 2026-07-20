# Engram frontend — Vite build served by nginx, which also reverse-proxies the
# API paths and the /voice WebSocket to the backend service.
#
# Build context is the repo root (see docker-compose.yml) because the web app
# has a local file: dependency on ../packages/engram-types.

# ---- Stage 1: build the SPA ----
FROM node:20-slim AS build
WORKDIR /app

# The local package must exist before `npm ci` (package.json references
# "@engram/types": "file:../packages/engram-types").
COPY packages/ ./packages/
COPY web/package.json web/package-lock.json ./web/

WORKDIR /app/web
RUN npm ci

COPY web/ ./
RUN npm run build

# ---- Stage 2: serve with nginx ----
FROM nginx:1.27-alpine
COPY deploy/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/web/dist /usr/share/nginx/html
EXPOSE 80
