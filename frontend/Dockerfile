FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm install --no-audit --no-fund

FROM node:22-alpine AS build
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
# rewrites /api -> бэкенд вшиваются при сборке (standalone), поэтому адрес API - аргумент сборки
ARG API_URL=http://backend:8000
ENV API_URL=$API_URL
ARG NEXT_PUBLIC_TG_BOT_NAME=""
ENV NEXT_PUBLIC_TG_BOT_NAME=$NEXT_PUBLIC_TG_BOT_NAME
RUN npm run build

FROM node:22-alpine
WORKDIR /app
# адрес API нужен и запущенному серверу сайта: страницы запрашивают данные на сервере
ARG API_URL=http://backend:8000
ENV API_URL=$API_URL
ENV NODE_ENV=production NEXT_TELEMETRY_DISABLED=1 PORT=3000 HOSTNAME=0.0.0.0
COPY --from=build /app/.next/standalone ./
COPY --from=build /app/.next/static ./.next/static
COPY --from=build /app/public ./public
EXPOSE 3000
CMD ["node", "server.js"]
