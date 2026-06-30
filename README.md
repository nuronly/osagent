# osAgent

> 面向小型操作系统的分析比对智能体系统  
> 服务对象：全国大学生操作系统比赛（OS Kernel 赛道）评审与组委会  
> 设计方案见 [`方案.md`](方案.md)

## 项目状态

🚧 W1 进行中：数据治理 + 工程骨架

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

# 4. 试用 CLI
osagent --help
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
│   ├── llm/                         # LLM 客户端（DeepSeek 等）
│   ├── ingest/                      # 仓库拉取与清单
│   ├── analyzer/                    # 静态分析（MCP Server 雏形）
│   ├── agent/                       # Agent 编排（后续 LangGraph）
│   ├── retrieval/                   # RAG（后续）
│   ├── report/                      # 报告生成（后续）
│   ├── web/                         # FastAPI + 静态前端（极简仪表盘）
│   └── schemas/                     # 数据契约（事实表/Card/Report）
├── scripts/                         # 一次性脚本
├── tests/
└── data/                            # 运行时产出（gitignore）
    ├── repos/   facts/   cache/   reports/   index/
```

## 路线图

| 阶段 | 目标 | 状态 |
|---|---|---|
| W1–W2 | 数据治理 + 168 仓库批量拉取 + MCP 接口契约 | 🚧 |
| W3–W4 | Static Analyzer 实现 + 事实表落地 | ⏳ |
| W5–W6 | 向量索引 + 多路召回 | ⏳ |
| W7–W8 | Project Card 生成（抗幻觉） | ⏳ |
| W9–W10 | Diff Report + Call Graph MinHash | ⏳ |
| W11 | Web Dashboard + 演进大盘 | ⏳ |
| W12 | 评测、调参、文档 | ⏳ |

## 当前可用 CLI

```bash
osagent llm ping                  # 测试 DeepSeek API 连通性
osagent manifest build            # 由 collected-data.xlsx 生成 manifest.json
osagent manifest stats            # 查看年份/学校分布
osagent manifest show --year 2021 # 按年份查看仓库
osagent ingest probe -n 5         # 抽样拉取 N 个仓库测试连通性
osagent ingest clone-all          # 批量拉取所有仓库（耗时较长）
osagent analyzer list-tools       # 列出 MCP Static Analyzer 9 个工具契约
osagent serve                     # 启动 Web 仪表盘（默认 8765 端口）
```

## Web 仪表盘

```bash
osagent serve                     # 默认 http://127.0.0.1:8765
osagent serve --port 9000         # 换端口
osagent serve --reload            # 开发模式（改代码自动重载）
```

界面包含三个 tab：
- **概览**：数据集卡片、年份分布柱状图、每年仓库规模表
- **仓库**：按年份/状态/关键字过滤，点"查看"看详情、可单独触发克隆
- **LLM**：一键 ping DeepSeek，看模型 / token 用量

API 文档（Swagger UI）：`http://127.0.0.1:8765/docs`
