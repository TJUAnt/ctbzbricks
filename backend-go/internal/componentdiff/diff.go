// Package componentdiff 提供不可变 Component SceneSnapshot 之间的确定性结构差异计算。
package componentdiff

import (
	"encoding/json"
	"errors"
	"fmt"
	"math"
	"sort"
	"strings"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/scene"
)

const (
	// AlgorithmVersion 是对外可观察的算法契约版本；匹配规则变化时必须提升该值。
	AlgorithmVersion = "component-scene-diff-v1"

	defaultMaxInstances = 50_000
	defaultMaxDetails   = 10_000
	defaultTolerance    = 1e-6
)

var (
	// ErrInvalidSnapshot 表示任一输入不是可展开的 SceneSnapshot document。
	ErrInvalidSnapshot = errors.New("invalid component scene snapshot")
	// ErrTooLarge 表示输入实例数超过同步计算的有界上限。
	ErrTooLarge = errors.New("component scene diff exceeds instance limit")
)

// Options 控制同步 diff 的资源边界和浮点归一化精度。
type Options struct {
	MaxInstances    int
	MaxDetails      int
	MatrixTolerance float64
}

// PartState 是差异两侧一个展开后 Part 实例的机器投影，不包含本地化名称。
type PartState struct {
	InstanceID  string      `json:"instanceId"`
	PartRef     string      `json:"partRef"`
	ColorCode   string      `json:"colorCode"`
	WorldMatrix [16]float64 `json:"worldMatrix"`
}

// TransformDelta 说明 transform 变化发生在平移分量、3x3 线性分量或两者。
type TransformDelta struct {
	TranslationChanged     bool `json:"translationChanged"`
	LinearTransformChanged bool `json:"linearTransformChanged"`
}

// InstanceChange 表示一个确定匹配的实例级变化。
// Kind 只使用 part_added、part_removed、transform_changed、color_changed、part_replaced。
type InstanceChange struct {
	Kind           string          `json:"kind"`
	Before         *PartState      `json:"before,omitempty"`
	After          *PartState      `json:"after,omitempty"`
	TransformDelta *TransformDelta `json:"transformDelta,omitempty"`
}

// BOMChange 表示一个 LDraw Part 编号在两个版本之间的数量变化。
type BOMChange struct {
	PartRef        string `json:"partRef"`
	BeforeQuantity int    `json:"beforeQuantity"`
	AfterQuantity  int    `json:"afterQuantity"`
	Delta          int    `json:"delta"`
}

// AmbiguousGroup 保存无法可靠一一对应的同 Part、同颜色重复实例。
// 算法宁可返回歧义，也不会用数组顺序伪造 transform_changed。
type AmbiguousGroup struct {
	PartRef           string   `json:"partRef"`
	ColorCode         string   `json:"colorCode"`
	BeforeInstanceIDs []string `json:"beforeInstanceIds"`
	AfterInstanceIDs  []string `json:"afterInstanceIds"`
}

// Summary 是完整计数；即使明细因 MaxDetails 截断，Summary 仍覆盖全部实例。
type Summary struct {
	BeforeInstances           int `json:"beforeInstances"`
	AfterInstances            int `json:"afterInstances"`
	UnchangedInstances        int `json:"unchangedInstances"`
	AddedInstances            int `json:"addedInstances"`
	RemovedInstances          int `json:"removedInstances"`
	TransformChangedInstances int `json:"transformChangedInstances"`
	ColorChangedInstances     int `json:"colorChangedInstances"`
	ReplacedInstances         int `json:"replacedInstances"`
	AmbiguousBeforeInstances  int `json:"ambiguousBeforeInstances"`
	AmbiguousAfterInstances   int `json:"ambiguousAfterInstances"`
	AmbiguousGroups           int `json:"ambiguousGroups"`
	BOMChangedPartTypes       int `json:"bomChangedPartTypes"`
}

