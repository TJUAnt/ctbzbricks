package feedrender

import (
	"bytes"
	"context"
	_ "embed"
	"encoding/json"
	"errors"
	"image"
	"image/color"
	"image/png"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/ldrawmaterial"
)

const defaultPathTracerTimeout = 5 * time.Minute

//go:embed blender_cycles.py
var blenderCyclesScript []byte

// RenderedImage 返回经校验的 PNG 及实际使用的渲染边界，便于 Artifact 审计区分 Cycles 与光栅降级。
type RenderedImage struct {
	PNG               []byte
	Engine            string
	Fallback          bool
	FallbackCode      string
	TargetWidthRatio  float64
	TargetHeightRatio float64
}

// ImageRenderer 是 Go Worker 内部的派生图片边界；实现必须遵守 context 取消并返回完整 PNG。
type ImageRenderer interface {
	Render(context.Context, []byte) (RenderedImage, error)
}

type renderPipeline struct {
	primary  ImageRenderer
	fallback ImageRenderer
}

type rasterRenderer struct{}

type blenderCommand func(context.Context, string, []string, string) error

type blenderCyclesRenderer struct {
	path    string
	timeout time.Duration
	run     blenderCommand
}

type cyclesMaterial struct {
	ProfileVersion     string     `json:"profileVersion"`
	BaseColor          [3]float64 `json:"baseColor"`
	Alpha              float64    `json:"alpha"`
	Roughness          float64    `json:"roughness"`
	Metallic           float64    `json:"metallic"`
	IOR                float64    `json:"ior"`
	Transmission       float64    `json:"transmission"`
	Specular           float64    `json:"specular"`
	Clearcoat          float64    `json:"clearcoat"`
	ClearcoatRoughness float64    `json:"clearcoatRoughness"`
	EmissiveStrength   float64    `json:"emissiveStrength"`
	Class              string     `json:"class"`
}

// NewImageRenderer 创建 Cycles 优先、Go 光栅器托底的渲染管线。
// Blender 路径无效时不阻止 Worker 消费任务，以免已发布事件永久停在 pending。
func NewImageRenderer(blenderPath string, timeout time.Duration) ImageRenderer {
	pipeline := &renderPipeline{fallback: rasterRenderer{}}
	if timeout <= 0 {
		timeout = defaultPathTracerTimeout
	}
	if blenderPath != "" {
		if resolved, err := exec.LookPath(blenderPath); err == nil {
			pipeline.primary = &blenderCyclesRenderer{path: resolved, timeout: timeout, run: runBlenderCommand}
		}
	}
	return pipeline
}

func (p *renderPipeline) Render(ctx context.Context, source []byte) (RenderedImage, error) {
	fallbackCode := "path_tracer_unavailable"
	if p.primary != nil {
		result, err := p.primary.Render(ctx, source)
		if err == nil {
			return result, nil
		}
		if ctx.Err() != nil {
			return RenderedImage{}, ctx.Err()
		}
		if errors.Is(err, context.Canceled) {
			return RenderedImage{}, err
		}
		fallbackCode = "path_tracer_failed"
	}
	result, err := p.fallback.Render(ctx, source)
	if err != nil {
		return RenderedImage{}, err
	}
	result.Fallback = true
	result.FallbackCode = fallbackCode
	return result, nil
}

func (rasterRenderer) Render(ctx context.Context, source []byte) (RenderedImage, error) {
	if err := ctx.Err(); err != nil {
		return RenderedImage{}, err
	}
	value, err := RenderGLB(source)
	if err != nil {
		return RenderedImage{}, err
	}
	return RenderedImage{
		PNG: value, Engine: RasterEngine,
		TargetWidthRatio: targetWidthRatio, TargetHeightRatio: targetHeightRatio,
	}, nil
}

// Render 把每次 Cycles 执行限制在 Worker 创建的临时目录内。
// 命令参数只包含固定脚本和临时路径，不接受 Component 名称、文件名或其他用户内容。
func (r *blenderCyclesRenderer) Render(ctx context.Context, source []byte) (RenderedImage, error) {
	directory, err := os.MkdirTemp("", "brickbuilder-feed-cycles-*")
	if err != nil {
		return RenderedImage{}, err
	}
	defer os.RemoveAll(directory)
	inputPath := filepath.Join(directory, "input.glb")
	outputPath := filepath.Join(directory, "output.png")
	scriptPath := filepath.Join(directory, "render.py")
	materialPath := filepath.Join(directory, "materials.json")
	if err := os.WriteFile(inputPath, source, 0o600); err != nil {
		return RenderedImage{}, err
	}
	if err := os.WriteFile(scriptPath, blenderCyclesScript, 0o600); err != nil {
		return RenderedImage{}, err
	}
	materialData, err := cyclesMaterialOverrides(source)
	if err != nil {
		return RenderedImage{}, err
	}
	if err := os.WriteFile(materialPath, materialData, 0o600); err != nil {
		return RenderedImage{}, err
	}
	renderContext, cancel := context.WithTimeout(ctx, r.timeout)
	defer cancel()
	args := []string{
		"--background", "--factory-startup", "--disable-autoexec", "--python", scriptPath, "--",
		inputPath, outputPath, materialPath, strconv.Itoa(ImageWidth), strconv.Itoa(ImageHeight),
		strconv.FormatFloat(PathTracerTargetWidthRatio, 'f', -1, 64),
		strconv.FormatFloat(PathTracerTargetHeightRatio, 'f', -1, 64), strconv.Itoa(PathTracerSamples),
	}
	if err := r.run(renderContext, r.path, args, directory); err != nil {
		if renderContext.Err() != nil {
			return RenderedImage{}, renderContext.Err()
		}
		return RenderedImage{}, errors.New("cycles render failed")
	}
	file, err := os.Open(outputPath)
	if err != nil {
		return RenderedImage{}, errors.New("cycles output missing")
	}
	value, readErr := io.ReadAll(io.LimitReader(file, MaxPNGBytes+1))
	closeErr := file.Close()
	if readErr != nil || closeErr != nil || len(value) == 0 || len(value) > MaxPNGBytes {
		return RenderedImage{}, errors.New("cycles output invalid")
	}
	configuration, err := png.DecodeConfig(bytes.NewReader(value))
	if err != nil || configuration.Width != ImageWidth || configuration.Height != ImageHeight {
		return RenderedImage{}, errors.New("cycles output invalid")
	}
	value, err = cleanTransparentPNG(value)
	if err != nil || len(value) > MaxPNGBytes {
		return RenderedImage{}, errors.New("cycles output invalid")
	}
	return RenderedImage{
		PNG: value, Engine: PathTracerEngine,
		TargetWidthRatio: PathTracerTargetWidthRatio, TargetHeightRatio: PathTracerTargetHeightRatio,
	}, nil
}

