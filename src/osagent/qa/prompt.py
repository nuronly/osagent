"""QA prompt 模板（中文，抗幻觉硬约束）。

设计要点：
- system prompt 强制只能基于上下文回答；不知道就说不知道；
- 要求每一条结论后挂引用编号 [1] / [2]；
- 输出统一用紧凑 Markdown，前端无须二次解析。
"""
from __future__ import annotations

from ..schemas.qa import QAContextItem, QARequest

SYSTEM_PROMPT = """你是 osAgent 的内核分析问答助手，专长于操作系统内核源码分析。

【绝对规则】
1. 你的回答只能基于下方"上下文"中提供的事实，不得编造、不得脑补、不得引入上下文之外的知识。
2. 若上下文不足以回答，必须明确回复："根据现有事实表，暂无足够证据回答该问题"，并简述缺哪些信息。
3. 你的每一条结论后必须挂引用编号 [n]，n 对应上下文条目的编号；多个引用写作 [1][3]。
4. 不要复述原文整段，要做归纳；保留关键函数名/数据结构名/syscall 名等技术词原样不译。
5. 默认用简体中文回答，技术名词保留英文（如 buddy / VMA / capability 等）。

【回答风格】
- 总分结构：先一句话直接回答，再分点展开。
- 涉及代码位置时，引用编号即可，不要在正文里重复 file:line。
- 不要用客套话开头（"好的""当然"）；不要 emoji。
"""


def build_user_prompt(req: QARequest, items: list[QAContextItem]) -> str:
    """把检索到的上下文 + 问题组装成 user message。"""
    lines: list[str] = []
    scope_hint = {
        "repo": f"针对仓库 `{req.repo_id}` 的单仓库问答",
        "compare": f"针对仓库 `{req.repo_id_a}` 与 `{req.repo_id_b}` 的对比问答",
        "global": "针对全部仓库的全局问答",
    }[req.scope]
    lines.append(f"# 任务\n{scope_hint}。请基于下方上下文回答用户问题。\n")

    lines.append("# 上下文（编号即引用编号）")
    if not items:
        lines.append("（空）")
    else:
        for idx, it in enumerate(items, start=1):
            lines.append(f"\n## [{idx}] {it.title}")
            lines.append(it.body.strip())

    lines.append("\n# 用户问题")
    lines.append(req.question.strip())

    lines.append(
        "\n# 输出要求\n"
        "- 第一句话直接回答，然后分点展开；\n"
        "- 每条结论后挂 [n] 引用，n 必须出现在上方上下文编号范围内；\n"
        "- 若证据不足，明确说不知道。"
    )
    return "\n".join(lines)


def build_messages(req: QARequest, items: list[QAContextItem]) -> list[dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": build_user_prompt(req, items)},
    ]
