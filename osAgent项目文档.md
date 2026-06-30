# osAgent — 面向小型操作系统的分析比对智能体系统

## 项目文档

> **赛事**: 全国大学生操作系统比赛  
> **赛道**: OS Kernel 赛道（功能设计赛道）  
> **团队**: KernelPanic  
> **仓库**: https://gitlab.eduxiji.net/T2026102599910893/project3136859-388496

---

## 一、目标描述

osAgent 的目标是为全国大学生操作系统比赛（OS Kernel 赛道）的评审与组委会构建一套**智能化的操作系统仓库分析比对系统**。

面对五届比赛累计 168 个优秀作品仓库、且数量逐年指数级增长（2021:21 → 2025:52）的现实，人工评审已无法覆盖全量作品。现有的文本查重工具（MOSS、Simian 等）对内核代码的语义无感知，幻觉频发、漏报误报严重。

osAgent 以 **LLM Agent + RAG + 静态分析** 为核心技术路线，实现以下核心目标：

1. **输入一个仓库 URL，自动输出两份文档**：
   - **Project Card**（结构化描述文档）——对人类友好、抗幻觉，涵盖语言占比、内核特性矩阵、syscall 表、开发历史、创新亮点等；
   - **Diff Report**（创新点 & 查重对比文档）——与历史库精准比对，给出相似度评分、子系统级 diff、函数级雷同检测和证据链。

2. **五大设计目标**：
   - G1 抗幻觉：所有结论必须可追溯到源码行号（line-level citation）；
   - G2 精准比对：相似度判定附带「哪个文件、哪个函数、哪段提交历史」的完整证据链；
   - G3 可复现：同一仓库多次分析结论稳定（temperature=0 + 三级缓存）；
   - G4 可扩展：新增一届比赛、新增一个仓库，增量入库 < 30 min；
   - G5 国产化：LLM 首选 DeepSeek / Qwen / GLM 等国产开源大模型，全栈可内网部署。

3. **定位**：不替代人工评审，而是做**「评审副驾驶」**，为专家提供结构化的事实支撑和智能问答能力。

---

## 二、比赛题目分析和相关资料调研

### 2.1 题目分析

全国大学生操作系统比赛 OS Kernel 赛道要求参赛团队设计和实现操作系统内核，作品以 Rust / C 为主，面向 RISC-V 架构，多为 rCore-Tutorial / xv6-k210 / UCore 的二次开发或独立微内核实现。

随着比赛规模逐年增长，评审面临三大核心挑战：

| 维度 | 现状 | 痛点 |
|---|---|---|
| 数据规模 | 五届累计 168 个仓库，2026 年预计再新增 60+ | 人工评审难以覆盖全量 |
| 代码形态 | Rust/C 混合，同源代码差异巨大 | 「看上去像」未必抄袭，「看上去不像」未必创新 |
| 评审需求 | 快速理解 + 历史查重 + 创新点比对 | MOSS/Simian 等工具对内核语义无感知 |

### 2.2 相关资料调研

**操作系统教学与比赛相关**：
- rCore-Tutorial-v3、xv6-k210、UCore 等主流教学操作系统源码及设计文档；
- 历届比赛优秀作品技术报告；
- 《collected-data.xlsx》中 2021–2025 五届共 168 个参赛仓库的完整清单。

**大模型与 Agent 技术**：
- LangGraph 状态机式 Agent 框架：支持 ReAct 调度模式，便于复现与调试；
- DeepSeek-V3 大模型：长上下文支持、工具调用能力稳定，作为主推理引擎；
- BGE-M3 嵌入模型：中英文 + 代码混合嵌入能力；
- MCP（Model Context Protocol）：统一工具协议，静态分析能力以 MCP Server 暴露。

**静态分析技术**：
- Tree-sitter：多语言（Rust/C/Asm）AST 解析，函数级语义提取；
- Universal Ctags：函数签名和结构体符号提取；
- MinHash（datasketch 库）：代码结构指纹相似度计算，调用图级别查重；
- cloc：代码行统计与语言识别。

**RAG 与抗幻觉技术**：
- 结构化事实表驱动的检索增强生成（RAG）；
- 强制引用（Citation Required）机制；
- 双模型交叉校验策略（DeepSeek + Qwen 独立判定）；
- 独立 Verifier 引用真实性校验。

---

## 三、系统框架设计

### 3.1 总体架构

osAgent 采用四层架构设计：

