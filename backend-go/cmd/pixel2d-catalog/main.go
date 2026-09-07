// pixel2d-catalog 显式导入冻结的真实 Plate/Color 目录；不清库、不修改既有目录快照。
package main

import (
	"context"
	"flag"
	"fmt"
	"github.com/ctbzbricks/brickbuilder/backend-go/internal/pixel2d"
	"github.com/jackc/pgx/v5/pgxpool"
	"os"
)

func main() {
	file := flag.String("metadata", "", "authoritative metadata JSON file")
	flag.Parse()
	if *file == "" {
		fmt.Fprintln(os.Stderr, "--metadata is required")
		os.Exit(2)
	}
	data, err := os.ReadFile(*file)
	if err != nil {
		panic(err)
	}
	ctx := context.Background()
	pool, err := pgxpool.New(ctx, os.Getenv("DATABASE_URL"))
	if err != nil {
		panic(err)
	}
	defer pool.Close()
	hash, err := pixel2d.ImportCatalog(ctx, pool, data)
	if err != nil {
		panic(err)
	}
	fmt.Println(hash)
}
