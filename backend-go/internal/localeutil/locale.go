// Package localeutil 统一 Component Repo 的 locale 规范化契约。
package localeutil

import "strings"

const defaultDisplayLocale = "zh-CN"

// Normalize 对写入、任务和其他严格输入执行受支持 locale 校验。
// 返回 false 时调用方必须使用稳定 validation error，不能静默保存 fallback locale。
func Normalize(input string) (string, bool) {
	normalized := strings.TrimSpace(strings.ReplaceAll(input, "_", "-"))
	lower := strings.ToLower(normalized)
	switch {
	case lower == "zh" || lower == "zh-cn" || strings.HasPrefix(lower, "zh-hans-"):
		return "zh-CN", true
	case lower == "en" || lower == "en-us" || strings.HasPrefix(lower, "en-"):
		return "en-US", true
	default:
		return "", false
	}
}

// Display 对只读展示请求执行规范化；缺省或不支持的 locale 按既有产品契约回落到 zh-CN。
func Display(input string) string {
	locale, ok := Normalize(input)
	if !ok {
		return defaultDisplayLocale
	}
	return locale
}