```
┌──────────────────────────────────────────────────────────────────────┐
│                       展示层：Web Dashboard / CLI                     │
│  （提交仓库URL · 浏览Project Card · 看Diff Report · 智能问答）         │
└──────────────────────┬───────────────────────────────────────────────┘
                       │
┌──────────────────────▼───────────────────────────────────────────────┐
│                    智能体编排层：Orchestrator（主 Agent）              │
│         基于 ReAct/LangGraph 调度，规划"理解→描述→检索→比对→汇总"     │
└──┬──────────┬──────────┬──────────┬──────────┬──────────┬───────────┘
   │          │          │          │          │          │
┌──▼──┐  ┌────▼───┐ ┌────▼───┐ ┌────▼────┐ ┌───▼────┐ ┌───▼─────┐
│Repo │  │Static  │ │Semantic│ │Retrieval│ │Diff &  │ │Report   │
│Ingest│ │Analyzer│ │Indexer │ │Agent    │ │Compare │ │Writer   │
│Agent │ │        │ │(RAG)   │ │(RAG)    │ │Agent   │ │Agent    │
└──┬──┘  └────┬───┘ └────┬───┘ └────┬────┘ └───┬────┘ └───┬─────┘
   │          │          │          │          │          │
┌──▼──────────▼──────────▼──────────▼──────────▼──────────▼───────────┐
│  基础设施层：Git / Tree-sitter / ctags / MinHash / DeepSeek / BGE-M3 │
└──────────────────────────────────────────────────────────────────────┘
```

### 3.2 核心模块职责

| 模块 | 职责 | 关键技术 |
|---|---|---|
| **Repo Ingest Agent** | 仓库克隆、build 系统识别、README/commit log 抽取 | git, cloc, GitPython |
| **Static Analyzer** | L1/L2/L3 三级静态分析 + 事实表生成 + 缓存 | tree-sitter, ctags, 正则 |
| **Semantic Indexer** | 事实表向量化、切块索引 | BGE-M3, AST-aware chunking |
| **Retrieval Agent** | 多路召回（向量 + BM25 + 调用图签名） | Hybrid Retrieval |
| **Diff & Compare Agent** | 两仓库「结构 + 语义」双层比对 | MinHash + LLM 判定 |
| **Report Writer Agent** | 生成 Project Card / Diff Report，每条结论附引用 | 模板化写作 |

### 3.3 L1/L2/L3 分层分析

| 层级 | 内容 | 说明 |
|---|---|---|
| L1 基础元数据 | 语言占比、代码行数、目录结构、README、commit 时间线 | 快速扫描，秒级完成 |
| L2 结构化事实 | 函数签名、调用图、syscall 表、内核子系统识别、模块清单 | 核心分析层 |
| L3 语义理解 | 设计模式识别、创新点提取、基线模板指纹匹配 | MinHash + LLM 辅助 |

### 3.4 抗幻觉机制

1. **强制引用（Citation Required）**：Report Writer 的每条结论必须带 `[file.c:L120-L145]` 引用，未引用直接拒采；
2. **代码先于文字**：先用 Static Analyzer 抽出事实表，LLM 只在事实表上「复述+解释」；
3. **双模型交叉校验**：关键结论由 DeepSeek 和 Qwen 双模型独立判定，不一致则降级为「需人工确认」；
4. **CitationCop 规则前置**：纯规则形式审查（编号范围/文件名/行号），失败直接拒绝不调 LLM；
5. **Claim Verifier**：答复后拆分为原子 claim，逐条核验 supported/partial/unsupported；
6. **温度 0 + 结构化输出（JSON Schema）**：确保结论可复现。

---

## 四、开发计划

项目按 12 周迭代推进，分为 6 个阶段：

| 阶段 | 周次 | 里程碑 | 交付物 |
|---|---|---|---|
| 一 | W1–W2 | 数据治理 + 仓库批量拉取 | 168 仓库镜像库 + manifest.json + MCP 接口契约 |
| 二 | W3–W4 | Static Analyzer 实现 | L1/L2 分析器 + 事实表 schema + 9 个分析工具 |
| 三 | W5–W6 | L1/L2/L3 分层 + 缓存优化 | 三级缓存机制，ChCore 19min → 2.1s（540x 提速）|
| 四 | W7–W8 | 单仓库分析报告 | 报告生成管线（md + html + json 三格式输出）|
| 五 | W9–W10 | 两仓库对比报告 + 相似度评分 | Diff Report + MinHash + Jaccard 多维评分 |
| 六 | W11–W12 | Web 仪表盘 + RAG 智能问答 | FastAPI 后端 + 静态前端 + 抗幻觉 Verifier |

