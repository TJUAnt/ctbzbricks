.PHONY: fmt fmt-check generate sqlc-vet test test-postgres vet check run-api run-worker migrate-help

fmt:
	gofmt -w $$(find . -name '*.go' -not -path './db/generated/*')

fmt-check:
	@test -z "$$(gofmt -l .)" || (gofmt -l . && exit 1)

generate:
	go tool sqlc generate

sqlc-vet:
	go tool sqlc vet

test:
	go test ./...

test-postgres:
	./scripts/test-postgres.sh

vet:
	go vet ./...

check: fmt-check test vet sqlc-vet

run-api:
	go run ./cmd/api

run-worker:
	go run ./cmd/worker

migrate-help:
	go run ./cmd/migrate --help
