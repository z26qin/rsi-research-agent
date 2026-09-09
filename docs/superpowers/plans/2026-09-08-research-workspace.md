# Momentum Research Workspace Implementation Plan

> **For agentic workers:** Use superpowers:executing-plans to implement this plan task-by-task in the current session. Steps use checkbox (`- [ ]`) syntax for tracking. This plan does not require subagent dispatch.

**Goal:** 实现基于 Mock 与只读会话产物的交互式研究工作台，完成从首页到证据、验证、任务详情的阅读闭环。

**Architecture:** 独立 React 前端通过 ResearchDataSource 接口读取类型化 Demo 或本地产物快照。离线同步脚本只读取 reports 和角色声明，生成浏览器可按需加载的文件；页面通过 URL 管理选择和筛选，Demo 的状态机与真实数据读取分离。

**Tech Stack:** React、TypeScript、Vite、Tailwind CSS、Lucide、React Router、TanStack Query、Zod、Vitest、Testing Library；Python 标准库负责离线文件索引，pytest 验证导入行为。按需使用 shadcn/ui 交互基础组件。

**Spec:** [已批准的设计文档](../specs/2026-09-08-research-workspace-design.md)。实施前完整阅读。

## Global Constraints

### 执行记录（2026-09-08）

实施位置：`.worktrees/research-workspace`，分支 `codex/research-workspace`。未部署、未运行真实 Agent，原始 reports 未修改。

- [x] Task 1：React/TypeScript 框架、设计 tokens、类型化 Demo、三栏首页及参考资产。
- [x] Task 2：只读导入、原子快照、坏文件诊断、symlink 边界、静态角色目录；18 项导入测试。
- [x] Task 3：Zod 校验、统一读取接口、来源切换及持久化、部分数据保留、证据歧义保护。
- [x] Task 4：首页、会话列表及 Overview / Evidence / Verification / Trace 阅读闭环。
- [x] Task 5：表单、分阶段 Demo、暂停/恢复、搜索和快捷键、本地审阅标记。
- [x] Task 6：Daily Briefs、Gaps、Agents、Library 页面与筛选。
- [x] Task 7：响应式抽屉、焦点返回、视觉对照及 2 条浏览器验收流程。记录见 `frontend/design-qa.md`。
- [x] Task 8：默认 Demo-only / 显式 local 构建、打包隔离测试、运行文档；4 项打包测试及 4 项模板测试。

实现调整：为保持第一阶段代码扁平，normalizer/adapters/mock 各收敛为一个模块，页面直接使用经 Zod 校验的后端 snake_case 契约，不额外复制 camelCase 字段。导入采用会话级 envelope 与 diagnostics；trace 保留来源哈希，审阅键使用完整对象身份与 claim 内容，不宣称提供完整逐文件 provenance 审计系统。当前一次载入本地有界集合，未来远程分页通过 ResearchDataSource 替换。源文件未记录的时间不使用导入时间冒充；source snapshotAt 单独表示导入时刻。

前端回归测试覆盖独立坏文件、重复证据 ID、Demo 阶段、持久化、书签合并、导航筛选和数值语义。末次覆盖率约 89% statements / 82% branches；设置全局 80% 阈值。实际研究会话为空，因此真实产物端到端阅读仍待用户产生文件后验证；这不是实时后端接入验收。

以下保留原始分步设计清单作为方案记录；上述执行矩阵与测试/QA 文件是本次交付的实际验证记录。

- 新前端位于独立的 `frontend/`。
- 真实产物只读；新建研究只创建浏览器内 Demo。
- 界面默认英文，设计文档使用中文。
- 左栏 205px，右栏 330px，顶部约 76px，主区约 28–32px 内边距。
- 主参考为用户提供的 1536×1024 桌面截图。
- `findings` 为证据事实来源，Verifier 状态原样保留。
- 已记录任务状态不冒充实时进程状态；任务完成计数不是全流程完成百分比。
- 构建默认包含 Demo。本地产物构建须使用明确选项，不发布站点。
- `frontend/.generated/artifacts/` 不提交 Git。
- JSON 存在但损坏时显示读取错误，不回退 Markdown 掩盖问题。
- 无真实模型调用、引擎运行、政策修改或原始 reports 写入。
- UI 范围依据本次用户批准；AGENTS.md 中其余研究与工具授权约束继续生效。

