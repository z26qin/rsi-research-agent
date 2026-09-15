# Useful Momentum Research Prototype Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. 本计划默认顺序执行；先完成第一阶段，再决定后续实现范围。

**Goal:** 让助手自主寻找可读资料、提取带日期的证据，并给出能节省用户研究时间的 momentum research 答案；随后从真实失败中改进。

**Architecture:** 复用现有 CLI → Single/Team → 授权搜索/正文读取 → ResearchReport → 独立 Verifier → 答案流程。第一阶段用 MTUM 持仓问题检验这条链路，按实际故障修复；真实研究反馈复用现有 gap ledger、policy 和 shadow comparison，不新增评估框架。

**Tech Stack:** Python 3.12+、uv、Pydantic、AsyncOpenAI/DeepSeek、现有公共 HTTPS reader、pytest。

**Spec:** [项目优先级](../../../TODO.md)；用户已确认的顺序是“真实问题 → 有价值的动量研究 → 从失败中改进”，以回答覆盖、来源可靠性/时效和节省研究时间验收。

## Global Constraints

- 本次只产出计划，不运行付费模型、不修改生产代码、不自动提交或推送。
- 执行阶段开始时检查工作区；代码修改使用 `codex/` 分支，保留已有用户改动。
- 维护的 pytest suite 最多 30 collected cases；新增必要回归须替换低优先级用例，不以 skip、隐藏目录或参数包装规避上限。
- 不新增工具授权、agent framework、web UI、数据库或自动调度。
- 保持每角色现有搜索/读取次数、LoopBudget、取消传播和独立 verifier 约束。不得以增加重试/预算掩盖问题。
- Committed analyst/verifier profiles 保持冻结；研究行为变化优先放在现有 source-reading contract。
- 搜索元数据不等于正文；抓取日期不等于数据日期；缺失值不等于零。
- 不修改确定性引擎、arena fixtures、评分或 promotion gate 来获得好看的结果。
- Native search 发现的来源继续遵守 AGENTS.md 的 UNCHECKED 约束；不把下载成功自动升级为 VERIFIED。核验绑定能力若确需扩展，另列明确设计，不混入读取修复。
- API key 只由现有配置读取；诊断只保存允许公开的错误类别、来源及时间，不记录密钥、请求认证信息或任意异常正文。

## 已知事实与待验证假设

已知：`reports/20260910_003250_eb4b7abf/` 中的 MTUM 持仓研究找到过候选链接，但未获得可用持仓正文，最终没有回答问题。`read_url.py` 当前把 HTTP、格式、超时等失败合并成通用 reason。

不能据此认定：所有官方来源现在都不可读，或者换 URL、放宽限制就一定能解决。该记录早于近期若干研究流程修改，必须先用当前版本确认问题是否仍然存在。

## 阶段与交付边界

| 阶段 | 用户得到什么 | 进入下一阶段的条件 |
| --- | --- | --- |
| M1：单个问题有用 | MTUM 前十大持仓、权重、真实日期、来源及核验状态 | 当前真实来源能支持主要请求字段；明确记录未完成部分；不只是抓取失败报告 |
| M2：动量研究有用 | 表现、集中度、拥挤/反转问题的简洁研究报告 | 每题有可追溯数据、明确解释及反证/未知，能重复使用 |
| M3：改进有用 | 一次从真实失败出发、对照证明有效的研究方法改进 | 修复目标失败且通过真实通过案例的回归检查，不要求先做 arena 自动晋升演示 |

本计划详细实施 M1；M2/M3 是后续验收路线，不在 M1 期间同时开发。

## M1 验收样例

输入：

> What are MTUM's top 10 holdings? Read source content and include weights, the actual observation date, and source links. Distinguish missing evidence from confirmed facts.

期望输出：

1. 开头直接说明持仓数据截至哪一天，来自何种来源。
2. 表格含名称/可得 ticker、权重（%）、实际观察日期、来源和核验状态。完整答案包含十项，排序以同一份数据的权重为准；不拼接不同日期来凑十项。
3. 说明来源口径，如全基金权重还是股票部分，避免擅自归一化。
4. 缺少任何字段时明确标记；第三方来源、日期未知、过时数据均需说明，不能冒充最新官方数据。
5. 正文中的数字能追溯到保存的 source content、Evidence 和 metrics；拒绝/未核验状态保持真实。
6. 附简短限制，不用工具执行日志替代答案。

分别记录：内容覆盖（几项/哪些字段）、独立核验结果、数据日期、重复失败调用、耗时、请求和 token 用量。内容完整与已核验是两个独立状态。

## 文件责任

