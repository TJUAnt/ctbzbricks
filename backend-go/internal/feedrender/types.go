package feedrender

import "encoding/json"

const (
	// TaskType 是发布事务创建、Go Worker 消费的高质量 Feed 图片任务。
	TaskType = "component.feed_render.materialize"
	// RendererVersion 参与任务和 Artifact 幂等身份；构图、灯光或材质变化必须提升版本。
	RendererVersion = "component-feed-renderer-v4"
	RenderProfile   = "feed_card_3x2"
	ImageWidth      = 1200
	ImageHeight     = 800
	MaxGLBBytes     = 32 * 1024 * 1024
	MaxPNGBytes     = 32 * 1024 * 1024

	PathTracerEngine = "blender_cycles_4_1"
	RasterEngine     = "go_raster_v2"

	PathTracerTargetWidthRatio  = 0.52
	PathTracerTargetHeightRatio = 0.46
	PathTracerSamples           = 128
)

// Payload 只保存稳定机器标识；任务从数据库重新确认发布事件、owner 和 GLB Artifact 边界。
type Payload struct {
	EventID            string `json:"eventId"`
	ComponentVersionID string `json:"componentVersionId"`
	RenderProfile      string `json:"renderProfile"`
	RendererVersion    string `json:"rendererVersion"`
}

func payloadJSON(value Payload) json.RawMessage {
	encoded, _ := json.Marshal(value)
	return encoded
}