## 起点、依赖与执行约定

当前是 Python CLI 仓库，没有 frontend；本次检查未发现 reports 下的会话 JSON。演示与适配器验证使用明确的合成 fixtures，实际文件出现后可通过相同路径载入。

已检查的后端来源：`models/schemas.py`、`coordinator/task_board.py`、`state/reports.py`、`state/traces.py`、`tools/__init__.py`、`daily_brief.py`。这些文件仅作为契约参考。

执行顺序：任务 1 → 2 → 3 → 4 → 5 → 6 → 7 → 8。每一项完成时记录修改文件、验证结果与剩余限制；修复当前任务的问题后再前进。使用隔离分支 `codex/research-workspace`，执行时按 using-git-worktrees 流程检查已有工作区，保留当前设计文档。计划阶段不创建应用或安装依赖。

实施时再核验依赖的官方安装方法和兼容版本，并提交 lockfile。使用当前安装的 Product Design desktop prototype 启动脚本；保留模板的静态构建与 worker 包装，不部署。

## 文件责任地图

| 文件/目录 | 责任 |
| --- | --- |
| `frontend/scripts/sync_artifacts.py` | CLI 参数、同步协调、稳定快照发布 |
| `frontend/scripts/artifact_io.py` | 受限文件读取、JSON/JSONL 诊断、路径检查 |
| `frontend/scripts/profile_catalog.py` | 从显式常量读取角色 allowlist，不加载应用运行时 |
| `frontend/scripts/test_sync_artifacts.py` | 使用临时目录验证只读导入 |
| `frontend/src/data/schemas.ts` | 输入产物及快照 envelope 的 Zod schemas |
| `frontend/src/types/index.ts` | 从 schemas 推导的类型和展示模型 |
| `frontend/src/data/normalizers/` | session、verification、brief、gap 规范化 |
| `frontend/src/data/adapters/` | 同一个读取接口的 artifact/mock 实现 |
| `frontend/src/data/mock/` | 完整、部分、失败场景及 Demo 状态机 |
| `frontend/src/app/` | providers、路由、来源切换与 URL 状态 |
| `frontend/src/components/` | 按已批准设计分类的展示组件 |
| `frontend/src/pages/` | 页面组合，不直接读取产物 |
| `frontend/src/hooks/` | 快捷键、本地审阅、Demo 持久化 |
| `frontend/tests/` | 适配器、交互及存储边界测试 |
| `frontend/design-qa.md` | 视觉对照记录、修复与最终结果 |
| `README.md`、`frontend/README.md` | 运行方法与前端设计/数据说明 |

## Task 1：可启动的视觉框架与 Demo 契约

**Files:**
- Create: `frontend/package.json`、`frontend/tsconfig.json`、`frontend/vite.config.ts`、`frontend/vitest.config.ts`。
- Create: `frontend/src/main.tsx`、`frontend/src/app/App.tsx`、`frontend/src/app/Providers.tsx`、`frontend/src/styles.css`。
- Create: `frontend/src/components/layout/AppShell.tsx`、`Sidebar.tsx`、`CommandBar.tsx`、`ContextRail.tsx`。
- Create: `frontend/src/data/schemas.ts`、`frontend/src/types/index.ts`、`frontend/src/data/adapters/ResearchDataSource.ts`、`frontend/src/data/mock/fixtures.ts`。
- Create: `frontend/tests/setup.ts`、`frontend/tests/fixtures.test.ts`。
- Modify: 根目录 `.gitignore`，忽略 frontend 的 node_modules、.generated、dist 和测试缓存。

**接口与对象标识：**

```ts
export type DataSourceKind = 'artifact' | 'demo'
export type Availability = 'complete' | 'partial' | 'unavailable' | 'legacy'
export interface Provenance {
  kind: DataSourceKind
  snapshotId: string
  snapshotAt: string
  sourceFile: string | null
  contentHash: string
}
export interface Diagnostic {
  file: string
  code: string
  message: string
  line?: number
}
export interface ResearchDataSource {
  listSessions(): Promise<SessionSummary[]>
  getSession(id: string): Promise<ResearchSession>
  listDailyBriefs(): Promise<DailyBriefSummary[]>
  getDailyBrief(id: string): Promise<DailyBrief>
  listGapLedgerEntries(): Promise<GapLedgerEntry[]>
  listAgentProfiles(): Promise<AgentProfile[]>
}
```

