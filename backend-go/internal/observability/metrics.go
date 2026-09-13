package observability

import (
	"fmt"
	"net/http"
	"sync/atomic"
	"time"
)

const (
	// ComponentVersionPublishedEvent 是 WATCH-2 冻结的发布事件机器类型，不得写入用户内容或本地化文案。
	ComponentVersionPublishedEvent = "component.version.published.v1"
	// DomainEventCommitted 表示包含领域事件的发布事务已确认提交。
	DomainEventCommitted = "committed"
	// DomainEventFailed 表示已进入事件写入阶段的发布事务最终未提交。
	DomainEventFailed = "failed"
	// ComponentWatchActionWatch 与 ComponentWatchActionUnwatch 是 Watch mutation 指标允许的固定动作标签。
	ComponentWatchActionWatch   = "watch"
	ComponentWatchActionUnwatch = "unwatch"
	// ComponentWatchMutationSucceeded 包含产生状态变化和幂等空操作；Failed 表示 mutation 未成功完成。
	ComponentWatchMutationSucceeded = "succeeded"
	ComponentWatchMutationFailed    = "failed"
	// ComponentWatchFeedSucceeded/Failed 是动态 Feed 请求允许的固定结果标签。
	ComponentWatchFeedSucceeded = "succeeded"
	ComponentWatchFeedFailed    = "failed"
)

var componentWatchFeedDurationBuckets = [...]time.Duration{
	10 * time.Millisecond, 50 * time.Millisecond, 100 * time.Millisecond, 250 * time.Millisecond,
	500 * time.Millisecond, time.Second, 2 * time.Second,
}

// Registry 保存单个 API 进程的低基数运维指标，并以 Prometheus 文本格式提供采集。
// 动态 Watch Feed 没有 fan-out backlog；读取性能由标准 HTTP/数据库观测承担。
type Registry struct {
	componentDomainEventCommitted atomic.Uint64
	componentDomainEventFailed    atomic.Uint64
	componentWatchSucceeded       atomic.Uint64
	componentWatchFailed          atomic.Uint64
	componentUnwatchSucceeded     atomic.Uint64
	componentUnwatchFailed        atomic.Uint64
	componentWatchFeedSucceeded   atomic.Uint64
	componentWatchFeedFailed      atomic.Uint64
	componentWatchFeedBuckets     [len(componentWatchFeedDurationBuckets)]atomic.Uint64
	componentWatchFeedCount       atomic.Uint64
	componentWatchFeedNanos       atomic.Uint64
}

// NewRegistry 创建一个空的进程级指标注册表。
func NewRegistry() *Registry {
	return &Registry{}
}

// RecordComponentDomainEvent 记录发布事件事务的最终结果。
// eventType 与 result 只接受冻结机器值，防止请求数据进入指标标签造成高基数或信息泄露。
func (r *Registry) RecordComponentDomainEvent(eventType, result string) {
	if r == nil || eventType != ComponentVersionPublishedEvent {
		return
	}
	switch result {
	case DomainEventCommitted:
		r.componentDomainEventCommitted.Add(1)
	case DomainEventFailed:
		r.componentDomainEventFailed.Add(1)
	}
}

// ComponentDomainEventCounts 返回发布事件结果计数，供契约测试和进程内诊断使用。
func (r *Registry) ComponentDomainEventCounts() (committed, failed uint64) {
	if r == nil {
		return 0, 0
	}
	return r.componentDomainEventCommitted.Load(), r.componentDomainEventFailed.Load()
}

// RecordComponentWatchMutation 记录 Watch/Unwatch 应用服务调用的最终结果。
// action 与 result 只接受固定机器值，禁止 actor、Component ID 或错误正文进入指标标签。
func (r *Registry) RecordComponentWatchMutation(action, result string) {
	if r == nil {
		return
	}
	var counter *atomic.Uint64
	switch {
	case action == ComponentWatchActionWatch && result == ComponentWatchMutationSucceeded:
		counter = &r.componentWatchSucceeded
	case action == ComponentWatchActionWatch && result == ComponentWatchMutationFailed:
		counter = &r.componentWatchFailed
	case action == ComponentWatchActionUnwatch && result == ComponentWatchMutationSucceeded:
		counter = &r.componentUnwatchSucceeded
	case action == ComponentWatchActionUnwatch && result == ComponentWatchMutationFailed:
		counter = &r.componentUnwatchFailed
	default:
		return
	}
	counter.Add(1)
}

// ComponentWatchMutationCounts 返回四个固定结果桶，供契约测试和进程内诊断使用。
func (r *Registry) ComponentWatchMutationCounts() (watchSucceeded, watchFailed, unwatchSucceeded, unwatchFailed uint64) {
	if r == nil {
		return 0, 0, 0, 0
	}
	return r.componentWatchSucceeded.Load(), r.componentWatchFailed.Load(),
		r.componentUnwatchSucceeded.Load(), r.componentUnwatchFailed.Load()
}

