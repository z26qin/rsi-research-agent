# Momentum Research Agent：前端工作台设计

状态：产品原则、页面流程与数据架构已在对话中批准；本文将其整理为实施与验收依据。

本阶段交付：完整设计规格。本文不代表前端已实现或已通过浏览器验收。

## 1. 产品目标与设计要点

为现有 Momentum Research Agent 提供一个可阅读、可探索、可演示的研究工作台。用户可以从研究问题进入会话，理解分析师的工作，检查证据和验证结果，再定位未解决的问题。

- 研究会话是主要组织单位，可涉及公司、主题或市场风险。
- 首页回答：最近有什么发现、哪些任务值得关注、还有哪些证据缺口、数据更新到了哪天。
- 暖白背景、编辑感衬线标题、细边框和低饱和状态色，以用户提供的桌面截图为视觉基准。
- 左侧导航、中间阅读、右侧检查详情，减少上下文切换。
- Agent 的任务状态、报告完整度、证据置信度和独立验证结果分别呈现。
- 证据卡可追溯来源与摘录；技术细节按需展开。
- 真实产物与 Demo 明确区分，缺失数据保留其缺失语义。
- 第一版通过只读产物适配器连接现有后端，为后续 API 留出边界。
- 桌面优先，同时支持窄屏、键盘操作和减少动态效果。

## 2. 范围与现有仓库的关系

新前端位于独立的 `frontend/`。用户本次明确要求增加前端，构成对 AGENTS.md 中旧有“no web UI”约束的本次范围例外；其他引擎、授权、验证和持久化规则继续生效。

第一版包含：Dashboard、Research 编辑器、Sessions 列表、Session Workspace、Daily Briefs、Gap Ledger、Agents 和 Library。辅助页面复用列表、详情与筛选组件，不建立独立产品子系统。

真实产物只读；新建研究只创建浏览器内 Demo。暂停、继续和重置仅适用于 Demo 播放。真实任务启动、恢复、取消、工具执行、政策修改、行情订阅、事件调度和账户服务不属于第一版。

界面默认英文，设计文档使用中文。股票名称与示例内容作为数据出现，不写死到路由或页面结构中。

## 3. 主要用户流程

### 3.1 阅读已有研究

首页研究更新 → 会话 Overview → 选择关键证据 → 查看来源与验证结果 → 标记待查或打开相关缺口。

“研究发现”和“已验证证据”分别统计。最终摘要存在时优先展示，同时保留报告与验证状态；没有综合结论时直接展示已获得的子报告和未完成部分。

### 3.2 理解 Agent 工作

会话任务板 → 选择任务 → 右栏显示角色、assignment、记录状态、用量、关联报告与 traces。切换任务不丢失当前阅读标签和筛选器。

### 3.3 演示新研究

Research 输入问题 → 选择 Team/Single、最大 Agent 数和研究侧重点 → Start demo → 演示任务拆解、并行执行、验证及综合过程。

Demo 使用预编写的类型化场景。输入问题用于会话标题和演示上下文，结果明确注明为示例内容；任意输入不会生成看似针对该问题的真实分析。场景预览称为“Example plan”，不称为后端预计计划。

### 3.4 检查局限

Gap Ledger 筛选 OPEN → 展开缺口 → 进入来源会话和相关证据 → 查看已记录的消费任务或后续结果。审阅标记仅保存用户本地偏好，不改变 gap 状态或 verifier verdict。

## 4. 导航与页面

| 路由 | 主要用途 | 右栏内容 |
| --- | --- | --- |
| `/` | 首页概览与最近研究 | 任务快照、近期研究活动 |
| `/research` | 新建 Demo 研究 | 示例计划、模式说明 |
| `/sessions` | 会话列表、搜索与筛选 | 选中会话概览 |
| `/sessions/:sessionId` | 会话工作区 | 任务、证据或 trace 详情 |
| `/briefs`、`/briefs/:briefId` | 日报列表和正文 | 数据截止时间、来源与局限 |
| `/gaps` | 跨会话研究缺口 | 选中缺口的来源与关联 |
| `/agents` | 分析师角色与历史贡献 | 授权工具和已有任务 |
| `/library` | 报告、证据、简报统一检索 | 所选条目详情 |

