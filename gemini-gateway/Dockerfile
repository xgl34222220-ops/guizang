FROM golang:1.23-alpine AS build
WORKDIR /src
COPY go.mod ./
COPY parts ./parts
RUN cat parts/main.go.part01 parts/main.go.part02 parts/main.go.part03 parts/main.go.part04 > main.go \
 && mkdir -p web \
 && cat parts/admin.html.part01 parts/admin.html.part02 > web/admin.html \
 && CGO_ENABLED=0 GOOS=linux go build -trimpath -ldflags="-s -w" -o /out/gateway .

FROM alpine:3.20
RUN apk add --no-cache ca-certificates tzdata && addgroup -S app && adduser -S -G app app
WORKDIR /app
COPY --from=build /out/gateway /app/gateway
RUN mkdir -p /data && chown -R app:app /data /app
USER app
ENV PORT=8080 STATE_PATH=/data/gateway.json
EXPOSE 8080
ENTRYPOINT ["/app/gateway"]