SessionSummary 定义 id、question、recordedStatus、updatedAt（可空）、taskCounts、evidenceCount、verificationStatus（可空）、availability、provenance、diagnostics。ResearchSession 扩展 summary，包含 tasks、reports、evidence、verification、synthesis、traces；字段缺失与空集合分别表达。

AgentTask 保留后端 Task 字段和原始 ID；EvidenceItem 保留后端 Evidence 字段，并增加 taskId、provenance。EvidenceVerdict 保留原 verdict，将 task_id 映射为 taskId。DailyBrief 保留 daily_brief_v1 语义；DailyBriefSummary 是列表所需字段的 Pick。GapLedgerEntry 保留完整 occurrence 字段。AgentProfile 包含 name、displayName、description、tools、kind（research/verification）。后端 raw schemas 使用 snake_case；展示层统一 camelCase，转换仅在 normalizers 中发生。

- [ ] 保存用户截图到 `docs/design/assets/momentum-reference.png`，从已提供附件复制并实际打开确认；附件缺失时保留原对话参考，报告本地对照资产缺失。
- [ ] 使用已读取的 Product Design bootstrap 在空的 frontend 目录创建 desktop prototype；随后用 apply_patch 迁移入口为 TypeScript 并配置 Tailwind、测试环境和 npm scripts。
- [ ] 从现有 Pydantic 定义建立 runtime schemas，明确 enum、optional 与 nullable 区别。schemas 校验内容，不重新计算 verifier 或引擎结论。
- [ ] 编写三组 fixtures，导出 demoComplete、demoPartial 和 initialDemo：多分析师完整会话、含 BLOCKED/缺失产物的部分会话、等待展示的 Demo。另导出 unavailableBriefEnvelope 和 artifactProvenance 用于规范化测试。证据至少包含支持/反对、中等置信度、verified/rejected/unchecked 与无 verdict；Sample claim 固定为 rejected 且没有可用来源的交互测试案例。
- [ ] 建立 AppShell 和 tokens；默认 Home 可渲染，参考比例下放入实际 Demo 内容。未完成路线先不展示可点击入口。
- [ ] 验证 fixtures 的引用自洽，例如：

```ts
it('keeps explicit unchecked distinct from missing review', () => {
  expect(demoComplete.verification.verdicts.some(v => v.status === 'unchecked')).toBe(true)
  const reviewedIds = new Set(demoComplete.verification.verdicts.map(v => v.evidenceId))
  expect(demoComplete.evidence.some(e => !reviewedIds.has(e.id))).toBe(true)
})
```

- [ ] 运行 `npm --prefix frontend run typecheck`、`npm --prefix frontend run test -- --run tests/fixtures.test.ts` 和 build；浏览器查看 1536×1024 框架，记录初次视觉基线。

**可独立评审结果：** 应用可启动，视觉方向、字体与三栏比例可见，Demo 数据通过契约校验。

## Task 2：只读会话导入与原子快照

**Files:**
- Create: `frontend/scripts/sync_artifacts.py`、`frontend/scripts/artifact_io.py`、`frontend/scripts/profile_catalog.py`、`frontend/scripts/test_sync_artifacts.py`。
- Modify: `frontend/package.json`、`frontend/vite.config.ts`。

**接口：**

```python
def sync_artifacts(reports_root: Path, output_root: Path, project_root: Path) -> dict:
    """Read allowed artifacts, publish a snapshot, return its manifest."""
```

CLI 接受 `--reports-root`、`--output-root`、`--project-root`。默认路径从脚本位置推导仓库根，不依赖调用 cwd。输出 manifest 包含 schemaVersion、snapshotId、snapshotAt、availability、sessions、briefs、gaps、profiles、diagnostics；条目路径是由脚本生成的 URL-safe ID，不使用来源字符串拼接输出路径。

每个文件以 `{relativePath, contentHash, availability, payload, diagnostics}` envelope 保存。会话条目保存 board、reports、verification、synthesis、traces 与 legacy 正文 envelope。浏览器原始 payload 必须经过 Task 3 schema 校验后才进入组件。

- [ ] 首先实现临时目录测试，覆盖完整会话、只有 brief 的目录、缺少 reports、损坏 JSON、JSONL 个别坏行、symlink、越界路径和写入期间文件变化。
- [ ] 写入文件内容不变测试：