左栏主导航使用 Home、Research、Sessions、Daily Briefs、Gaps、Agents、Library。参考图中的 Coverage 改为已保存的研究范围筛选；第一版可按数据中的问题关键词筛选，不从正文自动推断完整股票覆盖或持仓。

### 4.1 Dashboard

顶部保留问候语及一句研究摘要，右侧显示产物快照更新时间。市场倒计时、模拟组合收益、实时价格、日历事件不填入真实数据首页。

指标带显示当前数据源中的会话数、已记录 ACTIVE 任务数、待核查证据数和最近简报 as-of 日期。ACTIVE 指标标为“Recorded active”，提示其来源为快照。没有值时显示 “Not available”。

Top updates 保留三张卡的布局：研究标题、问题或范围、报告时间、摘要、报告状态、验证状态、证据数量、Open research。排序依据已有报告时间，不生成未经后端支持的 materiality 或 thesis impact 分数。

下方紧凑表格展示近期会话：Question、Recorded status、Tasks、Evidence、Verification、Updated。长问题截断并提供完整可访问名称。

右栏 Agent Pulse 显示所选数据源内近期任务快照；Recent activity 只展示有记录时间戳的事件；Recent research 导向原始会话。

### 4.2 Session Workspace

页首：问题、数据来源、快照时间、可用产物状态。主区标签为 Overview、Evidence、Verification、Trace。

Overview 显示 executive summary、analysis by dimension、risk assessment、actionable signals、confidence level、dissenting views；原文保留，不推断额外投资结论。下方展示任务板、子报告、未回答问题和矛盾。

Evidence 按 stance、category、agent confidence、verification status 和任务筛选。证据卡展示 claim、source、excerpt、published/retrieved 时间和关联任务。验证结果通过 evidence ID 与任务上下文匹配；没有 verdict 显示“Not reviewed”，不同于文件中显式的 unchecked。

Verification 显示 overall_status、summary、verdicts、unsupported claims、missing evidence 和 gaps。点击 verdict 定位证据；悬空引用显示“Referenced evidence unavailable”，保留记录。

Trace 展示存储的 engine_query/web_search 调用：工具、时间、Agent、arguments、observation、截断状态和来源信息。工具调用总数可能大于存储 trace 数量，二者分别标注。查看记录不触发 replay 或实际工具调用。

任务板包含 PENDING、ACTIVE、COMPLETED、BLOCKED、CANCELLED，并以次级标签区分 research、gap、replan、followup。任务完成计数不是全流程完成百分比。

### 4.3 Daily Briefs、Gap Ledger 与 Agents

日报保留 requested_as_of、generated_at、data_cutoff、partial/unavailable、metrics、comparison_note、limitations 和 delivery 信息。监测分数不显示为崩盘概率。没有合法 changes 时显示不可比较原因；日期筛选不运行引擎。

Gap Ledger 以来源会话与 evidence ID 的 occurrence 为单位呈现 OPEN/CONSUMED/CLOSED。保留 consumed_session_id、consumed_task_id；关闭原因仅在关联记录明确支持时展示，不从 CLOSED 状态补写因果解释。eval 来源保留原始标识，不构造不存在的会话链接。

Agents 显示后端已知研究角色和明确 allowlist；Verifier 单独作为验证角色呈现，不加入可分派分析师列表。历史贡献是当前载入会话中的任务/证据计数，不声称跨全部历史的性能排名。

## 5. 视觉系统

主参考为用户提供的 1536×1024 桌面截图。实施时将该附件保存为稳定的设计参考文件；颜色和尺寸以本节为初始值，最终通过同视口截图比较调整。

