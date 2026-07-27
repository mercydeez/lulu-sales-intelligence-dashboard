# Diagnostics worker (Node + BullMQ). Small, single-purpose image.
FROM node:26-alpine

WORKDIR /app

# Install deps first for layer caching.
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

COPY src ./src

# Drop root: run as a dedicated non-privileged user (mirrors backend/frontend).
RUN addgroup -S appgroup && adduser -S appuser -G appgroup \
    && chown -R appuser:appgroup /app
USER appuser

# Long-running process; BullMQ schedules the recurring scan.
CMD ["node", "src/index.js"]
