package workbench

import (
	"bytes"
	"context"
	"encoding/binary"
	"errors"
	"os"
	"os/exec"
	"path/filepath"
)

// PartGLBOptimizer 定义 Part 派生模型的压缩边界；实现必须输出仍可独立加载的 GLB，
// 且不得改变上游已经完成的坐标系、法线与材质语义。
type PartGLBOptimizer interface {
	Optimize(context.Context, []byte) ([]byte, error)
}

// GLTFPackOptimizer 通过原生 gltfpack 生成 EXT_meshopt_compression 数据。
// 外部进程只处理 Worker 创建的临时文件，不接收用户可控命令参数。
type GLTFPackOptimizer struct {
	path string
}

const partPreviewGLTFPackVersion = "gltfpack 1.2"

// NewGLTFPackOptimizer 在 Worker 启动时解析可执行文件，避免任务运行到一半才发现压缩器缺失。
func NewGLTFPackOptimizer(path string) (*GLTFPackOptimizer, error) {
	if filepath.IsAbs(path) == false && filepath.Dir(path) != "." {
		absolute, err := filepath.Abs(path)
		if err != nil {
			return nil, errors.New("PART_PREVIEW_GLTFPACK_PATH is invalid")
		}
		path = absolute
	}
	resolved, err := exec.LookPath(path)
	if err != nil {
		return nil, errors.New("PART_PREVIEW_GLTFPACK_PATH must point to an executable gltfpack")
	}
	// generator version 必须对应可复现的压缩器版本；任意升级都需要显式提升 PartPreviewGeneratorVersion。
	version, err := exec.Command(resolved, "-v").Output()
	if err != nil || string(bytes.TrimSpace(version)) != partPreviewGLTFPackVersion {
		return nil, errors.New("PART_PREVIEW_GLTFPACK_PATH must use gltfpack 1.2")
	}
	return &GLTFPackOptimizer{path: resolved}, nil
}

// Optimize 使用 gltfpack 的压缩模式；保留节点名与 extras，便于调试和后续元数据扩展。
func (o *GLTFPackOptimizer) Optimize(ctx context.Context, source []byte) ([]byte, error) {
	directory, err := os.MkdirTemp("", "brickbuilder-part-glb-*")
	if err != nil {
		return nil, err
	}
	defer os.RemoveAll(directory)
	inputPath := filepath.Join(directory, "input.glb")
	outputPath := filepath.Join(directory, "output.glb")
	if err := os.WriteFile(inputPath, source, 0o600); err != nil {
		return nil, err
	}
	command := exec.CommandContext(ctx, o.path, "-i", inputPath, "-o", outputPath, "-cc", "-kn", "-ke")
	if output, runErr := command.CombinedOutput(); runErr != nil {
		return nil, errors.New("gltfpack failed: " + string(bytes.TrimSpace(output)))
	}
	optimized, err := os.ReadFile(outputPath)
	if err != nil {
		return nil, err
	}
	if !isMeshoptGLB(optimized) {
		return nil, errors.New("gltfpack output is not a meshopt-compressed GLB")
	}
	return optimized, nil
}

func isMeshoptGLB(data []byte) bool {
	if len(data) < 20 || string(data[:4]) != "glTF" || binary.LittleEndian.Uint32(data[4:8]) != 2 {
		return false
	}
	jsonLength := int(binary.LittleEndian.Uint32(data[12:16]))
	if jsonLength <= 0 || 20+jsonLength > len(data) || string(data[16:20]) != "JSON" {
		return false
	}
	return bytes.Contains(data[20:20+jsonLength], []byte("EXT_meshopt_compression"))
}