// cleanTransparentPNG 去除 Cycles shadow catcher 在整张透明画布留下的低 alpha 黑雾。
// 28/255 是固定渲染配置下测得的环境底噪；线性重映射保留模型接触阴影并保持不透明像素不变。
func cleanTransparentPNG(source []byte) ([]byte, error) {
	decoded, err := png.Decode(bytes.NewReader(source))
	if err != nil {
		return nil, err
	}
	bounds := decoded.Bounds()
	cleaned := image.NewNRGBA(bounds)
	const alphaFloor = uint8(28)
	for y := bounds.Min.Y; y < bounds.Max.Y; y++ {
		for x := bounds.Min.X; x < bounds.Max.X; x++ {
			pixel := color.NRGBAModel.Convert(decoded.At(x, y)).(color.NRGBA)
			if pixel.A <= alphaFloor {
				pixel.R, pixel.G, pixel.B, pixel.A = 0, 0, 0, 0
			} else if pixel.A < 255 {
				pixel.A = uint8((uint16(pixel.A-alphaFloor)*255 + 113) / 227)
			}
			cleaned.SetNRGBA(x, y, pixel)
		}
	}
	var output bytes.Buffer
	encoder := png.Encoder{CompressionLevel: png.BestSpeed}
	if err := encoder.Encode(&output, cleaned); err != nil {
		return nil, err
	}
	return output.Bytes(), nil
}

// cyclesMaterialOverrides 把 Go 侧固定 LDraw 材质表交给 Cycles adapter，避免另外维护一套颜色分类。
// Studio 的 100000+code 嵌入材质也在这里归一化，使历史 v4 GLB 的印刷透明件可正确渲染。
func cyclesMaterialOverrides(source []byte) ([]byte, error) {
	document, _, err := parseGLB(source)
	if err != nil {
		return nil, err
	}
	result := make(map[string]cyclesMaterial, len(document.Materials))
	for _, material := range document.Materials {
		code, ok := strings.CutPrefix(strings.TrimSpace(material.Name), "LDraw ")
		if !ok {
			continue
		}
		definition := ldrawmaterial.Lookup(code)
		result[material.Name] = cyclesMaterial{
			ProfileVersion:     ldrawmaterial.ProfileVersion,
			BaseColor:          definition.BaseColor,
			Alpha:              definition.Alpha,
			Roughness:          definition.Roughness,
			Metallic:           definition.Metallic,
			IOR:                definition.IOR,
			Transmission:       definition.Transmission,
			Specular:           definition.Specular,
			Clearcoat:          definition.Clearcoat,
			ClearcoatRoughness: definition.ClearcoatRoughness,
			EmissiveStrength:   definition.EmissiveStrength,
			Class:              definition.Class,
		}
	}
	return json.Marshal(result)
}

func runBlenderCommand(ctx context.Context, executable string, args []string, directory string) error {
	if err := os.MkdirAll(filepath.Join(directory, "blender-user"), 0o700); err != nil {
		return err
	}
	command := exec.CommandContext(ctx, executable, args...)
	command.Dir = directory
	command.Stdout = io.Discard
	command.Stderr = io.Discard
	command.Env = blenderEnvironment(directory)
	return command.Run()
}

// blenderEnvironment 只传递启动渲染器所需的操作系统变量，并把 Blender 用户目录锁在临时目录。
// Worker 的数据库、JWT 与对象存储凭据不会进入外部进程环境。
func blenderEnvironment(directory string) []string {
	configurationRoot := filepath.Join(directory, "blender-user")
	environment := []string{
		"BLENDER_USER_CONFIG=" + configurationRoot,
		"BLENDER_USER_SCRIPTS=" + configurationRoot,
		"BLENDER_USER_DATAFILES=" + configurationRoot,
	}
	for _, name := range []string{"PATH", "TMPDIR", "TEMP", "TMP", "LANG", "LC_ALL", "SYSTEMROOT", "WINDIR", "COMSPEC", "PATHEXT"} {
		if value, ok := os.LookupEnv(name); ok {
			environment = append(environment, name+"="+value)
		}
	}
	return environment
}
