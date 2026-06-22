# Diagnostics worker (Node + BullMQ). Small, single-purpose image.
FROM node:20-alpine

WORKDIR /app

# Install deps first for layer caching.
COPY package.json ./
RUN npm install --omit=dev --no-audit --no-fund

COPY src ./src

# Long-running process; BullMQ schedules the recurring scan.
CMD ["node", "src/index.js"]
