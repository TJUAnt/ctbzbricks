package partlibrary

import (
	"bytes"
	"encoding/binary"
	"errors"
	"fmt"
	"io"
	"math"
)

const StudioConnectivityParserVersion = "studio-connectivity-v0-parser-v1"

type StudioConnectorDefinition struct {
	ConnectorKind           string
	NormalizedConnectorType string
	ConnectorGroup          string
	ConnectorGender         string
	Position                [3]float64
	Orientation             [9]float64
	Direction               [3]float64
	Radius                  *float64
	Length                  *float64
	Caps                    []bool
	CenterFlag              bool
	SlideFlag               bool
	SourceGroup             int16
	SourceSubtype           int16
	MatrixItemType          int16
	MatrixGridType          int16
	SourceRecord            int
	SourceCell              int
}

type studioConnectivityRecord struct {
	group       int16
	subtype     int16
	orientation [9]float64
	position    [3]float64
	startCapped bool
	endCapped   bool
	length      float64
	grabbing    bool
	required    bool
	height      int
	width       int
	cells       []studioMatrixCell
}

type studioMatrixCell struct {
	itemType int16
	gridType int16
}

func ParseStudioConnectivity(data []byte) ([]StudioConnectorDefinition, error) {
	if len(data) == 0 {
		return nil, nil
	}
	reader := bytes.NewReader(data)
	records := []studioConnectivityRecord{}
	for reader.Len() > 0 {
		record, err := readStudioConnectivityRecord(reader)
		if err != nil {
			return nil, fmt.Errorf("record %d: %w", len(records), err)
		}
		records = append(records, record)
	}
	definitions := []StudioConnectorDefinition{}
	for recordIndex, record := range records {
		if record.group == 2 || record.group == 3 {
			definitions = append(definitions, expandStudioMatrixRecord(record, recordIndex)...)
			continue
		}
		definitions = append(definitions, studioRecordDefinition(record, recordIndex))
	}
	return definitions, nil
}

