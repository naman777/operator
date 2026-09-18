FROM node:22-alpine
WORKDIR /app
RUN corepack enable
COPY package.json pnpm-workspace.yaml pnpm-lock.yaml turbo.json ./
COPY packages packages
COPY apps/web apps/web
RUN pnpm install --frozen-lockfile
ENV API_URL=http://api:8000
RUN pnpm --filter @operator/web build
EXPOSE 3000
CMD ["pnpm", "--filter", "@operator/web", "exec", "next", "start", "--hostname", "0.0.0.0"]
