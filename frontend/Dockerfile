# Сборка фронтенда и раздача статики nginx-ом.
# VITE_API_BASE подставляется на этапе сборки: Vite вшивает значение в бандл,
# менять его после сборки уже нельзя — поэтому это build-arg, а не переменная
# окружения контейнера.
FROM node:20-alpine AS build

ARG VITE_API_BASE=""
ENV VITE_API_BASE=$VITE_API_BASE

WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

FROM nginx:alpine
COPY --from=build /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
