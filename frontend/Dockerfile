# --- build stage -------------------------------------------------------
FROM node:22-alpine AS build
WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci

COPY . .

# API base URL baked into the bundle at build time. Leave empty to use
# relative paths (serve the SPA behind the same origin as the API).
#   docker build --build-arg VITE_API_BASE=https://api.example.com -t engram-frontend .
ARG VITE_API_BASE=
ENV VITE_API_BASE=${VITE_API_BASE}
RUN npm run build

# --- serve stage --------------------------------------------------------
FROM nginx:alpine
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
