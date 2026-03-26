FROM node:20-bookworm-slim AS base

WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json ./

RUN npm ci

FROM base AS dev

ENV NODE_ENV=development \
    NEXT_TELEMETRY_DISABLED=1

COPY apps/web ./

CMD ["npm", "run", "dev", "--", "--hostname", "0.0.0.0", "--port", "3000"]

FROM base AS prod

COPY apps/web ./

ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1

RUN npm run build

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
