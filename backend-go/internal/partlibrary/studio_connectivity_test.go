package partlibrary

import (
	"bytes"
	"encoding/binary"
	"math"
	"testing"
)

func TestParseStudioConnectivityExpandsStudAndHoleMatrices(t *testing.T) {
	var data bytes.Buffer
	writeStudioMatrixFixture(t, &data, 3, 23, [3]float32{-10, 0, 10}, 2, 2, []studioMatrixCell{
		{3, 1}, {0, 4}, {3, 1},
		{0, 4}, {10, 4}, {0, 4},
		{3, 1}, {0, 4}, {3, 1},
	})
	writeStudioMatrixFixture(t, &data, 2, 1, [3]float32{-10, 8, 10}, 2, 2, []studioMatrixCell{
		{0, 1}, {0, 2}, {0, 1},
		{0, 2}, {20, 4}, {0, 2},
		{0, 1}, {0, 2}, {0, 1},
	})

	definitions, err := ParseStudioConnectivity(data.Bytes())
	if err != nil {
		t.Fatalf("ParseStudioConnectivity: %v", err)
	}
	if len(definitions) != 2 {
		t.Fatalf("definition count = %d, want 2", len(definitions))
	}
	stud, hole := definitions[0], definitions[1]
	if stud.NormalizedConnectorType != "stud" || stud.ConnectorGender != "M" {
		t.Fatalf("stud = %+v", stud)
	}
	if hole.NormalizedConnectorType != "anti_stud" || hole.ConnectorGender != "F" {
		t.Fatalf("hole = %+v", hole)
	}
	if stud.Position != [3]float64{0, 0, -20} || hole.Position != [3]float64{0, 8, -20} {
		t.Fatalf("positions = %v / %v", stud.Position, hole.Position)
	}
}

func TestParseStudioConnectivityAxle(t *testing.T) {
	var data bytes.Buffer
	writeInt16(t, &data, 0)
	writeInt16(t, &data, 3)
	writeTransform(t, &data, [3]float32{20, 0, 0})
	data.Write([]byte{0, 1})
	writeFloat32(t, &data, 20)
	data.Write([]byte{0, 0})

	definitions, err := ParseStudioConnectivity(data.Bytes())
	if err != nil {
		t.Fatalf("ParseStudioConnectivity: %v", err)
	}
	if len(definitions) != 1 || definitions[0].NormalizedConnectorType != "technic_pin" || definitions[0].ConnectorGender != "M" {
		t.Fatalf("definitions = %+v", definitions)
	}
	if definitions[0].Length == nil || *definitions[0].Length != 20 || definitions[0].Caps[1] != true {
		t.Fatalf("axle dimensions = %+v", definitions[0])
	}
}

func TestParseStudioConnectivityRejectsTruncatedMatrix(t *testing.T) {
	var data bytes.Buffer
	writeInt16(t, &data, 3)
	writeInt16(t, &data, 23)
	writeTransform(t, &data, [3]float32{})
	writeInt16(t, &data, 100)
	writeInt16(t, &data, 100)
	if _, err := ParseStudioConnectivity(data.Bytes()); err == nil {
		t.Fatal("expected truncated matrix error")
	}
}

func TestParseStudioColliders(t *testing.T) {
	data := []byte("9 0 1 0 0 0 1 0 0 0 1 2 3 4 5 6 7 null\r\n")
	definitions, err := ParseStudioColliders(data)
	if err != nil {
		t.Fatalf("ParseStudioColliders: %v", err)
	}
	if len(definitions) != 1 || definitions[0].Position != [3]float64{2, 3, -4} || definitions[0].HalfExtents != [3]float64{5, 6, 7} {
		t.Fatalf("definitions = %+v", definitions)
	}
}

func writeStudioMatrixFixture(t *testing.T, data *bytes.Buffer, group, subtype int16, position [3]float32, height, width int16, cells []studioMatrixCell) {
	t.Helper()
	writeInt16(t, data, group)
	writeInt16(t, data, subtype)
	writeTransform(t, data, position)
	writeInt16(t, data, height)
	writeInt16(t, data, width)
	for _, cell := range cells {
		writeInt16(t, data, cell.itemType)
		writeInt16(t, data, cell.gridType)
	}
}

func writeTransform(t *testing.T, data *bytes.Buffer, position [3]float32) {
	t.Helper()
	values := [12]float32{1, 0, 0, 0, 1, 0, 0, 0, 1, position[0], position[1], position[2]}
	if err := binary.Write(data, binary.LittleEndian, values); err != nil {
		t.Fatal(err)
	}
}

func writeInt16(t *testing.T, data *bytes.Buffer, value int16) {
	t.Helper()
	if err := binary.Write(data, binary.LittleEndian, value); err != nil {
		t.Fatal(err)
	}
}

func writeFloat32(t *testing.T, data *bytes.Buffer, value float32) {
	t.Helper()
	if math.IsNaN(float64(value)) {
		t.Fatal("NaN fixture")
	}
	if err := binary.Write(data, binary.LittleEndian, value); err != nil {
		t.Fatal(err)
	}
}
