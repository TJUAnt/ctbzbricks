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
	// ComponentNotificationFanoutCompleted 与 DeadLettered 只记录一个 delivery 的最终状态。
	ComponentNotificationFanoutCompleted    = "completed"
	ComponentNotificationFanoutDeadLettered = "dead_lettered"
	// ComponentNotificationAttempt* 是单个持久批次尝试允许的固定结果，不把错误正文写入标签。
	ComponentNotificationAttemptCommitted      = "committed"
	ComponentNotificationAttemptRetryScheduled = "retry_scheduled"
	ComponentNotificationAttemptDeadLettered   = "dead_lettered"
	// ComponentNotificationRecipient* 统计批次内 recipient 的幂等处理结果。
	ComponentNotificationRecipientCreated           = "created"
	ComponentNotificationRecipientDeduplicated      = "deduplicated"
	ComponentNotificationRecipientSkippedIneligible = "skipped_ineligible"
	// ComponentNotificationDeadLetter* 将失败原因收敛为三个稳定运维类别。
	ComponentNotificationDeadLetterRetryExhausted     = "retry_exhausted"
	ComponentNotificationDeadLetterPermanentData      = "permanent_data"
	ComponentNotificationDeadLetterInvariantViolation = "invariant_violation"
)

var componentNotificationLagBuckets = [...]time.Duration{
	time.Second, 5 * time.Second, 15 * time.Second, 30 * time.Second,
	time.Minute, 5 * time.Minute, 15 * time.Minute,
}

var componentNotificationBatchBuckets = [...]uint64{1, 10, 50, 100, 250}