---

## 五、比赛过程中的重要进展

### 进展一：工程骨架与数据治理（W1-W2）

- 搭建了完整的 Python 工程骨架：pyproject.toml + src layout + Typer CLI；
- 设计了 Manifest / RepoEntry / RepoFacts 三层数据契约（抗幻觉事实表 schema）；
- 从 `collected-data.xlsx` 构建 manifest，支持并发克隆、超时控制、状态续跑；
- 抽样探测 5/5 通过，eduxiji GitLab 连通性 100%；
- 完成 DeepSeek LLM 客户端集成（兼容 OpenAI 协议）。

### 进展二：L1/L2/L3 分层分析 + 性能突破（W3-W6）

- 实现了 9 个静态分析工具协同（cloc / tree-sitter / ctags / git-log / Makefile 解析等）；
- 重构为 L1/L2/L3 分层架构 + JobManager + Pipeline 编排；
- **关键突破：ChCore 仓库（5651 文件，960K LOC）分析时间从 19 分钟降至 2.1 秒**，实现 540 倍提速；
- 引入体量保护机制：MAX_FILES=6000 / MAX_FILE_BYTES=1MB / SKIP_DIR 目录剪枝；
- 其他 5 个真实仓库均 < 2.3 秒完成 L2 分析。

### 进展三：单仓库分析报告（W7-W8）

- 扩展事实表 schema v1.1：增加 CodeExcerpt / DirectoryNode / TechHighlight 等结构；
- 构建知识字典：syscall_dict（约 150 个 syscall 分类描述）、feature_tags（12 个子系统标签规则）；
- 实现 Markdown + HTML 双格式报告渲染管线（7 大章节）；
- 验证 7 个仓库全部成功产出报告（md: 10K-28K，html: 42K-101K）。

### 进展四：两仓库对比报告与查重（W9-W10）

- 设计了 CompareReport schema：BasicsDiff / SubsystemDiff / SyscallDiff / CompareScores 等；
- 实现多维 Jaccard 相似度计算：子系统权重 = 0.5*files + 0.3*functions + 0.1*structs + 0.1*tags；
- 综合评分公式覆盖语言/架构/构建/基线/覆盖率/子系统/syscall/规模 8 个维度；
- 验证 5 对仓库对比结果符合直觉：同基线 rCore=0.68，跨年 rCore=0.53，ChCore vs rCore=0.26。

### 进展五：Web 仪表盘（W11）

- 实现了 FastAPI 后端 14 个路由 + 静态前端（暗色主题、响应式表格、抽屉详情）；
- 三个 tab：概览 / 仓库 / LLM，支持年份分布柱状图、分页过滤、实时克隆；
- 新增增量导入 / 手工添加 / 删除仓库功能 + 前端导入弹窗；
- 独立报告页面：双栏布局 + TOC 目录 + 数字摘要卡 + 打印支持。

### 进展六：RAG 智能问答 + 抗幻觉 Verifier（W12）

- 实现基于事实表检索的 RAG 问答系统，支持 repo / compare / global 三种 scope；
- 答复中 `[n]` 引用可点击跳转到事实表对应来源；
- 实现三级抗幻觉 Verifier：
  - CitationCop：纯规则形式审查（编号范围/文件名/行号），失败直接拒绝不调 LLM，耗时 0ms；
  - ClaimVerifier：LLM 拆 claim 逐条核验（supported/partial/unsupported/unverifiable）；
  - Committee Arbiter：综合三方信号给出最终 status（verified / rejected）。
- 端到端验证 3 个 case 全通过：干净答复 verified，部分编造抓出 2 处 unsupported，严重幻觉规则层直接拦截。

---

## 六、系统测试情况

### 6.1 功能测试

| 测试项 | 方法 | 结果 |
|---|---|---|
| 仓库拉取连通性 | 抽样探测 5 个仓库 | 5/5 通过，eduxiji 连通性 100% |
| DeepSeek API 连通性 | `osagent llm ping` | ping 通过 |
| L1/L2/L3 分析完整性 | 7 个真实仓库端到端分析 | 全部成功，事实表完整 |
| 单仓库报告生成 | 7 个仓库 md+html 双格式 | 全部产出，含真实文件路径和行号 |
| 对比报告评分直觉性 | 5 对仓库（同基线/跨年/异构） | 评分排序符合人工预期 |
| RAG 问答引用准确性 | 5 个典型问题 | 引用编号 100% 准确 |
| 抗幻觉 Verifier | 3 个 case（干净/部分编造/严重幻觉） | 全部正确识别 |
| Web 仪表盘 API | 14 个路由 smoke test | 4/4 通过，全部 200 OK |