func readStudioConnectivityRecord(reader *bytes.Reader) (studioConnectivityRecord, error) {
	if reader.Len() < 52 {
		return studioConnectivityRecord{}, io.ErrUnexpectedEOF
	}
	var record studioConnectivityRecord
	if err := binary.Read(reader, binary.LittleEndian, &record.group); err != nil {
		return record, err
	}
	if err := binary.Read(reader, binary.LittleEndian, &record.subtype); err != nil {
		return record, err
	}
	var values [12]float32
	if err := binary.Read(reader, binary.LittleEndian, &values); err != nil {
		return record, err
	}
	for index := range record.orientation {
		record.orientation[index] = float64(values[index])
	}
	record.position = [3]float64{float64(values[9]), float64(values[10]), float64(values[11])}
	if err := validateStudioTransform(record.orientation, record.position); err != nil {
		return record, err
	}
	switch record.group {
	case 0:
		if reader.Len() < 8 {
			return record, io.ErrUnexpectedEOF
		}
		var flags [2]byte
		if err := binary.Read(reader, binary.LittleEndian, &flags); err != nil {
			return record, err
		}
		var length float32
		if err := binary.Read(reader, binary.LittleEndian, &length); err != nil {
			return record, err
		}
		var grip [2]byte
		if err := binary.Read(reader, binary.LittleEndian, &grip); err != nil {
			return record, err
		}
		if !validBoolBytes(flags[:]) || !validBoolBytes(grip[:]) || !finite(float64(length)) || length < 0 {
			return record, errors.New("invalid axle payload")
		}
		record.startCapped, record.endCapped = flags[0] == 1, flags[1] == 1
		record.length = float64(length)
		record.grabbing, record.required = grip[0] == 1, grip[1] == 1
	case 1, 7:
		// Ball and rail records contain only the common transform.
	case 4:
		// Fixed records carry a legacy axis mask after the common transform.
		if reader.Len() < 2 {
			return record, io.ErrUnexpectedEOF
		}
		var axes int16
		if err := binary.Read(reader, binary.LittleEndian, &axes); err != nil {
			return record, err
		}
	case 6:
		// Legacy hinge records store four angle limits followed by isOriented.
		if reader.Len() < 17 {
			return record, io.ErrUnexpectedEOF
		}
		var limits [4]float32
		if err := binary.Read(reader, binary.LittleEndian, &limits); err != nil {
			return record, err
		}
		var oriented byte
		if err := binary.Read(reader, binary.LittleEndian, &oriented); err != nil {
			return record, err
		}
		if oriented > 1 {
			return record, errors.New("invalid hinge orientation flag")
		}
	case 2, 3:
		var height, width int16
		if err := binary.Read(reader, binary.LittleEndian, &height); err != nil {
			return record, err
		}
		if err := binary.Read(reader, binary.LittleEndian, &width); err != nil {
			return record, err
		}
		if height < 0 || width < 0 || height > 1024 || width > 1024 {
			return record, errors.New("invalid matrix dimensions")
		}
		record.height, record.width = int(height), int(width)
		cellCount := (record.height + 1) * (record.width + 1)
		if cellCount > reader.Len()/4 {
			return record, io.ErrUnexpectedEOF
		}
		record.cells = make([]studioMatrixCell, cellCount)
		for index := range record.cells {
			if err := binary.Read(reader, binary.LittleEndian, &record.cells[index].itemType); err != nil {
				return record, err
			}
			if err := binary.Read(reader, binary.LittleEndian, &record.cells[index].gridType); err != nil {
				return record, err
			}
		}
	case 8:
		if reader.Len() < 7 {
			return record, io.ErrUnexpectedEOF
		}
		var flags [2]byte
		if err := binary.Read(reader, binary.LittleEndian, &flags); err != nil {
			return record, err
		}
		var length float32
		if err := binary.Read(reader, binary.LittleEndian, &length); err != nil {
			return record, err
		}
		var cylindrical byte
		if err := binary.Read(reader, binary.LittleEndian, &cylindrical); err != nil {
			return record, err
		}
		if !validBoolBytes(flags[:]) || cylindrical > 1 || !finite(float64(length)) || length < 0 {
			return record, errors.New("invalid slider payload")
		}
		record.startCapped, record.endCapped = flags[0] == 1, flags[1] == 1
		record.length = float64(length)
	default:
		return record, fmt.Errorf("unsupported connectivity group %d", record.group)
	}
	return record, nil
}

func expandStudioMatrixRecord(record studioConnectivityRecord, recordIndex int) []StudioConnectorDefinition {
	definitions := []StudioConnectorDefinition{}
	for index, cell := range record.cells {
		kind, normalized, gender, active := normalizeStudioMatrixCell(record.group, cell.itemType)
		if !active {
			continue
		}
		row := index / (record.width + 1)
		column := index % (record.width + 1)
		offset := [3]float64{float64(column) * 10, 0, float64(row) * 10}
		position := add3(record.position, multiply3(record.orientation, offset))
		orientation, convertedPosition := studioToLDrawTransform(record.orientation, position)
		definition := StudioConnectorDefinition{
			ConnectorKind: kind, NormalizedConnectorType: normalized,
			ConnectorGroup: fmt.Sprintf("studio_matrix_%d", recordIndex), ConnectorGender: gender,
			Position: convertedPosition, Orientation: orientation, Direction: orientationColumn(orientation, 1),
			SourceGroup: record.group, SourceSubtype: record.subtype,
			MatrixItemType: cell.itemType, MatrixGridType: cell.gridType,
			SourceRecord: recordIndex, SourceCell: index,
		}
		definitions = append(definitions, definition)
	}
	return definitions
}

