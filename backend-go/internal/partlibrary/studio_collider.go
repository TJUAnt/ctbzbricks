package partlibrary

import (
	"bufio"
	"bytes"
	"errors"
	"fmt"
	"math"
	"strconv"
	"strings"
)

const StudioColliderParserVersion = "studio-collider-col-parser-v1"

type StudioColliderDefinition struct {
	ColliderKind      string
	Position          [3]float64
	Orientation       [9]float64
	HalfExtents       [3]float64
	SourceHalfExtents [3]float64
	SourceLine        int
	SourceType        int
	SourceID          int
}

func ParseStudioColliders(data []byte) ([]StudioColliderDefinition, error) {
	scanner := bufio.NewScanner(bytes.NewReader(data))
	scanner.Buffer(make([]byte, 1024), 1024*1024)
	definitions := []StudioColliderDefinition{}
	for lineNumber := 1; scanner.Scan(); lineNumber++ {
		line := strings.TrimSpace(scanner.Text())
		if line == "" {
			continue
		}
		fields := strings.Fields(line)
		if len(fields) != 17 && len(fields) != 18 {
			return nil, fmt.Errorf("line %d: expected 17 or 18 fields, got %d", lineNumber, len(fields))
		}
		sourceType, err := strconv.Atoi(fields[0])
		if err != nil || (sourceType != 9 && sourceType != 8192) {
			return nil, fmt.Errorf("line %d: unsupported collider type %q", lineNumber, fields[0])
		}
		sourceID, err := strconv.Atoi(fields[1])
		if err != nil {
			return nil, fmt.Errorf("line %d: invalid collider id", lineNumber)
		}
		values := [15]float64{}
		for index := range values {
			value, parseErr := strconv.ParseFloat(fields[index+2], 64)
			if parseErr != nil || math.IsNaN(value) || math.IsInf(value, 0) {
				return nil, fmt.Errorf("line %d: invalid numeric field %d", lineNumber, index+3)
			}
			values[index] = value
		}
		if len(fields) == 18 && fields[17] != "null" {
			return nil, fmt.Errorf("line %d: unsupported extension %q", lineNumber, fields[17])
		}
		orientation := [9]float64{}
		copy(orientation[:], values[:9])
		position := [3]float64{values[9], values[10], values[11]}
		halfExtents := [3]float64{values[12], values[13], values[14]}
		if err := validateStudioTransform(orientation, position); err != nil {
			return nil, fmt.Errorf("line %d: %w", lineNumber, err)
		}
		sourceHalfExtents := halfExtents
		halfExtents = [3]float64{math.Abs(halfExtents[0]), math.Abs(halfExtents[1]), math.Abs(halfExtents[2])}
		orientation, position = studioToLDrawTransform(orientation, position)
		definitions = append(definitions, StudioColliderDefinition{
			ColliderKind: "box", Position: position, Orientation: orientation,
			HalfExtents: halfExtents, SourceHalfExtents: sourceHalfExtents,
			SourceLine: lineNumber, SourceType: sourceType, SourceID: sourceID,
		})
	}
	if err := scanner.Err(); err != nil {
		return nil, err
	}
	if len(definitions) == 0 && len(bytes.TrimSpace(data)) > 0 {
		return nil, errors.New("no collider definitions")
	}
	return definitions, nil
}