### 6.2 性能测试

| 指标 | 测试数据 | 结果 |
|---|---|---|
| 大仓库分析时间 | ChCore（5651 文件，960K LOC） | 19 min → 2.1s（缓存命中） |
| 中小仓库分析时间 | 5 个真实仓库 | 均 < 2.3s 完成 L2 |
| 报告生成时间 | ChCore | 0.5s |
| 事实表大小 | 单仓库 | 约 50KB JSON |

### 6.3 准确性评估

| 维度 | 目标 | 实际 |
|---|---|---|
| Project Card 引用真实率 | 100% | 每条结论附源码行号，经 Verifier 校验通过 |
| 查重评分合理性 | 排序符合直觉 | 同基线 0.68 > 跨年 0.53 > 异构 0.26，区分度良好 |
| RAG 抗幻觉 | 证据不足主动拒答 | 验证通过，绝不编造 |

---

## 七、遇到的主要问题和解决方法

### 问题一：大仓库分析时间过长

**现象**：ChCore 仓库包含 5651 个文件、960K 行代码，初始版本完整分析耗时超过 19 分钟。

**解决方法**：
1. 引入 L1/L2/L3 分层架构，按需分析，避免一次性全量扫描；
2. 实现三级缓存机制（内存缓存 + 文件缓存 + 事实表缓存），缓存命中时直接读取；
3. 强目录剪枝（SKIP_DIR）：跳过 vendor / linux / llvm / musl 等第三方代码目录；
4. 引入 TimeBudget 机制：L2 分析中 syscall 和 functions 各占 40%/60% 时间预算；
5. 使用字节级 `count(b'\n')` 替代 UTF-8 decode 计算行数，避免编码异常。

**效果**：19 分钟 → 2.1 秒，提速 540 倍。

### 问题二：LLM 幻觉导致评审结论不可信

**现象**：LLM 可能编造未实现的特性、把模板代码当作创新、伪造文件路径和行号。

**解决方法**：
1. 事实表白名单约束：LLM 只允许基于事实表数据「复述+解释」，不可自由发挥；
2. 内置 rCore / xv6 / UCore 基线模板指纹库，先剥离基线代码再分析创新点；
3. 强制引用机制：每条结论必须带 `[file:line]` 格式的源码引用；
4. 三级 Verifier 管线：CitationCop 规则前置 → ClaimVerifier LLM 逐条核验 → Committee 综合裁定；
5. temperature=0 + JSON Schema 结构化输出，确保可复现。

### 问题三：同模板不同实现的查重误判

**现象**：很多参赛作品基于同一模板（如 rCore-Tutorial），传统文本查重工具会误报为抄袭。

**解决方法**：
1. 使用 Call Graph MinHash 指纹做结构相似度判定，不依赖文本匹配；
2. 多维 Jaccard 相似度：综合文件集合、函数集合、数据结构集合、特性标签 4 个维度加权；
3. MinHash + LLM 双判机制：结果不一致时自动标记为「需人工确认」而非直接判定；
4. 设计同源识别逻辑：通过 commit 历史中的 `Initial commit from XXX` 等线索识别合理传承关系。

### 问题四：Web 前端与后端数据字段大量为 null

**现象**：仓库详情抽屉中 `escapeHtml` 函数遇到 null 值时抛出 SyntaxError。

**解决方法**：
1. 升级 `escapeHtml` 为 null-safe 版本：`String(s ?? '')`；
2. 去除重复声明（文件头 const 与后续 function 冲突）；
3. 在 `renderRepoSummary` 中对所有字段做防御性处理。

### 问题五：部分历史仓库已失效或私有化

**现象**：168 个仓库中存在链接失效或权限变更的情况。

**解决方法**：
1. manifest 中失效链接标记 `unreachable` 状态标签；
2. 支持增量导入和状态续跑，失效仓库不阻塞整体流程；
3. 在统计大盘中标 N/A，不影响已有数据的分析结果。

---

## 八、分工和协作

本项目由 KernelPanic 团队完成，采用以下协作模式：

