"""检索增强问答（RAG）。

入口：``qa.ask(req) -> QAResponse``。

子模块：
- prompt.py    : system prompt + user prompt 模板
- retriever.py : 基于事实表 / CompareReport 的关键字检索
- agent.py     : retrieve → prompt → LLM → 解析引用
"""
from .agent import ask
from .retriever import retrieve

__all__ = ["ask", "retrieve"]