| 项目 | 初始规则 |
| --- | --- |
| 页面底色 | `#F8F7F3` / `#FBFAF7` |
| 卡片 | 暖白、1px 暖灰边框、14–16px 圆角 |
| 正文 | Inter，主要 14px，辅助 12px |
| 编辑感标题 | Instrument Serif，问候 38–42px，章节 25–28px，卡片 22–24px |
| 正文颜色 | 近黑；辅助信息中性灰，满足可读性对比 |
| 强操作 | 近黑背景、白色文字 |
| 状态 | 柔和绿：完成/verified；琥珀：待核查/局限；柔和红：blocked/rejected |
| 间距 | 8、12、16、24、32px |
| 桌面框架 | 左栏 205px，右栏 330px，顶部约 76px，主区约 28–32px 内边距 |

使用 Lucide 图标；字体实施时选择可分发版本并保留许可。第一版主要依靠排版和内容，不需要装饰插画。股票 logo 仅使用已提供或合法可用的资产；缺少时使用明确的 ticker 文字标识，不仿造品牌图形。

支持/反对/中性描述证据立场，不自动映射为涨跌信号。agent confidence、report status、verification status 使用带文本的独立标签，不依靠颜色辨识。

原稿中的 thesis diff 在 Demo 中作为示例审阅组件，提供 Previous、New evidence、Proposed update、Impact，始终注明示例。真实模式只呈现有来源的前后变化；未建立跨会话对齐规则时不生成投资论点差异。Accept/Reject/Investigate 保存为本地审阅意见，绝不改变验证结果。

时间线使用有时间戳的任务开始/结束、证据获取、trace 和报告生成事件。它是 recorded activity，不声称完整阶段日志；同一时间的项目稳定排序，缺时间的记录单独列出。源数据缺少事件时不补写事件。

## 6. 交互、响应式与可访问性

- 卡片悬停最多上移 2px，轻微增强边框；主要按钮和箭头有约 150–200ms 过渡。
- Demo 进度由明确状态机推进，支持播放、暂停、继续和重置；减少动画模式取消位移与循环动画。
- 全局命令框提供 Ask、Research、Monitor 三种意图，对应示例问题、研究场景和监测场景选择。Monitor 只进入演示流程，不建立后台监控。当前意图改变提示语。
- `Cmd/Ctrl+K` 打开搜索，支持键盘选择；`G` 后接 `H` 到 Home、`R` 到 Research、`S` 到 Sessions。原 Watchlist 已改为 Sessions，故不保留无对应页面的 `G W`。
- 输入框和文本编辑区内不捕获导航快捷键。Escape 关闭最上层弹层，关闭后焦点回到触发点。
- >=1440px 保持三栏；1100–1439px 将 Inspector 收为抽屉；768–1099px 使用紧凑导航与两列更新卡；<768px 使用单栏、移动导航和单列卡片。
- 桌面顶部和导航固定；右栏在可用高度内 sticky/独立滚动。窄屏抽屉保持焦点约束和明确关闭按钮。
- 表格自身可横向滚动；页面正文无横向溢出。文本可选择，来源链接有明确名称。
- 图标按钮有可访问名称；状态变更以克制的 live region 公布，避免 Demo 每个动画帧触发播报。

## 7. 数据架构

前端组件通过统一 ResearchDataSource 获取展示模型，不直接读取文件路径。

```ts
interface ResearchDataSource {
  listSessions(): Promise<SessionSummary[]>
  getSession(id: string): Promise<ResearchSession>
  listDailyBriefs(): Promise<DailyBriefSummary[]>
  getDailyBrief(id: string): Promise<DailyBrief>
  listGapLedgerEntries(): Promise<GapLedgerEntry[]>
  listAgentProfiles(): Promise<AgentProfile[]>
}
```

ArtifactResearchDataSource 读取本地同步脚本生成的 JSON。MockResearchDataSource 提供相同接口的预编写场景；Demo 状态推进由独立 DemoSessionRunner 管理，不混入只读接口。未来 ApiResearchDataSource 遵循相同读取契约；任务控制届时增加独立 command 接口，第一版不创建假 API 实现。