```python
def test_sync_never_changes_source(tmp_path):
    source = tmp_path / "reports"
    session = source / "session-a"
    session.mkdir(parents=True)
    board = session / "task_board.json"
    original = b'{"session_id":"session-a","question":"Risk?","tasks":[]}'
    board.write_bytes(original)
    sync_artifacts(source, tmp_path / "generated", tmp_path)
    assert board.read_bytes() == original
    assert sorted(p.relative_to(source).as_posix() for p in source.rglob('*') if p.is_file()) == ['session-a/task_board.json']
```

- [ ] 运行 `uv run pytest frontend/scripts/test_sync_artifacts.py -q` 确认新增行为测试失败，再实现对应读取逻辑。
- [ ] 只扫描一级会话目录及规定的 sub_reports；不递归抓取 policies、engine_runs、eval、隐藏目录或未知文件。不跟随 symlink/source_path。
- [ ] JSONL 坏行采用逐行诊断和 partial；读取前后 stat/hash 改变时视为正在写入，保留该对象上次成功快照，标注 stale。此规则区分稳定坏行与读写竞争。
- [ ] 将不可变快照写入 `snapshots/<snapshotId>/`，所有对象成功写出后原子替换 manifest；不覆盖浏览器仍可能读取的旧快照。
- [ ] profile_catalog 使用 Python ast 读取 tools/__init__.py 中 PROFILE_TOOLS 字面量和指定 profile Markdown，不 import tools、不加载 .env；找不到常量时返回诊断与空列表，无默认工具。
- [ ] 加入 `sync:artifacts` 与 predev；本地 Vite 中间件只服务已生成 manifest 和其引用文件，不开放原始 reports 路径。默认监听 loopback。
- [ ] 再运行该测试文件；检查网络端点只能读取快照文件，不存在执行/写入研究接口。

**可独立评审结果：** 用合成会话生成可读快照，原文件字节保持不变，损坏或未知数据有诊断。

## Task 3：规范化、来源切换与异步加载

**Files:**
- Create: `frontend/src/data/normalizers/session.ts`、`verification.ts`、`brief.ts`、`gaps.ts`。
- Create: `frontend/src/data/adapters/ArtifactResearchDataSource.ts`、`MockResearchDataSource.ts`。
- Create: `frontend/src/app/DataSourceProvider.tsx`、`frontend/src/hooks/useResearchData.ts`。
- Create: `frontend/tests/normalizers.test.ts`、`frontend/tests/data-source.test.ts`。

**接口：**

```ts
normalizeSession(raw: unknown, provenance: Provenance): ResearchSession
normalizeBrief(raw: unknown, provenance: Provenance): DailyBrief
normalizeGaps(raw: unknown, provenance: Provenance): GapLedgerEntry[]
resolveVerdict(evidence: EvidenceItem, verdicts: EvidenceVerdict[]):
  { kind: 'matched'; verdict: EvidenceVerdict } |
  { kind: 'missing' } | { kind: 'ambiguous'; candidates: EvidenceVerdict[] }
```

normalizeSession 校验 envelope 与 payload，把读取错误转为 diagnostics。Verdict 优先匹配同 evidence ID 和明确 taskId；旧 verdict 无 taskId 时仅允许在会话内唯一匹配。重复冲突不得以第一条覆盖。

- [ ] 编写 enum/缺失/空值/legacy/歧义引用测试，再实现四个 normalizer。研究正文维持原内容，Markdown 禁用 HTML。
- [ ] 验证缺失数值不被转换为 0，例如：

```ts
it('preserves unavailable monitoring values', () => {
  const brief = normalizeBrief(unavailableBriefEnvelope, artifactProvenance)
  expect(brief.status).toBe('unavailable')
  expect(Object.keys(brief.metrics)).toHaveLength(0)
})
```

