package observability

import (
	"encoding/json"
	"io"
	"net/http"
	"sort"
	"strings"
	"sync"
	"time"
	"unicode/utf8"

	"github.com/ctbzbricks/brickbuilder/backend-go/internal/apierror"
	"github.com/gin-gonic/gin"
)

// I18nEvent 仅接受客户端资源诊断机器字段，不接受异常正文、用户内容或凭据。
type I18nEvent struct {
	Kind      string `json:"kind"`
	Locale    string `json:"locale"`
	Namespace string `json:"namespace"`
	Code      string `json:"code"`
}

// I18nTelemetry 是有界进程指标，不承担持久业务状态；跨实例汇总由外部监控负责。
type I18nTelemetry struct {
	mu       sync.Mutex
	counts   map[I18nEvent]uint64
	hourly   map[string]map[I18nEvent]uint64
	overflow uint64
	now      func() time.Time
}

// NewI18nTelemetry 为每个 API 实例创建独立的 1000 维度、24 小时诊断窗口。
func NewI18nTelemetry() *I18nTelemetry {
	return &I18nTelemetry{counts: map[I18nEvent]uint64{}, hourly: map[string]map[I18nEvent]uint64{}, now: time.Now}
}

// Register 提供匿名前端也可访问的有界诊断接口；不访问业务对象或旧 Python 服务。
func (t *I18nTelemetry) Register(r *gin.Engine) {
	r.POST("/api/v1/i18n/events", t.record)
	r.GET("/api/v1/i18n/metrics", t.metrics)
}
func (t *I18nTelemetry) prune(now time.Time) {
	cutoff := now.UTC().Truncate(time.Hour).Add(-23 * time.Hour).Format(time.RFC3339)
	for hour := range t.hourly {
		if hour < cutoff {
			delete(t.hourly, hour)
		}
	}
}

// record 验证字段与事件种类后计数，超过维度预算只累计 overflow，避免内存随输入无限增长。
func (t *I18nTelemetry) record(c *gin.Context) {
	var event I18nEvent
	d := json.NewDecoder(c.Request.Body)
	d.DisallowUnknownFields()
	if err := d.Decode(&event); err != nil {
		apierror.Write(c, apierror.New("request.validation_failed", 422, map[string]any{"field": "body"}))
		return
	}
	if err := d.Decode(&struct{}{}); err != io.EOF {
		apierror.Write(c, apierror.New("request.validation_failed", 422, map[string]any{"field": "body"}))
		return
	}
	if event.Kind != "unknown_key" && event.Kind != "unknown_api_code" && event.Kind != "locale_fallback" {
		apierror.Write(c, apierror.New("request.i18n_event_kind_invalid", 422, nil))
		return
	}
	for _, v := range []struct {
		s   string
		max int
	}{{event.Locale, 35}, {event.Namespace, 64}, {event.Code, 160}} {
		if strings.TrimSpace(v.s) == "" || utf8.RuneCountInString(v.s) > v.max {
			apierror.Write(c, apierror.New("request.validation_failed", 422, map[string]any{"field": "event"}))
			return
		}
	}
	event.Locale = strings.Join(strings.Fields(event.Locale), " ")
	event.Namespace = strings.Join(strings.Fields(event.Namespace), " ")
	event.Code = strings.Join(strings.Fields(event.Code), " ")
	t.mu.Lock()
	defer t.mu.Unlock()
	now := t.now()
	t.prune(now)
	if _, ok := t.counts[event]; !ok && len(t.counts) >= 1000 {
		t.overflow++
		c.Status(http.StatusNoContent)
		return
	}
	t.counts[event]++
	hour := now.UTC().Truncate(time.Hour).Format(time.RFC3339)
	if t.hourly[hour] == nil {
		t.hourly[hour] = map[I18nEvent]uint64{}
	}
	t.hourly[hour][event]++
	c.Status(http.StatusNoContent)
}

// metrics 返回稳定排序的诊断快照；进程重启归零，趋势只保留最近 24 个 UTC 小时。
func (t *I18nTelemetry) metrics(c *gin.Context) {
	t.mu.Lock()
	defer t.mu.Unlock()
	t.prune(t.now())
	type metric struct {
		I18nEvent
		Count uint64 `json:"count"`
	}
	type hourlyMetric struct {
		metric
		Hour string `json:"hour"`
	}
	events := []metric{}
	hourly := []hourlyMetric{}
	totals := map[string]uint64{}
	for e, count := range t.counts {
		events = append(events, metric{e, count})
		totals[e.Kind] += count
	}
	key := func(e I18nEvent) string { return e.Kind + "\x00" + e.Locale + "\x00" + e.Namespace + "\x00" + e.Code }
	sort.Slice(events, func(i, j int) bool { return key(events[i].I18nEvent) < key(events[j].I18nEvent) })
	for hour, bucket := range t.hourly {
		for e, count := range bucket {
			hourly = append(hourly, hourlyMetric{metric{e, count}, hour})
		}
	}
	sort.Slice(hourly, func(i, j int) bool {
		if hourly[i].Hour != hourly[j].Hour {
			return hourly[i].Hour < hourly[j].Hour
		}
		return key(hourly[i].I18nEvent) < key(hourly[j].I18nEvent)
	})
	c.JSON(200, gin.H{"unknownKeyCount": totals["unknown_key"], "unknownApiCodeCount": totals["unknown_api_code"], "localeFallbackCount": totals["locale_fallback"], "metricOverflowCount": t.overflow, "events": events, "hourly": hourly})
}
