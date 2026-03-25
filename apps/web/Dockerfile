FROM node:20-bookworm-slim

WORKDIR /app

COPY apps/web/package.json apps/web/package-lock.json ./

RUN npm ci

COPY apps/web ./

ENV NODE_ENV=production

RUN npm run build

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