- [ ] 实现 canonical traces 优先级；只有 canonical 文件不存在时使用 verification.traces。相同 ID 相同内容去重，不同内容保留冲突诊断。来源 trace 数量不替代 task.tool_calls。
- [ ] Gap occurrence ID 以来源会话与 evidence ID 确定；相同 evidence 在不同会话保留独立条目；缺失来源使用明确 unknown 标记与稳定文件行身份，不合并猜测。
- [ ] 两个 data source 实现同一读取接口；artifact adapter 仅获取 manifest 引用文件，unknown id 返回 Not found。
- [ ] Query keys 包含 source kind、snapshotId、资源 ID。切换来源使相关缓存失效，保持来源标识可见。无文件进入标识清晰的 Demo；读取失败显示诊断和手动 Demo 入口。
- [ ] 将 Refresh 定义为重新载入 manifest，显示 snapshotAt；README 提示先执行 sync 命令才会获取新源文件内容。
- [ ] 运行 `npm --prefix frontend run test -- --run tests/normalizers.test.ts tests/data-source.test.ts`；分别用 mock 与合成 artifact 打开相同会话组件。

**可独立评审结果：** 页面可切换来源，数据缺失、验证状态和旧文件的语义得到保留。

## Task 4：首页与研究阅读闭环

**Files:**
- Create: `frontend/src/pages/Dashboard.tsx`、`Sessions.tsx`、`SessionWorkspace.tsx`。
- Create: `frontend/src/components/dashboard/MetricsStrip.tsx`、`ResearchUpdateCard.tsx`、`RecentSessionsTable.tsx`。
- Create: `frontend/src/components/sessions/SynthesisDocument.tsx`、`SessionTaskBoard.tsx`、`ActivityTimeline.tsx`。
- Create: `frontend/src/components/agents/AgentInspector.tsx`、`frontend/src/components/evidence/EvidenceCard.tsx`、`EvidenceList.tsx`。
- Create: `frontend/src/components/verification/VerificationPanel.tsx`、`frontend/src/components/sessions/TraceList.tsx`。
- Create: `frontend/src/app/sessionSelection.ts`、`frontend/tests/session-workspace.test.tsx`。

**接口：**

```ts
type SessionSelection = {
  tab: 'overview' | 'evidence' | 'verification' | 'trace'
  taskId?: string
  evidenceId?: string
  traceId?: string
}
```

Inspector 根据当前 selection 选择单个详情；选择证据与任务通过 URL search params 表达。未知选择显示缺失状态与清除选择入口。

- [ ] 写主路径测试后实现：从 Sessions 打开动态会话、进入 Evidence、选择 claim、展示来源及其准确 verdict，再返回上一标签。
- [ ] 交互测试使用用户可见行为，例如：

```ts
await user.click(screen.getByRole('tab', { name: 'Evidence', exact: true }))
await user.click(screen.getByRole('button', { name: 'Inspect evidence: Sample claim' }))
expect(screen.getByRole('complementary', { name: 'Research inspector' })).toHaveTextContent('Rejected')
expect(screen.getByRole('complementary', { name: 'Research inspector' })).toHaveTextContent('Source unavailable')
```

- [ ] Dashboard 按设计映射展示指标、三张更新卡、近期会话表、任务快照和最近活动；不足三条时展示实际条数，空列表显示入口，不复制卡片充数。
- [ ] Workspace 渲染原 synthesis 字段和子报告；无 synthesis 时仍可浏览已有 findings。没有 evidence ID 级引用的摘要只链接“Session evidence”。
- [ ] EvidenceList 实现 stance/category/confidence/verdict/task 筛选；VerificationPanel 显示 overall_status、反证与缺口并导航到证据；“Not reviewed”与“Unchecked”区分。
- [ ] TaskBoard 显示五种任务状态和四种 kind；Inspector 显示 assignment、error、用量及已有记录。ACTIVE 标为记录状态，无假 live 指示器。
- [ ] TraceList 将 args、observation、truncated、replay source 折叠展示，只有查看与复制操作。
- [ ] ActivityTimeline 按真实可用时间排序，展开显示来源对象；无 timestamp 的记录单列。
- [ ] 运行 workspace 测试、typecheck；浏览器完成一次完整会话和一次部分会话阅读。

**可独立评审结果：** 首页到任务、证据、验证和 trace 的核心闭环可操作。

## Task 5：新建 Demo、搜索与本地审阅

**Files:**
- Create: `frontend/src/pages/Research.tsx`、`frontend/src/data/mock/demoReducer.ts`、`frontend/src/hooks/useDemoSession.ts`。
- Create: `frontend/src/components/shared/CommandPalette.tsx`、`frontend/src/components/research/ThesisDiffCard.tsx`。
- Create: `frontend/src/hooks/useKeyboardShortcuts.ts`、`frontend/src/hooks/useReviewMarks.ts`。
- Create: `frontend/tests/demo.test.ts`、`frontend/tests/research-interactions.test.tsx`。

