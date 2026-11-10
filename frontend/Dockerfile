FROM node:22-alpine AS deps
WORKDIR /app
# Сборка и dev-сервер работают от непривилегированного пользователя node.
RUN chown node:node /app
USER node
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci --no-audit --no-fund

FROM deps AS dev
COPY --chown=node:node . .
ENV API_PROXY=http://api:8000
CMD ["npm", "run", "dev", "--", "--host"]

FROM deps AS build
COPY --chown=node:node . .
RUN npm run build && npm run check:bundle

FROM nginxinc/nginx-unprivileged:1.27-alpine AS prod
COPY --from=build /app/dist /usr/share/nginx/html
COPY deploy-nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 8080
HEALTHCHECK --interval=15s --timeout=3s CMD wget -qO- http://127.0.0.1:8080/healthz || exit 1