// Result 是与存储无关的纯计算结果，可由 HTTP API、CLI 或测试共同消费。
type Result struct {
	AlgorithmVersion string           `json:"algorithmVersion"`
	Summary          Summary          `json:"summary"`
	BOMChanges       []BOMChange      `json:"bomChanges"`
	InstanceChanges  []InstanceChange `json:"instanceChanges"`
	AmbiguousGroups  []AmbiguousGroup `json:"ambiguousGroups"`
	Truncated        bool             `json:"truncated"`
}

type normalizedPart struct {
	state  PartState
	matrix [16]int64
	used   bool
}

// CompareJSON 展开两份 SceneSnapshot document，并在严格实例上限内计算结构差异。
func CompareJSON(beforeRaw, afterRaw json.RawMessage, options Options) (Result, error) {
	options = normalizeOptions(options)
	limits := scene.ExpansionLimits{MaxPartInstances: options.MaxInstances, MaxSubmodelInstances: options.MaxInstances}
	before, err := scene.ExpandJSONWithLimits(beforeRaw, limits)
	if err != nil {
		if errors.Is(err, scene.ErrExpansionLimit) {
			return Result{}, ErrTooLarge
		}
		return Result{}, ErrInvalidSnapshot
	}
	after, err := scene.ExpandJSONWithLimits(afterRaw, limits)
	if err != nil {
		if errors.Is(err, scene.ErrExpansionLimit) {
			return Result{}, ErrTooLarge
		}
		return Result{}, ErrInvalidSnapshot
	}
	return CompareParts(before.Parts, after.Parts, options)
}

// CompareFromEmptyJSON 把首个版本视为从空树创建，因而所有实例均为新增。
func CompareFromEmptyJSON(afterRaw json.RawMessage, options Options) (Result, error) {
	options = normalizeOptions(options)
	limits := scene.ExpansionLimits{MaxPartInstances: options.MaxInstances, MaxSubmodelInstances: options.MaxInstances}
	after, err := scene.ExpandJSONWithLimits(afterRaw, limits)
	if err != nil {
		if errors.Is(err, scene.ErrExpansionLimit) {
			return Result{}, ErrTooLarge
		}
		return Result{}, ErrInvalidSnapshot
	}
	return CompareParts(nil, after.Parts, options)
}

// CompareParts 对已展开实例执行确定性匹配。调用方不得把 GLB mesh 当作结构权威输入。
func CompareParts(beforeParts, afterParts []scene.WorldPart, options Options) (Result, error) {
	options = normalizeOptions(options)
	if len(beforeParts) > options.MaxInstances || len(afterParts) > options.MaxInstances {
		return Result{}, ErrTooLarge
	}

	before := normalizeParts(beforeParts, options.MatrixTolerance)
	after := normalizeParts(afterParts, options.MatrixTolerance)
	result := Result{
		AlgorithmVersion: AlgorithmVersion,
		Summary:          Summary{BeforeInstances: len(before), AfterInstances: len(after)},
		BOMChanges:       diffBOM(before, after),
		InstanceChanges:  make([]InstanceChange, 0),
		AmbiguousGroups:  make([]AmbiguousGroup, 0),
	}
	result.Summary.BOMChangedPartTypes = len(result.BOMChanges)

	// 分阶段匹配保持语义稳定：完全相同 > 改色 > 替换零件 > 唯一实例移动。
	matchPairs(before, after, exactKey, func(_, _ normalizedPart) {
		result.Summary.UnchangedInstances++
	})
	matchPairs(before, after, colorKey, func(left, right normalizedPart) {
		result.Summary.ColorChangedInstances++
		appendChange(&result, options.MaxDetails, InstanceChange{Kind: "color_changed", Before: statePointer(left), After: statePointer(right)})
	})
	matchPairs(before, after, replacementKey, func(left, right normalizedPart) {
		result.Summary.ReplacedInstances++
		appendChange(&result, options.MaxDetails, InstanceChange{Kind: "part_replaced", Before: statePointer(left), After: statePointer(right)})
	})
	matchUniqueTransforms(before, after, &result, options.MaxDetails)
	collectAmbiguous(before, after, &result, options.MaxDetails)
	collectRemainder(before, after, &result, options.MaxDetails)
	return result, nil
}