func studioRecordDefinition(record studioConnectivityRecord, recordIndex int) StudioConnectorDefinition {
	kind, normalized, gender := normalizeStudioRecord(record.group, record.subtype)
	orientation, position := studioToLDrawTransform(record.orientation, record.position)
	definition := StudioConnectorDefinition{
		ConnectorKind: kind, NormalizedConnectorType: normalized,
		ConnectorGroup: fmt.Sprintf("studio_record_%d", recordIndex), ConnectorGender: gender,
		Position: position, Orientation: orientation, Direction: orientationColumn(orientation, 1),
		Caps: []bool{record.startCapped, record.endCapped}, SlideFlag: record.group == 8,
		SourceGroup: record.group, SourceSubtype: record.subtype,
		SourceRecord: recordIndex, SourceCell: -1,
	}
	if record.length > 0 {
		length := record.length
		definition.Length = &length
	}
	return definition
}

func normalizeStudioMatrixCell(group, itemType int16) (string, string, string, bool) {
	if group == 3 {
		switch itemType {
		case 10, 20, 40, 50, 60:
			return "stud", "stud", "M", true
		default:
			return "", "", "", false
		}
	}
	switch itemType {
	case 10, 20, 25, 30, 40, 50:
		return "tube", "anti_stud", "F", true
	default:
		return "", "", "", false
	}
}

func normalizeStudioRecord(group, subtype int16) (string, string, string) {
	if group == 0 {
		switch subtype {
		case 2:
			return "technic_pin_socket", "technic_pin_hole", "F"
		case 3, 5:
			return "technic_pin", "technic_pin", "M"
		case 6:
			return "axle_socket", "axle_hole", "F"
		case 7, 9:
			return "axle", "axle", "M"
		case 10:
			return "round_hole", "round_hole", "F"
		case 11:
			return "bar_for_round_hole", "bar", "M"
		case 12:
			return "clip", "clip", "F"
		case 13:
			return "bar", "bar", "M"
		case 14:
			return "pin_socket", "pin_socket", "F"
		case 15:
			return "bar_with_pin_socket", "bar", "M"
		case 17:
			return "pin", "pin", "M"
		}
	}
	kind := map[int16]string{1: "ball", 4: "fixed", 6: "hinge", 7: "rail", 8: "slider"}[group]
	if kind == "" {
		kind = "studio_unknown"
	}
	return kind, fmt.Sprintf("studio_%s_%d", kind, subtype), "neutral"
}

func studioToLDrawTransform(orientation [9]float64, position [3]float64) ([9]float64, [3]float64) {
	// Studio connectivity uses a left-handed Z axis. S*R*S converts its basis
	// to the right-handed LDraw coordinates used by scene snapshots.
	converted := orientation
	for row := 0; row < 3; row++ {
		for column := 0; column < 3; column++ {
			if (row == 2) != (column == 2) {
				converted[row*3+column] = -converted[row*3+column]
			}
		}
	}
	return converted, [3]float64{position[0], position[1], -position[2]}
}

func validateStudioTransform(orientation [9]float64, position [3]float64) error {
	for _, value := range orientation {
		if !finite(value) {
			return errors.New("non-finite orientation")
		}
	}
	for _, value := range position {
		if !finite(value) {
			return errors.New("non-finite position")
		}
	}
	return nil
}

func validBoolBytes(values []byte) bool {
	for _, value := range values {
		if value > 1 {
			return false
		}
	}
	return true
}

func finite(value float64) bool { return !math.IsNaN(value) && !math.IsInf(value, 0) }

func multiply3(matrix [9]float64, vector [3]float64) [3]float64 {
	return [3]float64{
		matrix[0]*vector[0] + matrix[1]*vector[1] + matrix[2]*vector[2],
		matrix[3]*vector[0] + matrix[4]*vector[1] + matrix[5]*vector[2],
		matrix[6]*vector[0] + matrix[7]*vector[1] + matrix[8]*vector[2],
	}
}

func add3(left, right [3]float64) [3]float64 {
	return [3]float64{left[0] + right[0], left[1] + right[1], left[2] + right[2]}
}

func orientationColumn(matrix [9]float64, column int) [3]float64 {
	return [3]float64{matrix[column], matrix[3+column], matrix[6+column]}
}
