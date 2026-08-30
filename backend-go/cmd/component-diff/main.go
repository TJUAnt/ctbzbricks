package main

import (
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"os"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/componentdiff"
)

// main 是离线 Component SceneSnapshot diff 入口；输入文件只包含 snapshot.document JSON，不访问数据库或 Storage。
func main() {
	if err := run(); err != nil {
		fmt.Fprintln(os.Stderr, err)
		os.Exit(1)
	}
}

func run() error {
	var beforePath string
	var afterPath string
	var maxInstances int
	var maxDetails int
	flag.StringVar(&beforePath, "before", "", "optional base SceneSnapshot document JSON; omitted means an empty tree")
	flag.StringVar(&afterPath, "after", "", "required head SceneSnapshot document JSON")
	flag.IntVar(&maxInstances, "max-instances", 50_000, "maximum expanded instances on either side")
	flag.IntVar(&maxDetails, "max-details", 10_000, "maximum instance and ambiguity detail records")
	flag.Parse()

	if afterPath == "" || maxInstances <= 0 || maxDetails <= 0 {
		return errors.New("--after, positive --max-instances and positive --max-details are required")
	}
	after, err := os.ReadFile(afterPath)
	if err != nil {
		return fmt.Errorf("read after snapshot: %w", err)
	}
	options := componentdiff.Options{MaxInstances: maxInstances, MaxDetails: maxDetails}
	var result componentdiff.Result
	if beforePath == "" {
		result, err = componentdiff.CompareFromEmptyJSON(after, options)
	} else {
		before, readErr := os.ReadFile(beforePath)
		if readErr != nil {
			return fmt.Errorf("read before snapshot: %w", readErr)
		}
		result, err = componentdiff.CompareJSON(before, after, options)
	}
	if err != nil {
		return fmt.Errorf("compute component diff: %w", err)
	}
	encoder := json.NewEncoder(os.Stdout)
	encoder.SetIndent("", "  ")
	if err := encoder.Encode(result); err != nil {
		return fmt.Errorf("write component diff: %w", err)
	}
	return nil
}