func normalizeOptions(options Options) Options {
	if options.MaxInstances <= 0 {
		options.MaxInstances = defaultMaxInstances
	}
	if options.MaxDetails <= 0 {
		options.MaxDetails = defaultMaxDetails
	}
	if options.MatrixTolerance <= 0 || math.IsNaN(options.MatrixTolerance) || math.IsInf(options.MatrixTolerance, 0) {
		options.MatrixTolerance = defaultTolerance
	}
	return options
}

func normalizeParts(parts []scene.WorldPart, tolerance float64) []normalizedPart {
	result := make([]normalizedPart, 0, len(parts))
	for _, part := range parts {
		state := PartState{InstanceID: part.InstanceID, PartRef: strings.ToLower(strings.TrimSpace(part.PartRef)), ColorCode: strings.TrimSpace(part.ColorCode), WorldMatrix: part.Matrix}
		var matrix [16]int64
		for index, value := range part.Matrix {
			matrix[index] = int64(math.Round(value / tolerance))
		}
		result = append(result, normalizedPart{state: state, matrix: matrix})
	}
	sort.Slice(result, func(i, j int) bool { return stablePartKey(result[i]) < stablePartKey(result[j]) })
	return result
}

func matchPairs(before, after []normalizedPart, key func(normalizedPart) string, matched func(normalizedPart, normalizedPart)) {
	leftGroups := unusedGroups(before, key)
	rightGroups := unusedGroups(after, key)
	keys := sharedKeys(leftGroups, rightGroups)
	for _, groupKey := range keys {
		leftIndexes := leftGroups[groupKey]
		rightIndexes := rightGroups[groupKey]
		count := min(len(leftIndexes), len(rightIndexes))
		for index := 0; index < count; index++ {
			leftIndex, rightIndex := leftIndexes[index], rightIndexes[index]
			before[leftIndex].used = true
			after[rightIndex].used = true
			matched(before[leftIndex], after[rightIndex])
		}
	}
}

func matchUniqueTransforms(before, after []normalizedPart, result *Result, maxDetails int) {
	leftGroups := unusedGroups(before, identityKey)
	rightGroups := unusedGroups(after, identityKey)
	for _, key := range sharedKeys(leftGroups, rightGroups) {
		leftIndexes, rightIndexes := leftGroups[key], rightGroups[key]
		if len(leftIndexes) != 1 || len(rightIndexes) != 1 {
			continue
		}
		leftIndex, rightIndex := leftIndexes[0], rightIndexes[0]
		before[leftIndex].used = true
		after[rightIndex].used = true
		result.Summary.TransformChangedInstances++
		delta := transformDelta(before[leftIndex].matrix, after[rightIndex].matrix)
		appendChange(result, maxDetails, InstanceChange{Kind: "transform_changed", Before: statePointer(before[leftIndex]), After: statePointer(after[rightIndex]), TransformDelta: &delta})
	}
}

func collectAmbiguous(before, after []normalizedPart, result *Result, maxDetails int) {
	leftGroups := unusedGroups(before, identityKey)
	rightGroups := unusedGroups(after, identityKey)
	for _, key := range sharedKeys(leftGroups, rightGroups) {
		leftIndexes, rightIndexes := leftGroups[key], rightGroups[key]
		if len(leftIndexes) == 1 && len(rightIndexes) == 1 {
			continue
		}
		group := AmbiguousGroup{PartRef: before[leftIndexes[0]].state.PartRef, ColorCode: before[leftIndexes[0]].state.ColorCode}
		for _, index := range leftIndexes {
			before[index].used = true
			group.BeforeInstanceIDs = append(group.BeforeInstanceIDs, before[index].state.InstanceID)
		}
		for _, index := range rightIndexes {
			after[index].used = true
			group.AfterInstanceIDs = append(group.AfterInstanceIDs, after[index].state.InstanceID)
		}
		result.Summary.AmbiguousGroups++
		result.Summary.AmbiguousBeforeInstances += len(leftIndexes)
		result.Summary.AmbiguousAfterInstances += len(rightIndexes)
		// 一个歧义组可能包含大量实例 ID；只有整个组都落在明细预算内才返回，避免单组绕过响应上限。
		if detailCount(*result)+len(group.BeforeInstanceIDs)+len(group.AfterInstanceIDs) <= maxDetails {
			result.AmbiguousGroups = append(result.AmbiguousGroups, group)
		} else {
			result.Truncated = true
		}
	}
}

