# osAgent
演示视频和ppt：
https://pan.baidu.com/s/1uBHX08PdH665WkpLePishw?pwd=1111

> 面向小型操作系统的分析比对智能体系统
> 服务对象：全国大学生操作系统比赛（OS Kernel 赛道）评审与组委会
> 设计方案见 [`方案.md`](方案.md)

## 项目简介

osAgent 针对五届比赛共 **168 个参赛仓库**，提供：

1. **静态事实抽取**（L1/L2/L3 三级分析，全程可缓存，ChCore 从 19min → 2.1s）
2. **单仓库分析报告**（md + html + json）
3. **两仓库对比报告**（相似度评分 + 子系统集合 diff + 颜色化差异）
4. **RAG 智能问答**（基于事实表检索 + DeepSeek，强引用抗幻觉）
5. **Web 仪表盘**（FastAPI + 静态前端，端口 8765）+ 异步任务队列



## 快速开始

```bash
# 1. 创建虚拟环境
python3.11 -m venv .venv
source .venv/bin/activate

# 2. 安装（开发模式）
pip install -e ".[dev]"

# 3. 配置环境变量
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY

# 4. 启动 Web 仪表盘
osagent serve                     # http://127.0.0.1:8765
```

## 目录结构

```
osAgent/
├── 方案.md                          # 总体设计方案
├── collected-data.xlsx              # 五届 168 个仓库清单（原始数据）
├── pyproject.toml
├── .env.example
├── src/osagent/                     # 源码包
│   ├── cli.py                       # Typer CLI 入口
│   ├── config.py                    # 配置（pydantic-settings）
│   ├── logging.py
│   ├── llm/                         # LLM 客户端（DeepSeek chat / chat_full）
│   ├── ingest/                      # 仓库拉取与清单管理
│   ├── analyzer/                    # L1/L2/L3 静态分析 + 缓存
│   ├── compare/                     # 两仓库对比（相似度评分 + diff）
│   ├── qa/                          # RAG 问答（retriever + agent + prompt）
│   ├── report/                      # 报告生成（md / html / json）
│   ├── jobs/                        # 异步任务队列（JobManager）
│   ├── pipeline/                    # 分析编排
│   ├── web/                         # FastAPI + 静态前端
│   └── schemas/                     # 数据契约（QA / Card / Report / 事实表）
├── scripts/                         # 一次性脚本
├── tests/
└── data/                            # 运行时产出（gitignore）
    ├── repos/   facts/   cache/   reports/   index/
```
![img_1.png](img_1.png)
## 路线图

| 阶段 | 目标 | 状态 |
|---|---|---|
| W1–W2 | 数据治理 + 168 仓库批量拉取 + MCP 接口契约 | ✅ |
| W3–W4 | Static Analyzer 实现 + 事实表落地 | ✅ |
| W5–W6 | L1/L2/L3 分层 + 缓存（ChCore 19min → 2.1s） | ✅ |
| W7–W8 | 单仓库分析报告（md+html+json） | ✅ |
| W9–W10 | 两仓库对比报告 + 相似度评分 | ✅ |
| W11 | Web 仪表盘 + 异步任务队列 | ✅ |
| W12 | **RAG 智能问答（抗幻觉 + 引用追溯）** | ✅ |

## 当前可用 CLI

```bash
# 基础
osagent llm ping                          # 测试 DeepSeek API 连通性
osagent manifest build                    # 由 collected-data.xlsx 生成 manifest.json
osagent manifest stats                    # 查看年份/学校分布
osagent manifest show --year 2021         # 按年份查看仓库

# 数据采集
osagent ingest probe -n 5                 # 抽样拉取 N 个仓库测试连通性
osagent ingest clone-all                  # 批量拉取所有仓库（耗时较长）

# 分析与报告
osagent analyzer list-tools               # 列出 9 个静态分析工具
osagent analyze <repo_id>                 # 跑单仓库 L1/L2/L3 分析
osagent report <repo_id>                  # 生成单仓库报告
osagent compare <repo_a> <repo_b>         # 生成两仓库对比报告

# RAG 智能问答
osagent qa ask "ChCore 的进程调度怎么实现？" --repo 2024_024_ChCore
osagent qa ask "A 和 B 的内存管理有什么差异？" --compare A,B

# 服务
osagent serve                             # 启动 Web 仪表盘（默认 8765）
osagent serve --port 9000 --reload        # 换端口 + 开发模式
```

## Web 仪表盘

```bash
osagent serve                     # 默认 http://127.0.0.1:8765
```

界面功能：

- **概览**：数据集卡片、年份分布柱状图、每年仓库规模表
- **仓库列表**：按年份/状态/关键字过滤
- **仓库详情抽屉**：L1/L2/L3 事实表 + 一键生成报告（md/html/json）+ **聊天框（针对本仓库提问）**
- **两仓库对比抽屉**：相似度评分 + 集合 diff + 颜色化 bullets + **聊天框（跨仓库对比提问）**
- **LLM 面板**：一键 ping DeepSeek，看模型 / token 用量

聊天框特性：
- 推荐问题 chip 一键提问
- 答复中 `[n]` 引用可点击跳转到事实表对应来源
- 实时展示 prompt / completion token 用量
- 证据不足时主动回复 "暂无足够证据回答"，绝不编造

API 文档（Swagger UI）：`http://127.0.0.1:8765/docs`

## 关键 API

```http
POST /api/qa                # RAG 智能问答（scope = repo | compare | global）
POST /api/qa/preview        # 仅检索 + prompt 预览，不调 LLM
POST /api/analyze/{repo_id} # 异步触发分析任务
POST /api/report/{repo_id}  # 生成单仓库报告
POST /api/compare           # 生成两仓库对比报告
GET  /api/jobs/{job_id}     # 查询异步任务进度
```

## 仓库镜像

- GitHub: https://github.com/nuronly/osagent
- 比赛仓: https://gitlab.eduxiji.net/T2026102599910893/project3136859-388496

## 技术栈

- **Python 3.11** · **FastAPI** · **Typer** · **pydantic-settings**
- **DeepSeek** (LLM) · 自研 RAG 检索（基于结构化事实表）
- **Tree-sitter** / **ctags**（静态分析）· **MinHash**（代码相似度）
- 静态前端（原生 JS，无构建链）
