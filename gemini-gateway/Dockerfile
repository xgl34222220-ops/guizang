FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY main.go ./
COPY web ./web
RUN CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/gateway .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata && addgroup -S app && adduser -S -G app app
WORKDIR /app
COPY --from=build /out/gateway /app/gateway
RUN mkdir -p /data && chown -R app:app /data /app
USER app
ENV PORT=8080 STATE_PATH=/data/gateway.json
EXPOSE 8080
ENTRYPOINT ["/app/gateway"]
