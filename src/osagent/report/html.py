"""HTML 报告：把 Markdown 渲染成自带样式的单文件 HTML。

- 使用 `markdown` 包做转换（fenced_code + tables + codehilite + toc）
- 内嵌一份精简 CSS（浅色风、卡片化），无外部依赖
- 输出单个 .html 文件，可直接双击在浏览器打开
"""
from __future__ import annotations

import html as _html

import markdown

_CSS = """
:root {
    --bg: #f7f9fc;
    --card-bg: #ffffff;
    --fg: #1f2937;
    --muted: #6b7280;
    --border: #e5e7eb;
    --accent: #2563eb;
    --accent-bg: #eff6ff;
    --code-bg: #f4f6fa;
    --tag-bg: #ede9fe;
    --tag-fg: #6d28d9;
}
* { box-sizing: border-box; }
body {
    margin: 0;
    padding: 2.5rem 1rem;
    background: var(--bg);
    color: var(--fg);
    font-family: -apple-system, BlinkMacSystemFont, "PingFang SC",
                 "Hiragino Sans GB", "Microsoft YaHei", "Helvetica Neue",
                 Arial, sans-serif;
    line-height: 1.65;
}
.container {
    max-width: 960px;
    margin: 0 auto;
    background: var(--card-bg);
    padding: 2.5rem 3rem;
    border-radius: 12px;
    box-shadow: 0 1px 3px rgba(0,0,0,.05), 0 1px 2px rgba(0,0,0,.03);
}
h1 {
    border-bottom: 2px solid var(--border);
    padding-bottom: 0.6rem;
    margin-top: 0;
    font-size: 1.9rem;
}
h2 {
    margin-top: 2.4rem;
    padding-left: 0.7rem;
    border-left: 4px solid var(--accent);
    font-size: 1.45rem;
}
h3 {
    margin-top: 1.8rem;
    color: var(--accent);
    font-size: 1.15rem;
}
h4 { margin-top: 1.2rem; color: var(--fg); }
p { margin: .6rem 0; }
hr { border: none; border-top: 1px solid var(--border); margin: 2rem 0; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }

table {
    border-collapse: collapse;
    margin: 1rem 0;
    width: 100%;
    font-size: 0.95rem;
}
table th, table td {
    border: 1px solid var(--border);
    padding: 0.5rem 0.8rem;
    text-align: left;
    vertical-align: top;
}
table th { background: var(--accent-bg); font-weight: 600; }
table tr:nth-child(even) td { background: #fafbfd; }

code {
    background: var(--code-bg);
    padding: 1px 6px;
    border-radius: 4px;
    font-family: "SF Mono", Menlo, Consolas, "Liberation Mono", monospace;
    font-size: 0.88em;
    color: #b91c1c;
}
pre {
    background: #0f172a;
    color: #e2e8f0;
    padding: 1rem 1.2rem;
    border-radius: 8px;
    overflow-x: auto;
    font-size: 0.85rem;
    line-height: 1.55;
}
pre code {
    background: transparent;
    color: inherit;
    padding: 0;
    font-size: inherit;
}
blockquote {
    border-left: 4px solid var(--tag-fg);
    background: var(--tag-bg);
    padding: 0.5rem 1rem;
    margin: 1rem 0;
    color: var(--fg);
    border-radius: 0 6px 6px 0;
}
ul { padding-left: 1.4rem; }
ul li { margin: 0.18rem 0; }
em { color: var(--muted); font-style: normal; }

/* code blocks: text (目录树) */
pre code.language-text {
    color: #cbd5e1;
}

/* highlight 语法颜色（codehilite 生成的 span） */
.codehilite .k  { color: #c4b5fd; }   /* keyword */
.codehilite .kd { color: #c4b5fd; }
.codehilite .kt { color: #93c5fd; }   /* type */
.codehilite .nf { color: #fbbf24; }   /* function name */
.codehilite .nb { color: #f472b6; }   /* builtin */
.codehilite .nc { color: #fbbf24; }   /* class name */
.codehilite .s, .codehilite .s1, .codehilite .s2 { color: #86efac; } /* string */
.codehilite .c, .codehilite .c1, .codehilite .cm { color: #94a3b8; font-style: italic; } /* comment */
.codehilite .mi, .codehilite .mf, .codehilite .mh { color: #fde68a; } /* number */
.codehilite .o  { color: #f9a8d4; }   /* operator */
.codehilite .p  { color: #e2e8f0; }

footer {
    margin-top: 3rem;
    padding-top: 1rem;
    border-top: 1px solid var(--border);
    color: var(--muted);
    font-size: 0.85rem;
    text-align: center;
}

/* compare 报告：进度条字符（█·）用等宽字体显示并去除底色 */
table td code {
    background: transparent;
    color: var(--accent);
    padding: 0;
    letter-spacing: -1px;
}
"""


def render_html(markdown_text: str, *, title: str = "分析报告") -> str:
    """把 Markdown 渲染为单文件 HTML。"""
    md = markdown.Markdown(
        extensions=[
            "fenced_code",
            "tables",
            "codehilite",
            "toc",
        ],
        extension_configs={
            "codehilite": {
                "guess_lang": False,
                "use_pygments": True,
                "noclasses": False,
            },
        },
    )
    body_html = md.convert(markdown_text)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<title>{_html.escape(title)}</title>
<style>
{_CSS}
</style>
</head>
<body>
<div class="container">
{body_html}
<footer>由 osAgent 生成 · L1+L2 静态分析 · 抗幻觉事实表驱动</footer>
</div>
</body>
</html>
"""
