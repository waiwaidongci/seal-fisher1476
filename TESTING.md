# 验证记录（研究系列 · 共享显著性额度）

日期：2026-11-17。环境：Python 3.11，SQLite（单测，StaticPool 内存库）+ MySQL 方言编译检查；无 docker，未跑 compose 全栈。

## 自动化测试：`backend/tests/`（17 项全部通过）

运行方式：`cd backend && python3 -m pytest tests/ -q`（依赖见 `backend/requirements.txt`，另需 pytest、httpx）。

### 抢占剩余额度
- `test_reserve_up_to_remaining_then_reject`：总额0.05，研究1预占0.02并完成（已用0.02），研究2缺省预占全部剩余0.03，研究3再预占0.001被409拒绝；不变量 已用+预占≤总额 始终成立。
- `test_default_alpha_capped_at_max`：缺省预占超过单次上限0.2时按0.2预占。
- `test_budget_never_exceeds_total`：连续预占至满额后任何正额预占均409。
- `test_alpha_and_budget_bounds`：α 越界、总额越界均422。

### 总额锁定
- `test_budget_locked_after_first_study`：首项研究前可调整总额；首项研究发起后 `locked=True`，再调整409；台账含 lock/reserve 记录。

### 公开与取消竞态
- `test_published_budget_never_refunded`：completed 研究取消409、重试409，已用额度不变（已公开永不退回）。
- `test_cancel_releases_unpublished`：queued 研究取消后额度释放、剩余恢复，台账记录取消原因，可再发起等额研究。
- `test_late_result_cannot_revive_cancelled`：先取消再模拟 worker 迟归 `complete_study`，返回 False，研究保持 cancelled、result 为空、无 use 台账——迟归结果不复活已退款研究。
- `test_worker_skips_cancelled_and_failure_releases`：worker 取出已取消研究的消息直接跳过；计算失败的研究释放预占额度。

### 中断重试
- `test_failure_releases_and_retry_no_double_charge`：失败释放→重试沿用原研究 id 与原阈值重新预占（不重复扣，预占仍为0.02而非0.04）→完成后已用0.02；台账动作序列为 create/lock/reserve/release/reserve/use。
- `test_retry_rejected_when_budget_consumed`：释放出的额度被后续研究占满后，重试409。
- `test_recovery_keeps_reservation`：queued/running 研究进入恢复列表，恢复期间预占保持（不漏扣）；已取消研究不恢复。
- `test_full_queue_cycle_and_recovery`：独立研究与系列研究经真实入队消息格式（`{run_id}` 与 `series:{id}`）由 `worker.dispatch` 消费完成；模拟中断后按 `recover()` 重新入队并完成，额度一致。

### 原独立研究保持原行为
- `test_independent_runs_keep_original_behavior`：`runs.create` 消息格式、状态流、结果阈值不变；独立运行完成不触碰任何系列额度，系列列表无独立研究台账。

### API 层
- `test_series_api_flow`：建系列→改总额→发起研究（锁定后改总额409）→取消→重试，GET /series 返回余额与台账。
- `test_series_api_requires_auth_and_writer`：未登录401，观察员写操作403、读操作200。

## MySQL 方言检查
- `SELECT ... FOR UPDATE` 行锁语句与三张新表 DDL（series / series_studies / series_ledger，NUMERIC(12,9)、JSON、外键）均通过 MySQL 方言编译。并发预占/取消/完成的互斥依赖 InnoDB 行锁，所有额度变动路径按“系列行→研究行”固定顺序加锁，避免死锁；SQLite 单测以串行调用模拟两种竞态顺序。

## 前端
- `node --check` 通过：pages/series.js、main.js、api/research.js、stores/research.js、router/index.js。
- 页面：建立系列、调整总额（未锁定）、发起研究（阈值留空抢占剩余）、取消、重试、额度条（已用/预占/剩余）、额度台账（事件、变动、已用、预占、原因）；queued/running 研究每2秒自动刷新。

## 未覆盖
- 未在真实 MySQL+Redis 的 compose 环境做并发压测（本机无 docker）；并发正确性由行锁设计与上述竞态顺序测试保证。