每个展示对象保留 source kind（artifact/demo）、稳定 ID、源文件相对位置、源时间与读取诊断。ID 在数据源之间命名空间隔离。缺少引用、损坏对象和低可信 legacy 内容均可表达，不转换为正常数据。

| 数据 | 现有来源 | 展示约束 |
| --- | --- | --- |
| 会话与任务 | `task_board.json` | 记录状态不等于进程存活 |
| 研究报告与证据 | `sub_reports/*.json` | findings 为证据事实来源 |
| 验证 | `verification.json` | 保留原 verdict；不重新验证 |
| 综合报告 | `synthesis.json` | 不凭摘要推断证据 ID 链接 |
| 工具记录 | `traces.jsonl` | canonical；重复 trace ID 检查内容一致性 |
| trace 后备来源 | `verification.json.traces` | canonical 文件缺失时使用，并注明来源 |
| 跨会话缺口 | `gap_ledger.jsonl` | occurrence-aware，不只按 evidence ID 合并 |
| 日报 | `brief.json` | schema `daily_brief_v1`，保留局限 |
| 角色与工具 | 已知 profile / `PROFILE_TOOLS` | 显式列表，未知角色无默认工具 |

若 synthesis 没有结构化证据引用，UI 可展示“本会话证据”入口，不把附近证据声称为某一句结论的精确依据。

## 8. 只读同步与刷新

本地同步脚本仅扫描配置的 reports 根目录及已允许的产物类型，生成 `frontend/.generated/artifacts/` 索引、单会话文件、日报文件和诊断。单会话按需加载，避免全量 traces 放进首屏。

开发启动前自动同步，开发期间提供显式同步命令；UI 的 Refresh 重新读取已生成快照，旁边显示 snapshot time。第一版不从文件变化声称持续实时更新，也不提供任意文件访问端点。

输出目录不提交 Git。浏览器通过本地开发服务器读取生成内容；原始 reports 不直接挂载为静态目录。脚本拒绝越出根目录的路径与 symlink，不跟随源数据里的任意 source_path，不导出 .env、模型密钥或未列入范围的文件。Markdown 禁用原始 HTML；外链仅允许 http/https。

构建默认包含 Demo。需要本地产物构建时使用明确的构建选项；生成目录不进 Git 并不意味着打包后不会包含私有研究，README 必须解释此区别。本阶段只本地预览，不发布站点。

同步读取时检查源文件变化；遇到写到一半的 JSON/JSONL 保留上次成功快照并标记 stale/error。首次读取失败时呈现 unavailable；可读的其他会话仍可使用。新索引完成后再替换旧索引，避免浏览器读到半成品。

无本地产物时展示明确的 Demo 模式和“未发现本地会话”；源目录读取失败或已有文件损坏时展示诊断，不能静默切换成看似真实的 Mock。

## 9. 类型校验、状态与组件

使用 React、TypeScript、Vite、Tailwind、Lucide；shadcn/ui 用于 dialog、tabs、popover 等适合的交互基础组件。TanStack Query 管理异步数据；React Router 管理路由；运行时 schema 校验生成索引和载入数据。Recharts 只在存在真实比较数据或明确 Demo 图表时使用；动画优先 CSS，复杂过渡需要时再引入 Framer Motion。

URL 保留当前 tab、选中 task/evidence/trace 和过滤条件。React 本地状态负责短期菜单与抽屉；sessionStorage 保存 Demo 与本地审阅标记，键包含来源、会话和对象 ID，并声明只在当前浏览器会话中保存。产物内容变化后不错误复用旧审阅结论。

```text
frontend/
  scripts/                 # 只读索引生成
  .generated/artifacts/    # 本地生成，忽略提交
  src/
    app/                   # 路由、providers、应用入口
    pages/                 # 页面组合
    components/
      layout/ dashboard/ sessions/ evidence/
      verification/ agents/ briefs/ shared/
    data/
      adapters/ normalizers/ mock/
    types/ hooks/
```

