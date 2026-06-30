# Stage 1: build
FROM node:22-alpine AS builder

WORKDIR /app

COPY package*.json ./
RUN npm ci

COPY . .

# Empty by default: single-domain (relative /v1/* on the SPA's own origin). The vite dev
# server uses localhost:8010 via import.meta.env.DEV, which never runs through this image.
ARG VITE_API_BASE_URL=
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

ARG VITE_DEFAULT_API_KEY=""
ENV VITE_DEFAULT_API_KEY=$VITE_DEFAULT_API_KEY

# Google sign-in client ID (public). Empty → the Google button stays hidden (no-op).
ARG VITE_GOOGLE_CLIENT_ID=""
ENV VITE_GOOGLE_CLIENT_ID=$VITE_GOOGLE_CLIENT_ID

RUN npx quasar build -m spa

# Stage 2: serve
FROM nginx:alpine AS production

COPY --from=builder /app/dist/spa /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
