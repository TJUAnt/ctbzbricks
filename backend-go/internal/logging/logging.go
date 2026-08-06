package logging

import (
	"io"
	"log/slog"
	"strings"
)

func New(output io.Writer, environment string) *slog.Logger {
	level := slog.LevelInfo
	if strings.EqualFold(environment, "development") {
		level = slog.LevelDebug
	}
	return slog.New(slog.NewJSONHandler(output, &slog.HandlerOptions{Level: level}))
}
