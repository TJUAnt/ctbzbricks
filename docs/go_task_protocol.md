# Go/Python Worker 持久化任务协议

> 状态：G5 implementation contract  
> 数据库 authority：Goose / `component_repo`  
> 实现：`backend-go/internal/task`、`backend-go/db/queries/tasks.sql`

## 1. 协议边界

PostgreSQL 的 `task_jobs`、`tasks`、`task_events` 和 `outbox_events` 是任务事实来源。Go 和
Python Worker 使用相同的状态、JSON、lease、执行复用和错误契约；进程内 channel、
goroutine、HTTP 请求 background callback、`LISTEN/NOTIFY` 或 Worker 内存都不是
权威队列。

任务系统使用三个通用层次：

| 层次 | 数据 | 语义 |
|---|---|---|
| Logical Job | `task_jobs` | 同一业务对象在同一确定性输入下的一次逻辑计算 |
| Execution | `tasks` | Job 的一次实际执行；失败、取消或显式缓存重建后新增一行 |
| Attempt | `tasks.attempts` | 一个 Execution 的 lease 领取/恢复次数 |

Job identity 是 `(owner_id, task_type, logical_key, input_hash)`。`logical_key` 表示业务对象，
`input_hash` 使用长度前缀后的 SHA-256，必须覆盖会改变结果的权威输入、算法版本及其受控配置版本。
Execution 使用 `task_job_id + execution_number` 唯一编号，并用 `retry_of_task_id` 形成执行链。

任务类型决定执行者：

| task type | 初始执行者 |
|---|---|
| `component.artifact.verify` | Go Worker |
| `component.validate` | Go Worker |
| `component.preview.materialize` | Go Worker |
| `component.part_preview.materialize` | Go Worker |
| `component.import.parse` | Python Worker |
| `component.relations.detect` | Python Worker |

Worker 只能 claim 自己注册的 task type。Python adapter 在 G6 接入解析器，但必须
直接遵循本协议，不得恢复公共 FastAPI Component Repo 路由。

## 2. 任务 JSON 契约

任务 payload/result 必须是 JSON object。ID、类型、状态、code、参数名、算法版本和
JSON key 都是机器字段，不翻译。任务创建时冻结规范化 locale 和 IANA timezone。

`component.artifact.verify`：

```json
{
  "taskType": "component.artifact.verify",
  "payload": {"artifactId": "uuid"},
  "result": {"artifactId": "uuid", "verificationStatus": "verified"}
}
```

`component.import.parse`：

```json
{
  "taskType": "component.import.parse",
  "payload": {
    "importId": "uuid",
    "parserVersion": "component-repo-ldraw-parser-v1",
    "snapshotSchema": "component-repo-v1"
  },
  "result": {
    "importId": "uuid",
    "candidateId": "uuid",
    "componentId": "uuid",
    "draftVersionId": "uuid",
    "sceneSnapshotId": "uuid"
  }
}
```

`component.relations.detect`：

```json
{
  "taskType": "component.relations.detect",
  "payload": {
    "candidateId": "uuid",
    "detectionVersion": "component-relation-detector-v1",
    "partLibraryVersionId": "uuid",
    "inputHash": "sha256"
  },
  "result": {
    "candidateId": "uuid",
    "relationCandidateCount": 2,
    "connectorCount": 4,
    "interfaceCount": 4,
    "detectionVersion": "component-relation-detector-v1"
  }
}
```

`component.validate`：

```json
{
  "taskType": "component.validate",
  "payload": {
    "candidateId": "uuid",
    "versionId": "uuid",
    "validationLevel": "publish",
    "validatorVersion": "component-repo-validator-v1",
    "inputHash": "sha256"
  },
  "result": {"validationReportId": "uuid", "passed": true}
}
```

`component.preview.materialize`：