// Registry 保存单个 API 或 Worker 进程的低基数运维指标，并以 Prometheus 文本格式提供采集。
// 指标不是业务事实账本；跨实例聚合与进程重启后的连续性由监控系统负责。
type Registry struct {
	componentDomainEventCommitted atomic.Uint64
	componentDomainEventFailed    atomic.Uint64
	componentWatchSucceeded       atomic.Uint64
	componentWatchFailed          atomic.Uint64
	componentUnwatchSucceeded     atomic.Uint64
	componentUnwatchFailed        atomic.Uint64
	componentFanoutCompleted      atomic.Uint64
	componentFanoutDeadLettered   atomic.Uint64
	componentFanoutAttempts       [3]atomic.Uint64
	componentFanoutRecipients     [3]atomic.Uint64
	componentFanoutDeadLetters    [3]atomic.Uint64
	componentFanoutLagBuckets     [len(componentNotificationLagBuckets)]atomic.Uint64
	componentFanoutLagCount       atomic.Uint64
	componentFanoutLagNanoseconds atomic.Uint64
	componentFanoutBatchBuckets   [len(componentNotificationBatchBuckets)]atomic.Uint64
	componentFanoutBatchCount     atomic.Uint64
	componentFanoutBatchSum       atomic.Uint64
	componentFanoutBacklogEvents  atomic.Uint64
	componentFanoutOldestNanos    atomic.Uint64
	componentFanoutUnresolvedDead atomic.Uint64
	componentFanoutOldestDeadNano atomic.Uint64
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

// RecordComponentNotificationFanout 记录一个 PostgreSQL delivery 的最终结果及从领域事件到最终状态的延迟。
// 仅接受 WATCH-3 冻结的事件和结果；进程指标不替代数据库中的权威 delivery 状态。
func (r *Registry) RecordComponentNotificationFanout(eventType, result string, lag time.Duration) {
	if r == nil || eventType != ComponentVersionPublishedEvent {
		return
	}
	switch result {
	case ComponentNotificationFanoutCompleted:
		r.componentFanoutCompleted.Add(1)
	case ComponentNotificationFanoutDeadLettered:
		r.componentFanoutDeadLettered.Add(1)
	default:
		return
	}
	if lag < 0 {
		return
	}
	r.componentFanoutLagCount.Add(1)
	r.componentFanoutLagNanoseconds.Add(uint64(lag))
	for index, upperBound := range componentNotificationLagBuckets {
		if lag <= upperBound {
			r.componentFanoutLagBuckets[index].Add(1)
		}
	}
}

// RecordComponentNotificationFanoutAttempt 记录一个批次事务的最终尝试结果。
func (r *Registry) RecordComponentNotificationFanoutAttempt(result string) {
	if r == nil {
		return
	}
	index := -1
	switch result {
	case ComponentNotificationAttemptCommitted:
		index = 0
	case ComponentNotificationAttemptRetryScheduled:
		index = 1
	case ComponentNotificationAttemptDeadLettered:
		index = 2
	}
	if index >= 0 {
		r.componentFanoutAttempts[index].Add(1)
	}
}

// AddComponentNotificationRecipients 按固定结果累计批次 recipient 数量，禁止 actor 或事件 ID 成为标签。
func (r *Registry) AddComponentNotificationRecipients(result string, count uint64) {
	if r == nil {
		return
	}
	index := -1
	switch result {
	case ComponentNotificationRecipientCreated:
		index = 0
	case ComponentNotificationRecipientDeduplicated:
		index = 1
	case ComponentNotificationRecipientSkippedIneligible:
		index = 2
	}
	if index >= 0 {
		r.componentFanoutRecipients[index].Add(count)
	}
}

// RecordComponentNotificationDeadLetter 将 delivery 最终失败归入稳定类别，详细 code 只留在数据库和日志字段。
func (r *Registry) RecordComponentNotificationDeadLetter(errorClass string) {
	if r == nil {
		return
	}
	index := -1
	switch errorClass {
	case ComponentNotificationDeadLetterRetryExhausted:
		index = 0
	case ComponentNotificationDeadLetterPermanentData:
		index = 1
	case ComponentNotificationDeadLetterInvariantViolation:
		index = 2
	}
	if index >= 0 {
		r.componentFanoutDeadLetters[index].Add(1)
	}
}

// ObserveComponentNotificationBatch 记录一个已尝试事务中的 recipient 数，250 是当前冻结的批次上限。
func (r *Registry) ObserveComponentNotificationBatch(size uint64) {
	if r == nil || size == 0 || size > 250 {
		return
	}
	r.componentFanoutBatchCount.Add(1)
	r.componentFanoutBatchSum.Add(size)
	for index, upperBound := range componentNotificationBatchBuckets {
		if size <= upperBound {
			r.componentFanoutBatchBuckets[index].Add(1)
		}
	}
}

// SetComponentNotificationBacklog 设置从 PostgreSQL 权威状态采样的 pending 数和最老事件年龄。
// Worker 尚未实现时保持零值；WATCH-3 必须由数据库采样覆盖，不能从进程队列推断。
func (r *Registry) SetComponentNotificationBacklog(events uint64, oldestAge time.Duration) {
	if r == nil {
		return
	}
	if oldestAge < 0 {
		oldestAge = 0
	}
	r.componentFanoutBacklogEvents.Store(events)
	r.componentFanoutOldestNanos.Store(uint64(oldestAge))
}

// SetComponentNotificationDeadLetterBacklog 从 PostgreSQL 采样未确认 dead letter 数及最老年龄，支撑 24 小时确认门禁。
func (r *Registry) SetComponentNotificationDeadLetterBacklog(unresolved uint64, oldestAge time.Duration) {
	if r == nil {
		return
	}
	if oldestAge < 0 {
		oldestAge = 0
	}
	r.componentFanoutUnresolvedDead.Store(unresolved)
	r.componentFanoutOldestDeadNano.Store(uint64(oldestAge))
}

// ServeHTTP 输出固定、无用户数据的 Prometheus 0.0.4 文本；该端点应由部署入口限制为监控网络访问。
func (r *Registry) ServeHTTP(response http.ResponseWriter, _ *http.Request) {
	committed, failed := r.ComponentDomainEventCounts()
	response.Header().Set("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
	response.WriteHeader(http.StatusOK)
	_, _ = fmt.Fprintf(response, "# HELP component_domain_event_total Component domain event transaction outcomes.\n")
	_, _ = fmt.Fprintf(response, "# TYPE component_domain_event_total counter\n")
	_, _ = fmt.Fprintf(response, "component_domain_event_total{event_type=%q,result=%q} %d\n", ComponentVersionPublishedEvent, DomainEventCommitted, committed)
	_, _ = fmt.Fprintf(response, "component_domain_event_total{event_type=%q,result=%q} %d\n", ComponentVersionPublishedEvent, DomainEventFailed, failed)
	watchSucceeded, watchFailed, unwatchSucceeded, unwatchFailed := r.ComponentWatchMutationCounts()
	_, _ = fmt.Fprintf(response, "# HELP component_watch_mutation_total Component Watch mutation outcomes.\n")
	_, _ = fmt.Fprintf(response, "# TYPE component_watch_mutation_total counter\n")
	_, _ = fmt.Fprintf(response, "component_watch_mutation_total{action=%q,result=%q} %d\n", ComponentWatchActionWatch, ComponentWatchMutationSucceeded, watchSucceeded)
	_, _ = fmt.Fprintf(response, "component_watch_mutation_total{action=%q,result=%q} %d\n", ComponentWatchActionWatch, ComponentWatchMutationFailed, watchFailed)
	_, _ = fmt.Fprintf(response, "component_watch_mutation_total{action=%q,result=%q} %d\n", ComponentWatchActionUnwatch, ComponentWatchMutationSucceeded, unwatchSucceeded)
	_, _ = fmt.Fprintf(response, "component_watch_mutation_total{action=%q,result=%q} %d\n", ComponentWatchActionUnwatch, ComponentWatchMutationFailed, unwatchFailed)
	r.writeComponentNotificationMetrics(response)
}

// writeComponentNotificationMetrics 输出 WATCH-3 预先冻结的低基数指标；所有 Gauge 后续必须来自 PostgreSQL 状态。
func (r *Registry) writeComponentNotificationMetrics(response http.ResponseWriter) {
	_, _ = fmt.Fprintln(response, "# HELP component_notification_fanout_total Final Component notification fan-out delivery outcomes.")
	_, _ = fmt.Fprintln(response, "# TYPE component_notification_fanout_total counter")
	_, _ = fmt.Fprintf(response, "component_notification_fanout_total{event_type=%q,result=%q} %d\n", ComponentVersionPublishedEvent, ComponentNotificationFanoutCompleted, r.componentFanoutCompleted.Load())
	_, _ = fmt.Fprintf(response, "component_notification_fanout_total{event_type=%q,result=%q} %d\n", ComponentVersionPublishedEvent, ComponentNotificationFanoutDeadLettered, r.componentFanoutDeadLettered.Load())

	_, _ = fmt.Fprintln(response, "# HELP component_notification_delivery_attempts_total Durable fan-out batch attempt outcomes.")
	_, _ = fmt.Fprintln(response, "# TYPE component_notification_delivery_attempts_total counter")
	for index, result := range []string{ComponentNotificationAttemptCommitted, ComponentNotificationAttemptRetryScheduled, ComponentNotificationAttemptDeadLettered} {
		_, _ = fmt.Fprintf(response, "component_notification_delivery_attempts_total{result=%q} %d\n", result, r.componentFanoutAttempts[index].Load())
	}

	_, _ = fmt.Fprintln(response, "# HELP component_notification_recipient_total Idempotent recipient materialization outcomes.")
	_, _ = fmt.Fprintln(response, "# TYPE component_notification_recipient_total counter")
	for index, result := range []string{ComponentNotificationRecipientCreated, ComponentNotificationRecipientDeduplicated, ComponentNotificationRecipientSkippedIneligible} {
		_, _ = fmt.Fprintf(response, "component_notification_recipient_total{result=%q} %d\n", result, r.componentFanoutRecipients[index].Load())
	}

	_, _ = fmt.Fprintln(response, "# HELP component_notification_dead_letter_total Final fan-out failures by bounded error class.")
	_, _ = fmt.Fprintln(response, "# TYPE component_notification_dead_letter_total counter")
	for index, errorClass := range []string{ComponentNotificationDeadLetterRetryExhausted, ComponentNotificationDeadLetterPermanentData, ComponentNotificationDeadLetterInvariantViolation} {
		_, _ = fmt.Fprintf(response, "component_notification_dead_letter_total{error_class=%q} %d\n", errorClass, r.componentFanoutDeadLetters[index].Load())
	}

	_, _ = fmt.Fprintln(response, "# HELP component_notification_fanout_lag_seconds Seconds from domain event occurrence to final fan-out state.")
	_, _ = fmt.Fprintln(response, "# TYPE component_notification_fanout_lag_seconds histogram")
	for index, upperBound := range componentNotificationLagBuckets {
		_, _ = fmt.Fprintf(response, "component_notification_fanout_lag_seconds_bucket{le=%q} %d\n", formatDurationSeconds(upperBound), r.componentFanoutLagBuckets[index].Load())
	}
	_, _ = fmt.Fprintf(response, "component_notification_fanout_lag_seconds_bucket{le=%q} %d\n", "+Inf", r.componentFanoutLagCount.Load())
	_, _ = fmt.Fprintf(response, "component_notification_fanout_lag_seconds_sum %.6f\n", float64(r.componentFanoutLagNanoseconds.Load())/float64(time.Second))
	_, _ = fmt.Fprintf(response, "component_notification_fanout_lag_seconds_count %d\n", r.componentFanoutLagCount.Load())

	_, _ = fmt.Fprintln(response, "# HELP component_notification_batch_size Recipients attempted per durable transaction.")
	_, _ = fmt.Fprintln(response, "# TYPE component_notification_batch_size histogram")
	for index, upperBound := range componentNotificationBatchBuckets {
		_, _ = fmt.Fprintf(response, "component_notification_batch_size_bucket{le=%q} %d\n", fmt.Sprint(upperBound), r.componentFanoutBatchBuckets[index].Load())
	}
	_, _ = fmt.Fprintf(response, "component_notification_batch_size_bucket{le=%q} %d\n", "+Inf", r.componentFanoutBatchCount.Load())
	_, _ = fmt.Fprintf(response, "component_notification_batch_size_sum %d\n", r.componentFanoutBatchSum.Load())
	_, _ = fmt.Fprintf(response, "component_notification_batch_size_count %d\n", r.componentFanoutBatchCount.Load())

	_, _ = fmt.Fprintln(response, "# HELP component_notification_backlog_events Pending or retryable PostgreSQL fan-out deliveries.")
	_, _ = fmt.Fprintln(response, "# TYPE component_notification_backlog_events gauge")
	_, _ = fmt.Fprintf(response, "component_notification_backlog_events %d\n", r.componentFanoutBacklogEvents.Load())
	_, _ = fmt.Fprintln(response, "# HELP component_notification_oldest_pending_seconds Age of the oldest pending or retryable PostgreSQL delivery.")
	_, _ = fmt.Fprintln(response, "# TYPE component_notification_oldest_pending_seconds gauge")
	_, _ = fmt.Fprintf(response, "component_notification_oldest_pending_seconds %.6f\n", float64(r.componentFanoutOldestNanos.Load())/float64(time.Second))
	_, _ = fmt.Fprintln(response, "# HELP component_notification_unresolved_dead_letters Unacknowledged PostgreSQL fan-out dead letters.")
	_, _ = fmt.Fprintln(response, "# TYPE component_notification_unresolved_dead_letters gauge")
	_, _ = fmt.Fprintf(response, "component_notification_unresolved_dead_letters %d\n", r.componentFanoutUnresolvedDead.Load())
	_, _ = fmt.Fprintln(response, "# HELP component_notification_oldest_dead_letter_seconds Age of the oldest unacknowledged fan-out dead letter.")
	_, _ = fmt.Fprintln(response, "# TYPE component_notification_oldest_dead_letter_seconds gauge")
	_, _ = fmt.Fprintf(response, "component_notification_oldest_dead_letter_seconds %.6f\n", float64(r.componentFanoutOldestDeadNano.Load())/float64(time.Second))
}

func formatDurationSeconds(value time.Duration) string {
	return fmt.Sprintf("%g", value.Seconds())
}
