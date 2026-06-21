# Foresia BullMQ worker — Node 20 + TypeScript, compiled to dist and run with node.
FROM node:20-alpine

WORKDIR /app

# Install deps first for layer caching.
COPY package.json ./
RUN npm install

# Build.
COPY tsconfig.json ./
COPY src ./src
RUN npm run build

ENV NODE_ENV=production
EXPOSE 9100

CMD ["node", "dist/index.js"]
