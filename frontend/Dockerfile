FROM node:22-slim@sha256:43ac6c60b8f89723f746e8a92ce91abd5017e627ce1ddfe4238355d3a30b772c AS build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend ./

ARG VITE_API_URL
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_PUBLISHABLE_KEY

RUN node -e 'for (const key of ["VITE_API_URL", "VITE_SUPABASE_URL", "VITE_SUPABASE_PUBLISHABLE_KEY"]) { if (!process.env[key]) throw new Error("Missing build setting: " + key); }' \
    && npm run build

FROM nginx:1.28-alpine@sha256:a8b39bd9cf0f83869a2162827a0caf6137ddf759d50a171451b335cecc87d236

ENV WPL_LISTEN_ADDRESS=127.0.0.1 \
    WPL_HTTP_PORT=8080

COPY --from=build /app/frontend/dist /usr/share/nginx/html
COPY deploy/nginx.conf.template /etc/nginx/templates/default.conf.template