```json
{
  "taskType": "component.preview.materialize",
  "payload": {
    "versionId": "uuid",
    "generatorVersion": "component-preview-structural-glb-v1",
    "generation": 0,
    "inputHash": "sha256"
  },
  "result": {
    "versionId": "uuid",
    "artifactId": "uuid",
    "generatorVersion": "component-preview-structural-glb-v1"
  }
}
```

`component.part_preview.materialize`：

```json
{
  "taskType": "component.part_preview.materialize",
  "payload": {
    "partLibraryVersionId": "uuid",
    "ldrawPartNum": "3001.dat",
    "generatorVersion": "part-preview-ldraw-glb-v1",
    "generation": 0,
    "inputHash": "sha256"
  },
  "result": {
    "partLibraryVersionId": "uuid",
    "ldrawPartNum": "3001.dat",
    "artifactId": "uuid",
    "generatorVersion": "part-preview-ldraw-glb-v1"
  }
}
```

关系 Worker 在一个事务中写入 relation candidates、connector analysis、external
interfaces、Candidate/Draft 签名以及任务终态。SceneSnapshot 不在其写集合中。关系确认
由 Go API 的 serializable transaction 与数据库 connector occupancy slot 共同保护。

验证报告通过 task ID、owner、Candidate、Draft Version 与三类签名/hash 绑定；只有对应
Task 已经 `succeeded` 且报告 `passed=true` 时才能发布。预览 Artifact ID 由 Version 与
generator version 稳定派生；Storage 缓存丢失后增加 materialization generation 并覆盖写回
同一 derived Artifact，GET 不负责创建任务或对象。

Part preview 的 Logical Job key 是 `partLibraryVersionId:ldrawPartNum`，input hash 覆盖
Part Library source hash、根 Part source file hash 和 generator version。Go Worker 只在配置
只读 `LDRAW_ROOT` 时注册该类型，递归展开冻结 Part Library 中的 LDraw type 1/3/4 几何；
Go API 不读取本地文件。Part preview GET 只读 `part_previews + Artifact`，物化必须显式 POST。

Parse Task 通过 `task_dependencies` 显式依赖本次上传的全部
`component.artifact.verify` Task。依赖未全部成功时不能 claim；任一依赖进入
`failed/cancelled`，下游 Task 在同一状态传播事务中进入对应终态，且不消耗 Parser
attempt。Import 的 parser version、snapshot schema、part-library version、locale/timezone
在创建时冻结，Worker 不从浏览器或运行期活动版本重新选择。

payload 禁止保存 Storage service-role key、签名 URL、对象正文、原始异常、SQL、路径
或堆栈。失败和进度只写稳定 `code + params`，最终译文由客户端资源层生成。

## 3. 状态机

```text
queued -> running -> succeeded
   |         |  \-> failed
   |         |  \-> queued       (retry)
   |         \----> cancelled    (cooperative cancellation)
   \--------------> cancelled
```

- 新任务只能以 `queued`、`attempts=0` 创建。
- `queued -> running` 必须原子增加一次 attempts 并写 lease。
- terminal 状态 `succeeded/failed/cancelled` 不可再修改。
- `running -> queued` 不增加 attempts；下一次 claim 才增加。
- 达到 `max_attempts` 后不可再次 claim。
- 每次状态变化与对应 task event/outbox event 在同一 PostgreSQL transaction 中提交。

数据库 trigger 和 check constraint 保护状态字段，不能只依赖 Worker 自律。

## 4. Claim、lease 与崩溃恢复

Worker 使用短事务和 `FOR UPDATE SKIP LOCKED`，按 `available_at, created_at, id`
稳定排序领取一条允许类型的任务。事务只完成 claim、task event 和 outbox 写入，计算
期间不持有行锁。

运行中 Worker 在 lease 尚未过期时续租。heartbeat 返回：

- 当前 Worker 是否仍拥有 lease；
- 是否已收到取消请求。

