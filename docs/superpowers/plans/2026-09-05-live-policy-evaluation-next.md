# 下一阶段计划：真实失败回流与 LLM 对照评测

日期：2026-09-05
基线：本地 main 已合入 9fe11ba（A+C）。
状态：下一阶段方案；本次不实现新功能，不执行付费模型请求。

## 目标与顺序

先证明候选策略能改变实际 agent 行为，再增加 B 的执行中重规划。
第一阶段采用「live LLM + 固定工具观察」，随后才接 live 数据 adapter。
保留现有离线检查作为第一道门槛，不把文本关键词命中解释成研究质量提升。

## API key：明确需要，但复用已有配置

- 导入历史 session、生成候选案例、离线测试：不需要 key。
- 现有 --improve 的 LLM 反思：已经需要 DEEPSEEK_API_KEY；不是下一阶段才首次引入。
- 新增的新旧策略真实 LLM 对照执行：需要同一 DEEPSEEK_API_KEY。
- 复用 config.make_client、SUB_AGENT_MODEL、COORDINATOR_MODEL 和已有 endpoint 配置，不新增 provider 框架。
- 模型标识由运行者指定并写入评测元数据；实施前用一次显式 smoke 确认账号可用模型，不硬编码假定可用的模型。
- key 仅通过本地环境变量或 git 忽略的 .env 注入，不进入 fixture、prompt、日志、报告或 Git。
- 常规 pytest 和 --eval 保持无 key、无模型请求。新增 live 命令显式启用；缺 key 时在发送请求前清晰退出。
- 首轮固定工具数据，不需要 Serper/Tavily 等搜索 key。未来 live 数据阶段再独立配置。
- 本次只制定计划，不读取或展示任何 key，不产生付费 API 调用。

## 切片 1：真实 session 失败导入（无 LLM）

输入现有 verification.json、traces.jsonl、task_board.json、sub_reports/*.json 和 policy_snapshot.json。
输出 reports/eval_cases/ 下待校验案例，包含：
case_id、来源 session/trace、研究角色、能力、失败证据、工具参数与观察、来源哈希、策略版本。

复用 ToolTrace 和既有证据 schema；不另建全量轨迹日志。
按稳定来源 ID 去重，但新一次失败保存 occurrence，避免已关闭 evidence ID 永久吞掉回归。
分别处理研究缺口账本和回归案例生命周期；研究任务闭合不等于回归测试永久删除。

验收：
- 同一 session 重复导入不产生重复案例。
- 缺失/截断/哈希不匹配的观察不能伪装成可回放案例。
- 新失败可重新打开已关闭问题，同时保留历史。
- 案例导入不调用 LLM，不自动发明 ground truth。

落点：新增 eval/session_cases.py；针对性扩展 coordinator/gap_seed.py；独立测试。

## 切片 2：固定工具观察上的真实 agent 执行（需要 LLM key）

复用 agents/react_loop.py，注入只读 replay tool registry。
按「工具名称 + 规范化参数」匹配观察，不简单把录制的第 N 条结果分配给第 N 个请求。
未录制的调用返回明确不可用或将案例标为不可评测；绝不静默回退到 live 工具。
当前只有 engine_query/web_search 有完整 ToolTrace，初版只支持回放数据完整的案例；
不伪造 market_data/file_reader 结果，也不宣称支持任意历史 session。

baseline 与 candidate 使用相同案例、模型、预算和工具观察；唯一主动变化是策略。
固定策略快照，保存实际工具调用和最终 Evidence[]。
独立输出到 reports/live_evals/<run_id>/，不污染生产 gap ledger 或 active 指针。

验收：
- 模型确实重新决策，工具结果来自固定观察。
- 任何未知调用都不会联网。
- 对照结果绑定明确的 baseline/candidate 版本及数据哈希。
- 单元测试使用 fake client；显式 live smoke 才调用服务。

落点：新增 eval/replay_runner.py；复用现有 LoopBudget 和 UsageSummary。

## 切片 3：可检验的行为评分与小规模实验

先选择 3–5 个可回放、有明确断言的真实失败案例，另留独立回归 guard 案例。
断言来自验证过的案例期望，不由候选生成器同时修改题目与答案。
评分检查实际行为与交付：工具及参数是否符合场景、日期是否正确、
证据来源是否真实存在于观察、未被支持的断言是否被拒绝/保留为未知。
关键词检查继续只是结构门槛。

初版每个策略每个案例运行 2 次；记录每次结果，不把小样本当统计证明。
报告任务通过率、逐案例差异、违规/无法评分原因、token 与延迟。
数据不足、超时、缺失结果均不能算通过；记录 observed no-regression，而不声称绝对无回归。

费用界限：
显式指定 --max-cases、--repeats、--max-llm-calls 和每次输出 token 上限。
预先展示最坏调用数，调用前检查剩余预算；以调用数/token 作为硬界限，
费用估算仅在配置了适用价格时展示，不猜测美元金额。

落点：扩展 eval/policy_suite.py 的行为结果适配；新增 eval/live_compare.py 和 CLI 入口。

## 切片 4：先影子评测，再接自动晋升

首轮 live compare 仅保存对照报告，不改变 active 策略。
证明回放、评分和成本控制可信后，再将其接入晋升：
现有离线门槛通过 AND 同案例 live 对照修复至少一个目标 AND guard 不退步。
复用 PolicyStore、实验记录、晋升锁和原子指针，不新增服务或数据库。
live 评测无法完成时保持当前策略；运行中的研究仍使用原快照。

验收：
- 正例/负例都能在相同观察上复现。
- 未通过或未完成 live 门槛的候选不能晋升。
- 实验可从版本、案例、模型、预算及实际输出追溯。
- 一次 live 实验不触发递归改进或无限重试。

## 切片 5：B — 有界执行中重规划（后续）

在上述行为评测可用后，增加阶段性结果回传，由 Coordinator 修改待执行任务，
必要时取消已过时分支；保留现有任务/工具预算和一次重规划上限。
用已建回放案例比较「静态计划 vs 动态计划」的效果和成本。
沿用 TaskBoard 与 asyncio；不引入 AgentBus、数据库或额外 agent 框架。

## 完成标准

下一阶段首先交付可独立运行的切片 1–3：
真实失败可进入案例库，真实 LLM 在固定工具观察上执行新旧策略，
产生有行为依据和成本记录的对照报告。
是否接通自动晋升取决于该报告，而不是离线关键词通过率。
B 与 live 数据接入继续作为后续增量，避免同时改变策略、协调和数据来源。

