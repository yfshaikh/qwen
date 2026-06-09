# ---- build stage ----
FROM node:22-alpine AS build
WORKDIR /app

# Install deps first (better layer caching).
COPY package.json package-lock.json* ./
RUN npm install

# Build the static site.
COPY . .
# VITE_API_BASE is baked in at build time. Override with:
#   docker build --build-arg VITE_API_BASE=https://api.example.com -t engram-frontend .
# Leave empty to call same-origin paths (front the app and API behind one proxy).
ARG VITE_API_BASE=""
ENV VITE_API_BASE=$VITE_API_BASE
RUN npm run build

# ---- serve stage ----
FROM nginx:alpine AS serve
COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