| 文件 | 本阶段用途 |
| --- | --- |
| `tools/public_web.py` | 已有 HTTPS 获取/解析边界；定位传输、HTTP、类型、大小或截断问题 |
| `tools/read_url.py` | 有界读取、结构化失败和证据归档；保持原成功返回格式 |
| `research_contract.py` | 已配置来源入口、grounding 和答案覆盖；仅在复现证明需要时修改 |
| `agents/source_reading.md` | 官方入口、真实发现的候选来源、失败后停止重复尝试的研究方法 |
| `agents/sub_agent.py` | 已有报告说明和结构化提取；仅在事实已读却未进入报告时修改 |
| `cli.py` / `state/reports.py` | 复用运行入口及落盘；仅在展示丢失已有证据时修改 |
| `tests/test_read_url.py` | 若读取器需修复，保留一个真实边界回归，替换一个 arena 专用用例 |
| `tests/test_research_contract.py` | 若来源选择需修复，保留一个预算内转向可读来源的流程回归 |
| `tests/test_research_completion.py` | 若报告需修复，保留一个来源→十项带日期指标→答案的流程回归 |
| `docs/structured-research.md` | 更新实际支持的行为、限制和演示命令 |

上表中的前三个新测试文件仅在对应故障需要代码修改时创建。替换候选依次为 `test_withholding_contract.py` 的 arena 缺失概念测试、`test_arena_schema_repair.py` 的 arena 修复测试、`test_research_world.py` 的 manifest 测试；在替换记录中说明覆盖取舍。保留授权、独立核验、预算和本轮两个 bug 的回归。

### Task 1：确认当前瓶颈，保留真实基线

**Files:** 只读旧 session、当前 reader/contract；运行产物放 `reports/usefulness/<unique-id>/`，不覆盖旧 session。

**Interfaces:** 消费现有 `read_url(url: str) -> str`、`run_single`/CLI 和 session JSON；产出人工可审计的 `review.md`，不新增生产 schema。

- [ ] 阅读旧 `task_board.json`、`traces.jsonl`、报告和 verification，区分当时的 URL、角色和错误；不把旧结果当作当前网络结论。
- [ ] 在执行阶段用当前版本运行一次下面的基线命令。目录用唯一标识，保存提交版本、模型、policy、预算和实际命令：

```bash
uv run momentum-research-agent --mode single \
  --session-dir reports/usefulness/<unique-id>/baseline \
  "What are MTUM's top 10 holdings? Read source content and include weights, the actual observation date, and source links. State any missing evidence."
```

`<unique-id>` 在执行时由现有 `new_session_id()` 生成，不复用目录。

- [ ] 如读取失败，最多做三次无模型的公共 reader 定位请求：当前配置的官方入口、正文/搜索实际发现的下载入口、一个实际发现的替代来源。保持原 HTTPS/时间/大小限制，不使用登录、浏览器伪装或任意 provider fallback。
- [ ] 在 `review.md` 记录第一个断点：发现不到来源 / URL 无效或不可达 / 内容类型不支持 / 正文截断丢失目标字段 / 提取失败 / grounding 或核验缺口 / 展示遗漏。无法确定时保留原始可公开诊断，不先改代码。
- [ ] 若当前基线已完整回答，跳过不必要修复，直接进入 Task 4。若根因是不可访问的数据且允许来源均不可读，记录数据接入阻塞，不无限尝试。

**交付:** 一份基于当前运行的基线与故障定位，明确哪些改动必要。

### Task 2：修复已经确认的资料获取瓶颈

**Files:** `tools/public_web.py`、`tools/read_url.py`，必要时 `research_contract.py`、`agents/source_reading.md`；对应 reader/contract 测试。

**Interfaces:** 保持 `read_url` 的 JSON 返回及成功 artifact/hash 字段；失败时可增加稳定的 `failure_kind`，例如 `http_error`、`timeout`、`unsupported_content`、`too_large`、`network_error`、`budget_exhausted`。不向模型传递任意异常文本。

- [ ] 用 Task 1 实际错误编写一个失败回归。若问题为诊断丢失，期望明确错误类别且不含敏感异常内容；若问题为格式处理，使用合法公开响应片段重现解析失败。
- [ ] 运行对应单个测试，确认失败于目标行为，而不是 fixture 缺失。
- [ ] 只修复已证实的分支：有效公开 CSV/HTML 的解析错误修解析；错误官方入口修已核实入口；真实 HTTP 拒绝保留失败，不能绕过它或伪装为成功。
- [ ] 若现有研究仍重复读取同一失败入口，在现有 source-reading contract 中说明：官方来源优先；失败后只使用已发现且相关的候选来源；预算耗尽即总结。不得硬编码 MTUM 持仓答案。
- [ ] 以记录的工具响应跑流程回归：官方入口失败、候选来源可读时，最终找到正文；候选均失败时，仍保留缺口且不编造事实。选定其中实际复现的情境作为维护用例。
- [ ] 执行对应测试并检查修改范围，独立提交这个可验证修复。

**交付:** 更准确的错误信息和/或可用的读取路径；不承诺解除外部网站访问限制。

### Task 3：让读到的事实变成直接答案

**Files:** 必要时 `agents/sub_agent.py`、`agents/source_reading.md`、`research_contract.py`、现有报告渲染；`tests/test_research_completion.py`。

**Interfaces:** 保持现有 `ResearchReport.findings`、`metrics`、`as_of`、`sources`、`summary` 和 `VerificationReport`；不另造持仓报告系统。