**接口：**

```ts
type DemoAction =
  | { type: 'advance' }
  | { type: 'pause' }
  | { type: 'resume' }
  | { type: 'reset' }
type ReviewMark = 'accepted' | 'rejected' | 'investigate' | 'saved'
```

DemoState 定义 scenarioId、question、mode、maxAgents、stageIndex、paused、session。每个预编写阶段是确定性的 state patch；paused 不接受 advance，完成后不继续计时。Single 固定一个研究角色；Team 的 maxAgents 在 1–4 内控制演示研究任务数，后续验证独立呈现。

- [ ] 先写 reducer 测试，验证暂停、继续、完成幂等、reset、恢复不重复推进，例如：

```ts
const paused = demoReducer(initialDemo, { type: 'pause' })
expect(demoReducer(paused, { type: 'advance' })).toEqual(paused)
expect(demoReducer(paused, { type: 'resume' }).paused).toBe(false)
```

- [ ] Research 表单提供问题、场景、Team/Single、并行数和侧重点；展示 Example plan，提交文案为 Start demo，预编写内容始终标示 Demo。
- [ ] useDemoSession 在 sessionStorage 存储版本化状态；异常时降级内存并说明刷新不保留。刷新恢复阶段位置，但页面关闭时不模拟后台运行。
- [ ] CommandPalette 检索当前来源中的 session、question、evidence、brief；结果打开对象对应页面。Ask/Research/Monitor 改变输入意图与 Demo 场景入口。
- [ ] 加入 Cmd/Ctrl+K、G H/G R/G S，导航序列有短超时，编辑区忽略；dialog 支持 Escape、焦点返回和键盘结果选择。
- [ ] ThesisDiffCard 在 Demo 场景中呈现明确的示例前后变化。本地 review marks 使用 source/session/object/contentHash 组合键，不修改 adapter 对象或 verdict。
- [ ] 运行 Demo 和交互测试；在浏览器验证刷新恢复、暂停状态、快捷键以及拒绝示例更新后原 verdict 不变。

**可独立评审结果：** 用户可创建并探索完整 Demo，搜索和审阅操作有真实本地反馈。

## Task 6：简报、缺口、角色与资料库

**Files:**
- Create: `frontend/src/pages/DailyBriefs.tsx`、`DailyBriefDetail.tsx`、`GapLedger.tsx`、`Agents.tsx`、`Library.tsx`。
- Create: `frontend/src/components/briefs/BriefDocument.tsx`、`frontend/src/components/verification/GapLedgerTable.tsx`。
- Create: `frontend/tests/supporting-pages.test.tsx`。
- Modify: `frontend/src/app/App.tsx`、`frontend/src/components/layout/Sidebar.tsx`。

- [ ] 先写产品约束测试：unavailable brief 隐藏分数；incompatible changes 展示 comparisonNote；Verifier 不出现在研究角色分派选项；不同 occurrence 的缺口分别可见。
- [ ] DailyBriefDetail 呈现 as-of、生成时间、dataCutoff、metrics、changes、limitations 与审计抽屉；score 文案为 Monitoring score，不格式化成概率。
- [ ] GapLedger 实现状态与 capability 筛选，打开来源和 consumed task；缺失来源/关闭原因时显示未记录，不创建假链接。
- [ ] Agents 使用真实读取的角色目录；当前加载数据的贡献数量标明范围。无目录时明确缺失，未知角色工具为空。
- [ ] Library 从已加载资源建立统一列表和按需证据索引；搜索结果给出来源和对象类型，复用 Workspace/Brief 详情。
- [ ] 完成 Sidebar 所有约定导航，以及无结果、Not found、损坏来源状态。
- [ ] 运行 supporting-pages 测试，在浏览器检查每个可见导航的实际内容。

**可独立评审结果：** 所有批准页面均有完整入口、真实读取或明确 Demo 内容。

## Task 7：响应式、可访问性与同视口视觉校准

**Files:**
- Modify: `frontend/src/styles.css`、layout 与核心交互组件。
- Create: `frontend/design-qa.md`、`frontend/tests/accessibility.test.tsx`。

