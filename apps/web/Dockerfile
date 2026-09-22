# syntax=docker/dockerfile:1
#
# Next.js 16 standalone image (§A1). Built on the target server, so the base
# image must publish linux/arm64 — node:22-alpine does.
#
# The runtime stage carries server.js plus only the node_modules that tracing
# found, which is why `output: "standalone"` is set in next.config.ts.

FROM node:22-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund


FROM node:22-alpine AS builder
WORKDIR /app
ENV NEXT_TELEMETRY_DISABLED=1
COPY --from=deps /app/node_modules ./node_modules
COPY . .
# `next build` type-checks and lints as part of the build, so a type error here
# fails the image rather than shipping.
RUN npm run build


FROM node:22-alpine AS runtime
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    PORT=3000 \
    HOSTNAME=0.0.0.0

RUN addgroup -g 10002 -S nodejs && adduser -u 10002 -S nextjs -G nodejs

WORKDIR /app
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static

USER nextjs
EXPOSE 3000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["node", "-e", "fetch('http://127.0.0.1:3000/').then(r=>process.exit(r.ok?0:1)).catch(()=>process.exit(1))"]

CMD ["node", "server.js"]
