"""QA（检索增强问答）数据契约。

设计原则（抗幻觉三板斧）：
1. **强证据**：所有 LLM 回答必须挂 ``QASource``，前端能跳到事实表字段或源码行；
2. **受控上下文**：``QAContextItem`` 按 token 预算装配，避免无意义灌满；
3. **可核验**：``QAResponse`` 透传 model / usage / warnings，方便事后审计。

scope 三类：
- ``repo``    单仓库问答（用本仓 facts 的子系统/syscall/技术亮点）
- ``compare`` 两仓库对比问答（直接喂 CompareReport）
- ``global``  跨全部仓库（第二期，先预留 schema）
"""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from .verification import VerificationReport


QAScope = Literal["repo", "compare", "global"]


# ---------------- 输入 ----------------

class QARequest(BaseModel):
    """前端发起的一次问答。"""

    question: str = Field(min_length=1, max_length=2000)
    scope: QAScope = "repo"

    # scope=repo
    repo_id: str | None = None

    # scope=compare
    repo_id_a: str | None = None
    repo_id_b: str | None = None

    # 控制项（给前端调参留口）
    max_context_items: int = 12
    max_tokens: int = 800
    temperature: float = 0.1


# ---------------- 证据 / 上下文 ----------------

QASourceType = Literal[
    "facts_field",    # facts 里某个字段（如 basics.base_template）
    "subsystem",      # 某个 KernelFeature（feature=memory）
    "syscall",        # 某个 syscall（name=sys_fork）
    "code",           # 源文件片段（file:start-end）
    "compare_field",  # CompareReport 里某个字段
    "tech_highlight", # 某个技术亮点
    "dev_history",    # 开发历史
]


class QASource(BaseModel):
    """单条证据。前端按 type 决定跳转方式。"""

    type: QASourceType
    repo_id: str | None = None
    label: str                       # 引用列表里的短文本
    detail: str = ""                 # 一句话补充

    # type=code / type=subsystem 带 evidence 时可用
    file: str | None = None
    start_line: int | None = None
    end_line: int | None = None

    # 可选 anchor：facts 字段路径或 CompareReport 字段路径
    anchor: str | None = None


class QAContextItem(BaseModel):
    """喂给 LLM 的一段上下文。"""

    title: str          # prompt 里的小标题，如 "[子系统:memory @ chcore]"
    body: str           # 已格式化好的文本（带 `- key: value` 列表）
    source: QASource    # 这段上下文对应的引用
    tokens_est: int = 0  # 粗估 token 数（按 chars/2）


# ---------------- 输出 ----------------

class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class QAResponse(BaseModel):
    schema_version: str = "1.0"
    asked_at: datetime = Field(default_factory=datetime.now)

    question: str
    scope: QAScope
    repo_ids: list[str] = Field(default_factory=list)

    answer: str

    # 引用 = 真正被 LLM "用到" 的子集（按引用编号去重后回传）
    sources: list[QASource] = Field(default_factory=list)
    context_items_used: int = 0
    context_chars: int = 0

    model: str = ""
    usage: TokenUsage = Field(default_factory=TokenUsage)
    latency_ms: int = 0

    # 风险提示：证据稀疏 / scope 不匹配 / LLM 失败回退到模板等
    warnings: list[str] = Field(default_factory=list)

    # 抗幻觉核验报告（verifier 输出）。可能为 None（关闭 / 无答复）
    verification: VerificationReport | None = None