- [ ] 在 1536×1024 浏览器打开参考和应用截图，比较三栏宽度、顶部高度、hero、三卡和表格的垂直节奏。视觉验收以阅读密度和布局为主，允许已批准的内容替换。
- [ ] 按设计断点实现右栏抽屉、紧凑导航、两列/单列卡片、表格自身滚动；检查 1280、1024、390px，无页面正文横向溢出。
- [ ] 增加 prefers-reduced-motion 支持，检查 hover/focus/selected/loading/empty/error 状态；移动抽屉有焦点约束与关闭后返回。
- [ ] 可访问性测试覆盖 dialog 焦点返回、图标 accessible name、输入区快捷键不跳页；例如打开 Inspector 再按 Escape 后验证原触发按钮获得焦点。
- [ ] 使用当前 Product Design design-qa 技能完成参考/实现同输入比较，修复 P0/P1/P2 并重新截图；记录剩余 P3。只有实际比较完成才能写 final result: passed。
- [ ] 检查 console，完成 Home → Session → Evidence → Verification → Gap，以及 Demo 暂停/恢复两条浏览器验收路径。

**可独立评审结果：** 桌面视觉达到参考质量，窄屏和键盘使用可行，有可追溯 QA 记录。

## Task 8：构建边界、运行文档与交付验证

**Files:**
- Create: `frontend/scripts/build_artifacts.mjs`、`frontend/README.md`。
- Create: `frontend/tests/build-artifacts.test.mjs`。
- Modify: `frontend/package.json`、根目录 `README.md`。

- [ ] 默认 build 仅包含 Demo；显式 `build:local` 才把选定生成快照复制到 `dist/client` 对应路径。build wrapper 只使用固定生成目录，清理自身输出不碰 reports。
- [ ] 写打包隔离测试：在本地快照放入唯一 marker，默认构建无 marker、无快照索引；显式本地构建含所选快照，跨构建不残留旧 snapshot。保留模板 worker fallback，深链接刷新仍加载 SPA。
- [ ] 添加 `test:build-artifacts` 脚本执行 `node --test tests/build-artifacts.test.mjs`；Vitest include 仅匹配 `.test.ts`/`.test.tsx`，避免重复执行 Node 原生测试。
- [ ] README 说明安装、dev、sync、Refresh 语义、Demo 来源、两种 build、数据边界、键盘、运行时字体和本地存储时限。根 README 链接前端说明。
- [ ] README 列出确切命令：

```bash
npm --prefix frontend install
npm --prefix frontend run dev -- --host 127.0.0.1 --port 4173
npm --prefix frontend run sync:artifacts
npm --prefix frontend run typecheck
npm --prefix frontend run test -- --run
uv run pytest frontend/scripts/test_sync_artifacts.py -q
npm --prefix frontend run build
npm --prefix frontend run test:build-artifacts
npm --prefix frontend run test:sites
```

- [ ] 运行上列相应验证；仅后端代码实际改变时扩大到相关后端回归测试。检查 git diff 和本地 reports 内容未修改。
- [ ] 逐条核对设计验收清单并更新本计划的 checkbox 与验证记录。交付时报告实际通过项、合成/真实产物覆盖范围和未完成项。
- [ ] 保留本地预览并给出可点击链接；不部署、不声称可实时运行真实 Agent。

**可独立评审结果：** 可运行、可验证、可演示的前端交付，附完整运行说明。

## 计划自检与覆盖关系

| 已批准规格 | 实施任务 |
| --- | --- |
| 视觉系统、三栏与动态路由 | 1、4、7 |
| 类型化 Mock 与只读适配器 | 1、2、3 |
| 任务、证据、验证、trace、时间线 | 3、4 |
| 新建 Demo、搜索、快捷键、审阅 | 5 |
| Briefs、Gaps、Agents、Library | 6 |
| 空状态、损坏数据与来源边界 | 2、3、4、6 |
| 响应式、可访问性、视觉 QA | 7 |
| 构建、README、本地交付 | 8 |

所有任务均依赖同一设计规格；没有添加真实任务控制服务。字段与 UI 语义以现有后端为准，未持久化的阶段进度、精确结论引用和关闭原因保持缺失。实施验证记录从执行时填写，本计划没有将任何实现检查标为已通过。