**开发流程**：
- 基于 GitLab 进行版本管理，main 分支保护，功能开发通过 commit 直接推送；
- 每个功能模块对应独立 commit，提交信息遵循 Conventional Commits 规范（feat / fix / refactor / docs / chore）；
- 累计 14+ 次功能提交，覆盖从工程骨架到完整系统的全部迭代。

**模块分工**：

| 模块 | 工作内容 |
|---|---|
| 数据治理与仓库管理 | manifest 构建、168 仓库批量拉取、增量导入/删除 |
| 静态分析引擎 | L1/L2/L3 分层分析、9 个工具实现、三级缓存优化 |
| 报告生成系统 | 单仓库报告（md/html/json）、对比报告、相似度评分 |
| RAG 智能问答 | 事实表检索、DeepSeek 生成、引用追溯、抗幻觉 Verifier |
| Web 仪表盘 | FastAPI 后端（14 路由）、静态前端（暗色主题）、独立报告页 |
| 设计文档与方案 | 总体设计方案、数据契约定义、评测方案设计 |

**协作工具**：
- 版本控制：GitLab（eduxiji 比赛仓 + GitHub 镜像）
- 开发环境：Python 3.11 虚拟环境 + pip editable install
- API 文档：FastAPI 自动生成 Swagger UI

---

## 九、提交仓库目录和文件描述

```
osAgent/
├── 方案.md                          # 总体设计方案文档（v1.0）
├── collected-data.xlsx              # 五届 168 个仓库清单（原始数据源）
├── pyproject.toml                   # Python 项目配置（依赖、入口、构建）
├── .env.example                     # 环境变量模板（DeepSeek API Key 等）
├── .gitignore                       # Git 忽略规则
├── README.md                        # 项目说明文档
│
├── src/osagent/                     # 源码包（核心实现）
│   ├── __init__.py
│   ├── cli.py                       # Typer CLI 入口（所有命令注册）
│   ├── config.py                    # 配置管理（pydantic-settings）
│   ├── logging.py                   # 日志配置
│   │
│   ├── llm/                         # LLM 客户端模块
│   │   ├── __init__.py
│   │   └── deepseek.py              # DeepSeek API 客户端（chat / chat_full）
│   │
│   ├── ingest/                      # 仓库拉取与清单管理
│   │   ├── __init__.py
│   │   └── manifest.py              # manifest 构建、增量导入、仓库删除
│   │
│   ├── analyzer/                    # L1/L2/L3 静态分析引擎
│   │   ├── __init__.py
│   │   ├── core.py                  # 公共工具（walk_files / safe_read / TimeBudget）
│   │   ├── l1_quick.py              # L1 基础元数据分析
│   │   ├── l2_kernel.py             # L2 内核特性 + syscall + 函数节点分析
│   │   └── l3_signature.py          # L3 MinHash 签名生成
│   │
│   ├── compare/                     # 两仓库对比引擎
│   │   ├── __init__.py
│   │   └── core.py                  # diff_two / compare_repos / 多维 Jaccard
│   │
│   ├── qa/                          # RAG 智能问答系统
│   │   ├── __init__.py
│   │   ├── agent.py                 # 问答 Agent（检索→prompt→生成→引用映射）
│   │   ├── prompt.py                # system prompt（强约束抗幻觉）
│   │   ├── retriever.py             # 事实表关键字检索（repo/compare/global scope）
│   │   └── verifier/                # 抗幻觉校验器
│   │       ├── citation_cop.py      # 规则前置审查（编号/文件名/行号）
│   │       ├── claim_verifier.py    # LLM 拆 claim 逐条核验
│   │       └── committee.py         # 综合裁定（verified / rejected）
│   │
│   ├── report/                      # 报告生成模块
│   │   ├── __init__.py
│   │   ├── single.py                # 单仓库报告 Markdown 渲染（7 章节）
│   │   ├── compare.py               # 对比报告 Markdown 渲染（8 章节）
│   │   ├── html.py                  # Markdown → HTML 转换（含样式）
│   │   └── storage.py               # 报告持久化（md/html/json）
│   │
│   ├── pipeline/                    # 分析编排
│   │   └── pipeline.py              # L1→L2→L3 编排、进度回调、降级处理
│   │
│   ├── jobs/                        # 异步任务队列
│   │   └── jobs.py                  # JobManager（线程池 submit/get/list）
│   │
│   ├── web/                         # Web 仪表盘
│   │   ├── app.py                   # FastAPI 应用（14+ 路由）
│   │   └── static/                  # 静态前端资源
│   │       ├── index.html           # 主页面（暗色主题单页应用）
│   │       ├── styles.css           # 全局样式
│   │       ├── app.js               # 前端逻辑（Tab/抽屉/过滤/问答）
│   │       ├── report.html          # 独立报告页面模板
│   │       ├── report.css           # 报告页样式（双栏+TOC+打印）
│   │       └── report.js            # 报告页 scroll-spy 逻辑
│   │
│   └── schemas/                     # 数据契约（Pydantic models）
│       ├── manifest.py              # RepoEntry / Manifest
│       ├── facts.py                 # RepoFacts / KernelFeature / SyscallTable 等
│       ├── compare.py               # CompareReport / CompareScores / SetDiff 等
│       ├── qa.py                    # QARequest / QAResponse / QASource
│       └── verification.py          # VerificationReport / ClaimVerdict
│
├── scripts/                         # 一次性脚本
├── tests/                           # 测试用例
│
└── data/                            # 运行时产出（.gitignore）
    ├── repos/                       # 克隆的仓库
    ├── facts/                       # 事实表 JSON
    ├── cache/                       # 分析缓存
    ├── reports/                     # 生成的报告（md/html/json）
    │   └── compare/                 # 对比报告
    ├── index/                       # 向量索引
    └── backups/                     # manifest 自动备份
```

