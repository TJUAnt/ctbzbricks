// Package scene 提供 SceneSnapshot 的确定性实例展开能力。
package scene

import (
	"encoding/json"
	"errors"
	"math"
	"strings"
)

const (
	maxExpansionDepth            = 64
	maxExpandedPartInstances     = 1_000_000
	maxExpandedSubmodelInstances = 1_000_000
)

var (
	errInvalidScene = errors.New("invalid component scene")
	// ErrExpansionLimit 表示实例展开超过调用方声明的资源边界。
	ErrExpansionLimit = errors.New("component scene expansion limit exceeded")
)

// ExpansionLimits 为同步调用方设置 Part 与子模型实例的硬上限，防止先分配完整场景再做事后校验。
type ExpansionLimits struct {
	MaxPartInstances     int
	MaxSubmodelInstances int
}

// Position 表示 SceneSnapshot 中未经单位换算的 LDraw 坐标。
type Position struct {
	X float64 `json:"x"`
	Y float64 `json:"y"`
	Z float64 `json:"z"`
}

// Transform 表示 LDraw 的平移和 3x3 方向矩阵。
type Transform struct {
	Position Position  `json:"position"`
	Matrix   []float64 `json:"matrix"`
}

// RootInstance 是场景的一个显式顶层入口实例。同一模型可以由多个 RootInstance 重复实例化。
type RootInstance struct {
	InstanceID    string    `json:"instanceId"`
	TargetModelID string    `json:"targetModelId"`
	Transform     Transform `json:"transform"`
}

// Reference 是模型定义中的一个 Part 或子模型引用。
type Reference struct {
	InstanceID    string    `json:"instanceId"`
	ReferenceName string    `json:"referenceName"`
	ReferenceKind string    `json:"referenceKind"`
	TargetModelID string    `json:"targetModelId"`
	ColorCode     string    `json:"colorCode"`
	Transform     Transform `json:"transform"`
}

// Model 是可被一个或多个场景实例引用的模型定义。
type Model struct {
	ModelID    string      `json:"modelId"`
	References []Reference `json:"references"`
}

// Document 只声明实例展开所需字段；SceneSnapshot 中的其它字段由各自领域保留。
type Document struct {
	RootModelID   string         `json:"rootModelId"`
	RootInstances []RootInstance `json:"rootInstances"`
	Models        []Model        `json:"models"`
}

// WorldPart 是从全部场景入口递归展开后的真实 Part 实例。
type WorldPart struct {
	InstanceID           string
	DefinitionInstanceID string
	PartRef              string
	ColorCode            string
	Matrix               [16]float64
}

// Expansion 保存一次场景展开的权威结果，BOM、校验、关系检测和 GLB 必须消费同一结果。
type Expansion struct {
	Parts                 []WorldPart
	SubmodelInstanceCount int
}

// IdentityTransform 返回场景顶层入口使用的单位变换。
func IdentityTransform() Transform {
	return Transform{
		Position: Position{},
		Matrix:   []float64{1, 0, 0, 0, 1, 0, 0, 0, 1},
	}
}

// ExpandJSON 解析 SceneSnapshot document，并按显式 rootInstances 展开真实 Part 实例。
// 旧快照没有 rootInstances 时，仅将 rootModelId 适配为一个单位变换入口；不会猜测未引用模型为 root。
func ExpandJSON(raw json.RawMessage) (Expansion, error) {
	return ExpandJSONWithLimits(raw, ExpansionLimits{
		MaxPartInstances:     maxExpandedPartInstances,
		MaxSubmodelInstances: maxExpandedSubmodelInstances,
	})
}

// ExpandJSONWithLimits 解析 SceneSnapshot document，并在展开过程中执行硬上限，而不是展开后再截断。
func ExpandJSONWithLimits(raw json.RawMessage, limits ExpansionLimits) (Expansion, error) {
	var document Document
	if err := json.Unmarshal(raw, &document); err != nil {
		return Expansion{}, errInvalidScene
	}
	return ExpandWithLimits(document, limits)
}

// Expand 按实例而不是模型定义展开场景。同一模型的重复引用必须重复计数，循环检测只作用于当前递归路径。
func Expand(document Document) (Expansion, error) {
	return ExpandWithLimits(document, ExpansionLimits{
		MaxPartInstances:     maxExpandedPartInstances,
		MaxSubmodelInstances: maxExpandedSubmodelInstances,
	})
}

