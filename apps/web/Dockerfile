FROM node:20-bookworm-slim

WORKDIR /app

COPY apps/web/package.json ./

RUN npm install

COPY apps/web ./

ENV NODE_ENV=production

RUN npm run build

CMD ["npm", "run", "start", "--", "--hostname", "0.0.0.0", "--port", "3000"]