- [ ] 用已保存且可公开复用的资料建立一个离线来源→报告用例；期望数字由原始表格人工核对，不从待测提取函数生成。
- [ ] 核对同一观察日期、权重单位、十项顺序、metrics→evidence_id→source_url 绑定。对日期不明的源，不得把 fetched_at 填进 as_of。
- [ ] 只有读到事实却未答出时，修改研究报告说明/现有呈现路径：先输出所问事实，再给日期、来源、核验状态和缺口；保留结构化 source of truth。
- [ ] 运行离线回归，确认 unsupported findings 仍被 withholding，拒绝和未核验结果仍如实展示。不得为了覆盖率改 verifier。
- [ ] 如现有代码已经满足这些条件，只记录验收证据，不增加测试或实现层。

**交付:** 内容完整度与核验状态分开表达、能直接使用的持仓答案。

### Task 4：真实验收与迁移检查

**Files:** `reports/usefulness/<unique-id>/`；`docs/structured-research.md`、`TODO.md`。

**Interfaces:** 原 CLI、保存的 ResearchReport/VerificationReport/UsageSummary；人工 `review.md` 汇总，无自动晋升。

- [ ] M1 总共最多三个完整真实研究 session：一个基线、一个修复后的 MTUM、一个同类迁移问题（QUAL 前十大持仓）。不运行至“碰巧成功”为止。
- [ ] 修复后保持基线模型、policy、预算和提问一致；记录来源在两次运行间可能变化，不能把实时数据差异宣称为纯策略提升。
- [ ] 对照保存原文人工核对表格，记录内容覆盖、来源/日期、核验状态、耗时和用量。迁移题检验方法是否只对 MTUM 硬编码有效。
- [ ] 无法完成十项或核验时，将对应维度标记未完成。若只是运行结束而没有事实答案，M1 不通过。
- [ ] 执行 `uv run pytest --collect-only -q`（最多 30），再执行 `uv run pytest` 和 `git diff --check`。
- [ ] 更新说明和实际可复现命令，提供一个已保存的有用答案链接，说明遗留限制。此时才评审是否进入 M2。

**M1 停止条件:** 三个 session 上限到达、允许来源均不可读、或需要新增授权/数据服务。此时交付准确阻塞说明和已有证据；不转向修改 arena 来展示进步。

## M2：扩大到真实 momentum 研究（M1 之后单独规划实现）

固定三个产品问题：

1. 指定日期窗口内 MTUM 相对 SPY 的收益、波动和回撤怎样？复用现有确定性数据/计算，标明 ETF proxy 的范围。
2. 相比一个有真实快照的历史日期，持仓集中度如何变化？缺历史数据时不编造比较。
3. 当前有哪些支持或反驳拥挤/反转风险的证据？不要从单一价格表现推断仓位，也不把引擎评分称为概率。

每份输出统一为：直接结论 → 关键数值与日期 → 支持证据 → 反证/其他解释 → 未知 → 值得继续观察什么。采用已有 Single/Team 路径，不新建协调系统。

验收：三个问题都有可审阅的真实运行记录；每条主要结论可回溯；用户能指出答案节省了哪项手工研究工作。无法定量回答的字段明确说明原因。

## M3：真实研究驱动的 self-improvement（M2 之后）

- 从实际使用中选择一个可修复失败和一个已通过案例：例如漏找可读来源、混淆数据日期、遗漏反证。外部数据不存在不计为推理错误。
- 用现有 gap ledger/importer/policy/shadow workflow；先核对实际工具轨迹是否被 replay 支持。`read_url` 等调用若不被现有 shadow replay 接受，标记兼容性阻塞并另行设计，不能删掉调用来假装可比。
- 基线与候选共享记录的来源、模型和预算；候选只改通用研究指引，不复制答案/来源线索，不改 verifier。
- 比较“是否答对目标问题、证据是否充分、通过案例是否退步、时间/用量变化”。无改善或不确定如实保留。
- 人工确认改进有用后，再讨论推广范围和策略激活。RSI arena 是辅助回归工具，自动晋升不是产品可用的前置条件。

## 执行顺序

先执行 Task 1；根据真实断点选择 Task 2/3 中必要的工作；完成 Task 4 后回到用户评审。当前不同时启动 M2/M3，不调用 live API，也不新增实现代码。

## M1 execution record — 2026-09-14

User authorized implementation. Task 1 completed: current official CSV works;
actual failures are over-scoped research, mixed arithmetic and unchecked display.
Task 2 reader changes skipped as unnecessary. Task 3 implemented with synthetic
source→report integration and verdict-aware rendering tests. Task 4 used all
three live sessions and one reader probe. MTUM/QUAL source coverage is 10/10;
QUAL independent verification completed, MTUM timed out. Full M1 verification
acceptance remains open. No policy/verifier changes or M2/M3 work performed.
See [execution review](../../m1-usefulness-review.md). Planning-time no-live-code
restrictions above were superseded by the user's implementation instruction.