// RecordComponentWatchFeed 记录一次动态 Feed 服务调用及耗时；结果标签固定，避免 actor 或查询参数进入指标。
func (r *Registry) RecordComponentWatchFeed(result string, duration time.Duration) {
	if r == nil || duration < 0 {
		return
	}
	switch result {
	case ComponentWatchFeedSucceeded:
		r.componentWatchFeedSucceeded.Add(1)
	case ComponentWatchFeedFailed:
		r.componentWatchFeedFailed.Add(1)
	default:
		return
	}
	r.componentWatchFeedCount.Add(1)
	r.componentWatchFeedNanos.Add(uint64(duration))
	for index, upperBound := range componentWatchFeedDurationBuckets {
		if duration <= upperBound {
			r.componentWatchFeedBuckets[index].Add(1)
		}
	}
}

// ComponentWatchFeedCounts 返回动态 Feed 的固定结果桶，供契约测试使用。
func (r *Registry) ComponentWatchFeedCounts() (succeeded, failed uint64) {
	if r == nil {
		return 0, 0
	}
	return r.componentWatchFeedSucceeded.Load(), r.componentWatchFeedFailed.Load()
}

// ServeHTTP 输出固定、无用户数据的 Prometheus 0.0.4 文本；该端点应由部署入口限制为监控网络访问。
func (r *Registry) ServeHTTP(response http.ResponseWriter, _ *http.Request) {
	committed, failed := r.ComponentDomainEventCounts()
	response.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	response.WriteHeader(http.StatusOK)
	_, _ = fmt.Fprintln(response, "# HELP component_domain_event_total Component domain event transaction outcomes.")
	_, _ = fmt.Fprintln(response, "# TYPE component_domain_event_total counter")
	_, _ = fmt.Fprintf(response, "component_domain_event_total{event_type=%q,result=%q} %d\n", ComponentVersionPublishedEvent, DomainEventCommitted, committed)
	_, _ = fmt.Fprintf(response, "component_domain_event_total{event_type=%q,result=%q} %d\n", ComponentVersionPublishedEvent, DomainEventFailed, failed)
	watchSucceeded, watchFailed, unwatchSucceeded, unwatchFailed := r.ComponentWatchMutationCounts()
	_, _ = fmt.Fprintln(response, "# HELP component_watch_mutation_total Component Watch mutation outcomes.")
	_, _ = fmt.Fprintln(response, "# TYPE component_watch_mutation_total counter")
	_, _ = fmt.Fprintf(response, "component_watch_mutation_total{action=%q,result=%q} %d\n", ComponentWatchActionWatch, ComponentWatchMutationSucceeded, watchSucceeded)
	_, _ = fmt.Fprintf(response, "component_watch_mutation_total{action=%q,result=%q} %d\n", ComponentWatchActionWatch, ComponentWatchMutationFailed, watchFailed)
	_, _ = fmt.Fprintf(response, "component_watch_mutation_total{action=%q,result=%q} %d\n", ComponentWatchActionUnwatch, ComponentWatchMutationSucceeded, unwatchSucceeded)
	_, _ = fmt.Fprintf(response, "component_watch_mutation_total{action=%q,result=%q} %d\n", ComponentWatchActionUnwatch, ComponentWatchMutationFailed, unwatchFailed)
	feedSucceeded, feedFailed := r.ComponentWatchFeedCounts()
	_, _ = fmt.Fprintln(response, "# HELP component_watch_feed_requests_total Dynamic Component Watch Feed request outcomes.")
	_, _ = fmt.Fprintln(response, "# TYPE component_watch_feed_requests_total counter")
	_, _ = fmt.Fprintf(response, "component_watch_feed_requests_total{result=%q} %d\n", ComponentWatchFeedSucceeded, feedSucceeded)
	_, _ = fmt.Fprintf(response, "component_watch_feed_requests_total{result=%q} %d\n", ComponentWatchFeedFailed, feedFailed)
	_, _ = fmt.Fprintln(response, "# HELP component_watch_feed_duration_seconds Dynamic Component Watch Feed service duration.")
	_, _ = fmt.Fprintln(response, "# TYPE component_watch_feed_duration_seconds histogram")
	for index, upperBound := range componentWatchFeedDurationBuckets {
		_, _ = fmt.Fprintf(response, "component_watch_feed_duration_seconds_bucket{le=%q} %d\n", formatSeconds(upperBound), r.componentWatchFeedBuckets[index].Load())
	}
	_, _ = fmt.Fprintf(response, "component_watch_feed_duration_seconds_bucket{le=%q} %d\n", "+Inf", r.componentWatchFeedCount.Load())
	_, _ = fmt.Fprintf(response, "component_watch_feed_duration_seconds_sum %.6f\n", float64(r.componentWatchFeedNanos.Load())/float64(time.Second))
	_, _ = fmt.Fprintf(response, "component_watch_feed_duration_seconds_count %d\n", r.componentWatchFeedCount.Load())
}

func formatSeconds(value time.Duration) string {
	return fmt.Sprintf("%g", value.Seconds())
}