func collectRemainder(before, after []normalizedPart, result *Result, maxDetails int) {
	for index := range before {
		if before[index].used {
			continue
		}
		result.Summary.RemovedInstances++
		appendChange(result, maxDetails, InstanceChange{Kind: "part_removed", Before: statePointer(before[index])})
	}
	for index := range after {
		if after[index].used {
			continue
		}
		result.Summary.AddedInstances++
		appendChange(result, maxDetails, InstanceChange{Kind: "part_added", After: statePointer(after[index])})
	}
}

func appendChange(result *Result, maxDetails int, change InstanceChange) {
	if detailCount(*result) >= maxDetails {
		result.Truncated = true
		return
	}
	result.InstanceChanges = append(result.InstanceChanges, change)
}

func detailCount(result Result) int {
	count := len(result.InstanceChanges)
	for _, group := range result.AmbiguousGroups {
		count += len(group.BeforeInstanceIDs) + len(group.AfterInstanceIDs)
	}
	return count
}

func unusedGroups(parts []normalizedPart, key func(normalizedPart) string) map[string][]int {
	groups := make(map[string][]int)
	for index := range parts {
		if !parts[index].used {
			groups[key(parts[index])] = append(groups[key(parts[index])], index)
		}
	}
	return groups
}

func sharedKeys(left, right map[string][]int) []string {
	keys := make([]string, 0)
	for key := range left {
		if len(right[key]) > 0 {
			keys = append(keys, key)
		}
	}
	sort.Strings(keys)
	return keys
}

func exactKey(part normalizedPart) string { return identityKey(part) + "|" + matrixKey(part.matrix) }
func colorKey(part normalizedPart) string { return part.state.PartRef + "|" + matrixKey(part.matrix) }
func replacementKey(part normalizedPart) string {
	return part.state.ColorCode + "|" + matrixKey(part.matrix)
}
func identityKey(part normalizedPart) string { return part.state.PartRef + "|" + part.state.ColorCode }

func matrixKey(matrix [16]int64) string {
	return fmt.Sprint(matrix)
}

func stablePartKey(part normalizedPart) string {
	return exactKey(part) + "|" + part.state.InstanceID
}

func statePointer(part normalizedPart) *PartState {
	state := part.state
	return &state
}

func transformDelta(before, after [16]int64) TransformDelta {
	delta := TransformDelta{}
	for index := range before {
		if before[index] == after[index] {
			continue
		}
		if index == 12 || index == 13 || index == 14 {
			delta.TranslationChanged = true
		} else if index != 3 && index != 7 && index != 11 && index != 15 {
			delta.LinearTransformChanged = true
		}
	}
	return delta
}

func diffBOM(before, after []normalizedPart) []BOMChange {
	left := make(map[string]int)
	right := make(map[string]int)
	for _, part := range before {
		left[part.state.PartRef]++
	}
	for _, part := range after {
		right[part.state.PartRef]++
	}
	keys := make(map[string]struct{}, len(left)+len(right))
	for key := range left {
		keys[key] = struct{}{}
	}
	for key := range right {
		keys[key] = struct{}{}
	}
	ordered := make([]string, 0, len(keys))
	for key := range keys {
		ordered = append(ordered, key)
	}
	sort.Strings(ordered)
	changes := make([]BOMChange, 0)
	for _, key := range ordered {
		if left[key] == right[key] {
			continue
		}
		changes = append(changes, BOMChange{PartRef: key, BeforeQuantity: left[key], AfterQuantity: right[key], Delta: right[key] - left[key]})
	}
	return changes
}

func min(left, right int) int {
	if left < right {
		return left
	}
	return right
}