// ExpandWithLimits 按实例展开场景并强制调用方资源上限；零值或负值上限视为非法输入。
func ExpandWithLimits(document Document, limits ExpansionLimits) (Expansion, error) {
	if limits.MaxPartInstances <= 0 || limits.MaxSubmodelInstances <= 0 {
		return Expansion{}, errInvalidScene
	}
	if len(document.Models) == 0 {
		return Expansion{}, errInvalidScene
	}
	models := make(map[string]Model, len(document.Models))
	for _, model := range document.Models {
		model.ModelID = strings.TrimSpace(model.ModelID)
		if model.ModelID == "" {
			return Expansion{}, errInvalidScene
		}
		if _, duplicate := models[model.ModelID]; duplicate {
			return Expansion{}, errInvalidScene
		}
		models[model.ModelID] = model
	}

	roots := document.RootInstances
	if len(roots) == 0 && strings.TrimSpace(document.RootModelID) != "" {
		roots = []RootInstance{{
			InstanceID:    "root_0001",
			TargetModelID: strings.TrimSpace(document.RootModelID),
			Transform:     IdentityTransform(),
		}}
	}
	if len(roots) == 0 {
		return Expansion{}, errInvalidScene
	}

	result := Expansion{Parts: make([]WorldPart, 0)}
	activeModels := map[string]bool{}
	worldInstanceIDs := map[string]bool{}
	rootInstanceIDs := map[string]bool{}

	var expandModel func(modelID string, parent [16]float64, path []string, depth int) error
	expandModel = func(modelID string, parent [16]float64, path []string, depth int) error {
		if depth > maxExpansionDepth || activeModels[modelID] {
			return errInvalidScene
		}
		model, exists := models[modelID]
		if !exists {
			return errInvalidScene
		}
		activeModels[modelID] = true
		defer delete(activeModels, modelID)

		// instanceId 在模型定义内必须唯一；完整实例路径则保证同一模型被多次引用时仍能区分每个实例。
		definitionInstanceIDs := map[string]bool{}
		for _, reference := range model.References {
			reference.InstanceID = strings.TrimSpace(reference.InstanceID)
			if reference.InstanceID == "" || definitionInstanceIDs[reference.InstanceID] {
				return errInvalidScene
			}
			definitionInstanceIDs[reference.InstanceID] = true
			local, err := matrix4(reference.Transform)
			if err != nil {
				return err
			}
			world := multiply4(parent, local)
			instancePath := appendPath(path, reference.InstanceID)
			switch reference.ReferenceKind {
			case "submodel":
				targetModelID := strings.TrimSpace(reference.TargetModelID)
				if targetModelID == "" {
					return errInvalidScene
				}
				result.SubmodelInstanceCount++
				if result.SubmodelInstanceCount > limits.MaxSubmodelInstances {
					return ErrExpansionLimit
				}
				if err := expandModel(targetModelID, world, instancePath, depth+1); err != nil {
					return err
				}
			case "part":
				partRef := strings.ToLower(strings.TrimSpace(reference.ReferenceName))
				if partRef == "" {
					return errInvalidScene
				}
				worldInstanceID := strings.Join(instancePath, "/")
				if worldInstanceIDs[worldInstanceID] {
					return errInvalidScene
				}
				worldInstanceIDs[worldInstanceID] = true
				if len(result.Parts) >= limits.MaxPartInstances {
					return ErrExpansionLimit
				}
				colorCode := strings.TrimSpace(reference.ColorCode)
				if colorCode == "" {
					colorCode = "16"
				}
				result.Parts = append(result.Parts, WorldPart{
					InstanceID:           worldInstanceID,
					DefinitionInstanceID: reference.InstanceID,
					PartRef:              partRef,
					ColorCode:            colorCode,
					Matrix:               world,
				})
			default:
				return errInvalidScene
			}
		}
		return nil
	}

	for _, root := range roots {
		root.InstanceID = strings.TrimSpace(root.InstanceID)
		root.TargetModelID = strings.TrimSpace(root.TargetModelID)
		if root.InstanceID == "" || root.TargetModelID == "" || rootInstanceIDs[root.InstanceID] {
			return Expansion{}, errInvalidScene
		}
		rootInstanceIDs[root.InstanceID] = true
		rootMatrix, err := matrix4(root.Transform)
		if err != nil {
			return Expansion{}, err
		}
		if err := expandModel(root.TargetModelID, rootMatrix, []string{root.InstanceID}, 0); err != nil {
			return Expansion{}, err
		}
	}
	if len(result.Parts) == 0 {
		return Expansion{}, errInvalidScene
	}
	return result, nil
}

// BOM 按规范化 LDraw Part 编号汇总真实场景实例，不对相同模型或相同 transform 去重。
func (e Expansion) BOM() map[string]int {
	result := make(map[string]int, len(e.Parts))
	for _, part := range e.Parts {
		result[part.PartRef]++
	}
	return result
}

func appendPath(path []string, instanceID string) []string {
	result := make([]string, len(path)+1)
	copy(result, path)
	result[len(path)] = instanceID
	return result
}

func matrix4(value Transform) ([16]float64, error) {
	if len(value.Matrix) != 9 {
		return [16]float64{}, errInvalidScene
	}
	for _, number := range []float64{value.Position.X, value.Position.Y, value.Position.Z} {
		if math.IsNaN(number) || math.IsInf(number, 0) {
			return [16]float64{}, errInvalidScene
		}
	}
	for _, number := range value.Matrix {
		if math.IsNaN(number) || math.IsInf(number, 0) {
			return [16]float64{}, errInvalidScene
		}
	}
	return [16]float64{
		value.Matrix[0], value.Matrix[3], value.Matrix[6], 0,
		value.Matrix[1], value.Matrix[4], value.Matrix[7], 0,
		value.Matrix[2], value.Matrix[5], value.Matrix[8], 0,
		value.Position.X, value.Position.Y, value.Position.Z, 1,
	}, nil
}

func multiply4(a, b [16]float64) [16]float64 {
	var result [16]float64
	for column := 0; column < 4; column++ {
		for row := 0; row < 4; row++ {
			for k := 0; k < 4; k++ {
				result[column*4+row] += a[k*4+row] * b[column*4+k]
			}
		}
	}
	return result
}
