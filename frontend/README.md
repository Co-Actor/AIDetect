# AIDetect Frontend

Quasar 2 (Vue 3 + TypeScript) SPA for AI content detection.

## Setup

```bash
cp .env.example .env
npm install
# or
pnpm install
```

## Development

```bash
npm run dev
# or
quasar dev
```

Runs on http://localhost:9000

## Production build

```bash
quasar build
```

Output: `dist/spa/`

## Docker

```bash
docker build --build-arg VITE_API_BASE_URL=http://your-api-host:8010 -t aidetect-frontend .
docker run -p 80:80 aidetect-frontend
```