claim 返回的 `attempts` 是本次领取的 `claimed_attempt`。heartbeat、progress、complete、
retry、fail 和 claimed cancellation 必须同时匹配 `task_id + lease_owner + claimed_attempt`；
只匹配 worker ID 不构成 lease 所有权，因为进程重启或下一次重试可以复用同一个 worker ID。

lease 到期后：

- 已请求取消：转为 `cancelled`；
- attempts 仍有余额：转回 `queued`；
- attempts 已耗尽：转为 `failed`，只保存结构化机器错误。

旧 Worker 在丢失 lease 后不得提交进度、结果或业务终态。结果提交由带 attempt 栅栏的
原子 UPDATE 判定所有权；若任务已经是 `succeeded`，相同 task 的重复 complete 是无操作，
不得新增 succeeded event/outbox。不得用提交前 SELECT 代替原子栅栏。

## 5. Job 复用、Execution 重提、Attempt 重试与业务副作用

调度同一 Job 时必须在 PostgreSQL transaction 中锁定 Job 行，并按以下通用矩阵处理：

| 已有状态 | 调度结果 |
|---|---|
| latest 为 `queued/running` | 返回同一 Execution，不重复提交 |
| 存在 `successful_task_id` | 返回成功 Execution，不重复计算 |
| latest 为 `failed/cancelled` 且无可复用成功结果 | 创建递增编号的新 Execution |
| 成功结果存在但可重建对象缓存已丢失 | 显式 `force new`，创建同一 Job 的新 Execution |

`force new` 只用于服务已经验证派生缓存确实缺失的场景，不能由公共客户端任意指定。
并发调度由 Job 唯一约束、行锁和 Execution 编号约束串行化，不能用“先 SELECT 再 INSERT”判断。
Execution 内的 retry/lease recovery 只增加 Attempt；它不创建新 task ID，也不改变 Job input identity。

Worker handler 必须让业务副作用幂等。例如 Artifact 校验成功先持久化
`verification_status=verified`；若 Worker 随后崩溃，重领任务读取该终态并直接返回，
不会再次流式下载对象正文。后续派生 Artifact 和 ComponentVersion 使用各自稳定业务
key/唯一约束，不依靠“任务通常只执行一次”。

Python Parser Worker 使用由 Import ID 派生的稳定 Snapshot/Candidate/Draft/derived
Artifact ID，并在一个 PostgreSQL transaction 中写入 SceneSnapshot、BOM、parse issues、
Candidate、Draft ComponentVersion、Task succeeded、task event 与 outbox。事务提交前崩溃
不会留下半个业务结果；已存在的权威 Snapshot 永不 UPDATE，重领只复用完整结果。

关系检测以 Candidate 为 logical key，并把结构/几何 hash、Snapshot schema/parser、冻结
Part Library source hash 和 detector version 纳入 input hash。发布校验以 Version 为 logical key，
把 interface/structure/geometry、Part Library source hash 和 validator version 纳入 input hash。
预览以 Version 为 logical key，把 immutable SceneSnapshot ID 和 generator version 纳入 input hash。
Worker 在提交业务结果前必须重新计算/验证 payload 的 input hash，拒绝过期或拼接输入。

## 6. 取消

queued 任务可以立即取消。running 任务只记录 `cancel_requested_at/by`，heartbeat
通知 Worker 取消 handler context；Worker 完成 cooperative cleanup 后提交
`cancelled`。取消与 handler 完成竞争时，完成 SQL 要求 cancel request 为空，因此不会
把已请求取消的任务提交为 succeeded。

## 7. Outbox

task event 同事务写入 topic `component.task.events`。事件 payload 必须同时包含
`taskJobId`、`executionNumber` 和 `attempt`。Outbox publisher 使用独立 lease、
attempts、max attempts 和退避时间；发布成功后写 `published_at`。未来接入外部事件消费
者时只能消费 outbox，不得从 API mutation 后直接发送非事务消息。

`LISTEN/NOTIFY` 可以作为降低轮询延迟的优化，但不得改变上述持久化协议。