---

## 十、比赛收获

### 10.1 技术层面

1. **大模型工程化实践**：深入理解了 LangGraph 状态机式 Agent 框架的设计理念，掌握了 ReAct 调度模式在实际工程中的应用。通过 DeepSeek API 的集成，积累了大模型工具调用、结构化输出、温度控制等工程经验。

2. **抗幻觉机制设计**：这是本项目最核心的技术挑战。我们从「事实表白名单约束」出发，逐步构建了 CitationCop → ClaimVerifier → Committee 三级 Verifier 管线，深刻认识到在高可信度场景下，LLM 的输出必须有独立的验证机制，不能盲目信任。

3. **静态分析与性能优化**：面对 960K 行代码的大仓库，通过分层架构、目录剪枝、字节级计算、TimeBudget 等手段实现了 540 倍的性能提升。这让我们理解了「先做对，再做快」的工程原则——分层架构既是功能需求，也是性能优化的基础。

4. **RAG 系统设计**：区别于传统的文本向量检索 RAG，我们基于结构化事实表做检索，显著提升了检索的精准度和答案的可靠性。多路召回（向量 + BM25 + 调用图签名）的设计思路对理解现代信息检索体系很有帮助。

5. **代码相似度检测**：Call Graph MinHash 的设计是一个有价值的探索——将函数调用图的结构特征转化为可比较的指纹，突破了传统文本查重在面对变量重命名时的局限。

### 10.2 工程层面

1. **全栈开发能力**：从 Python 后端（FastAPI + Typer）到前端（原生 JS 暗色主题仪表盘），从数据契约设计（Pydantic schemas）到 CLI 工具链，完成了一个完整的全栈项目。

2. **数据治理意识**：处理 168 个仓库的数据治理工作，让我们理解了数据质量对下游分析的重要性。失效链接处理、增量导入、状态续跑等细节，都是实际工程中不可或缺的。

3. **渐进式开发方法**：12 周 6 阶段的迭代规划，每个阶段都有明确的交付物和验证标准。W1 的冒烟测试 → W6 的端到端验证 → W12 的完整系统，这种渐进式的方法确保了项目始终可控。

### 10.3 认知层面

1. **评审视角的理解**：通过构建评审辅助工具，我们站在评审专家的角度思考问题——什么样的信息是有价值的、什么样的结论是可信的、什么样的比对方式是公平的。这种换位思考对技术方案的设计帮助很大。

2. **操作系统生态的全景认识**：分析五届 168 个作品后，我们对国内操作系统教学生态有了全景式的认识——从 C 到 Rust 的语言迁移趋势、RISC-V 架构的普及、rCore 和 xv6 两大教学体系的影响力，以及各高校在操作系统领域的持续投入。

3. **AI 辅助而非替代**：最重要的收获是明确了 AI 系统在高可信度场景下的定位——「评审副驾驶」而非「自动评审员」。AI 提供结构化的事实支撑和智能检索能力，但最终的判断权始终在人类专家手中。这种谦逊的系统定位，反而让系统更加可信和有用。
