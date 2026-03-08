FROM golang:1.22.3-bookworm AS go-builder

RUN git clone https://github.com/BattlesnakeOfficial/rules.git /src/rules
WORKDIR /src/rules
RUN go build -o /usr/local/bin/battlesnake ./cli/battlesnake/main.go

FROM node:20-bookworm-slim AS node-builder

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*
RUN git clone https://github.com/BattlesnakeOfficial/board.git /src/board
WORKDIR /src/board
RUN npm install

FROM node:20-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates && rm -rf /var/lib/apt/lists/*

COPY --from=go-builder /usr/local/bin/battlesnake /usr/local/bin/battlesnake

COPY --from=node-builder /src/board /opt/board

WORKDIR /opt/board

EXPOSE 3000
EXPOSE 8080

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