AppShell 负责布局；SessionTaskBoard 负责选择与状态呈现；AgentInspector 负责任务详情；EvidenceCard 和 VerificationPanel 通过明确 ID 关联；SynthesisDocument 负责研究阅读；GapLedgerTable 负责 occurrence 展示；DemoSessionRunner 只管理模拟运行。

legacy Markdown 仅作为可读正文，标记 legacy/partial，不从 Markdown 猜测结构化 findings。JSON 存在但损坏时显示读取错误，不回退 Markdown 掩盖问题。

## 10. 错误、空状态与降级

| 情况 | 用户看到的结果 |
| --- | --- |
| 未找到本地会话 | Demo 明确标识，可浏览演示内容 |
| 某个子报告缺失 | 对应任务仍显示，报告标为 unavailable |
| 无 verification | Not reviewed，无绿色通过状态 |
| 无 synthesis | 已有任务与证据可读，提示综合报告尚不可用 |
| 缺少时长/用量 | 显示未记录；不拿零值代替缺失 |
| 已记录 ACTIVE 但无进程信息 | Recorded active，显示快照时间 |
| 存在 BLOCKED 任务 | 展示 error/error_type，允许查看其他可用结果 |
| 无匹配搜索结果 | 显示清除筛选与返回入口 |
| 未知会话 URL | 明确 Not found，链接回 Sessions |
| 无法解析部分 JSONL | 保留成功条目及错误诊断，整份结果标为 partial |
| 浏览器存储不可用 | Demo 可在内存运行，提示刷新后不会保留 |

## 11. 验收标准

产品：用户能从首页进入动态会话、阅读结论、筛选证据、检查 verdict、查看任务及工具记录、定位缺口并返回原上下文。Demo 完整走通且刷新可恢复。辅助页面具有实际内容和导航，不留空白占位路线。

数据：用小型测试产物验证完整会话、部分会话、legacy、损坏文件、悬空引用、重复 ID、gap occurrence、截断 trace、partial/unavailable brief。验证导入前后 reports 内容不变、无任意路径读取、无静默 Mock 替换。没有本地真实会话时，用合成测试产物证明适配器行为，并明确未在用户真实产物上验证。

交互：验证搜索与快捷键、过滤、浏览器前进后退、证据/任务联动、Demo 暂停继续、局部审阅标记、错误恢复及抽屉焦点。所有可见主操作必须有明确结果。

视觉：以 1536×1024 同视口对照原截图，检查栏宽、垂直节奏、标题、卡片密度、表格和右栏；内容调整按本规格解释，不要求保留示例股价和虚构指标。另检查 1280、1024、390px 宽度以及减少动态效果。

工程：类型检查、production build、适配器测试和关键交互测试通过；浏览器无未处理错误。只修改文档时不运行模型或引擎，也不以文档检查声称前端通过验收。实际实现后记录 design-qa 结果和仍存在的视觉差异。

## 12. 实施顺序

1. 建立 frontend、视觉 tokens、三栏 AppShell 与完整类型化 Demo。
2. 完成只读索引脚本、校验、Artifact adapter 和读取诊断。
3. 打通首页 → Sessions → Workspace → Evidence/Verification/Trace 主流程。
4. 完成 Research Demo、搜索、右栏联动和本地审阅。
5. 复用组件完成 Briefs、Gaps、Agents、Library，补充响应式和空状态。
6. 执行数据与交互验证、同视口视觉 QA，完善运行说明后交付本地预览。

## 13. 规格自检

- NBIS 仅为示例；路由基于 session ID。
- 只读 artifact 接口与 Demo 状态推进分离，真实研究无控制按钮。
- 已记录任务状态不冒充实时进程状态。
- 不编造投资评分、阶段日志、论点差异、证据引用或缺口关闭原因。
- 研究置信度、报告完整度和验证结果的语义独立。
- 原始 JSON 优先，损坏数据和 legacy 有明确呈现规则。
- 数据导入根目录、静态暴露范围、构建内容与刷新语义均已明确。
- 各页面均映射到已有产物或明确的 Demo 场景。
- 所有验收项为未来实施要求，不宣称已经完成。
