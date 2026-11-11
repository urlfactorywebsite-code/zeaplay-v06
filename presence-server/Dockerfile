FROM node:20-alpine

LABEL org.opencontainers.image.version="6.1.7"

ENV NODE_ENV=production

WORKDIR /app

COPY package*.json ./
RUN npm install --omit=dev

COPY src ./src

EXPOSE 7212

CMD ["npm", "start"]
