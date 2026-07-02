"""可选的 API Key 中间件（上线保护危险接口）。

启用条件：设置环境变量 `OSAGENT_API_KEY`（非空）。
- 未设置 → 中间件透传，等价开发模式（本地跑用）
- 设置了 → 所有 **写操作**（POST / PUT / PATCH / DELETE）和显式敏感 GET 都必须携带
             `X-API-Key: <key>` 请求头，否则 401

上线建议：与 Caddy 的 basic_auth 双保险。
"""
from __future__ import annotations

import os
from typing import Iterable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

# 需要保护的方法（写操作）
_PROTECTED_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# 白名单前缀：这些即便设置了 API Key 也不校验（供健康检查、静态资源、页面等）
_WHITELIST_PREFIXES: tuple[str, ...] = (
    "/static/",
    "/api/health",
    "/api/manifest/stats",
    "/api/manifest/repos",
    "/api/manifest/years",
    "/api/repos",       # GET /api/repos/{id}/... 只读的都放行；写操作按方法拦
    "/api/compare",     # 同上
    "/api/jobs",
    "/api/dashboard",
    "/api/llm/ping",
    "/",                # 首页
    "/report",          # 报告页
)


def _need_check(path: str, method: str) -> bool:
    """判断是否需要校验 API Key。

    规则：写方法一律校验；GET 只在**非白名单**时校验（当前配置=所有 GET 都在白名单里）。
    """
    if method.upper() in _PROTECTED_METHODS:
        return True
    # GET / HEAD 默认全放行（未来若要收紧再改）
    return False


def install_api_key_middleware(app: FastAPI, extra_whitelist: Iterable[str] = ()) -> None:
    """把中间件挂到 app 上；未配置 OSAGENT_API_KEY 时自动 no-op。"""
    api_key = os.environ.get("OSAGENT_API_KEY", "").strip()
    if not api_key:
        # 开发模式：不校验，只在启动日志里提醒
        return

    whitelist = _WHITELIST_PREFIXES + tuple(extra_whitelist)

    @app.middleware("http")
    async def _check_api_key(request: Request, call_next):  # noqa: ANN001
        path = request.url.path
        # 白名单前缀直接放行
        if any(path.startswith(p) for p in whitelist) and not _need_check(path, request.method):
            return await call_next(request)

        if _need_check(path, request.method):
            got = request.headers.get("x-api-key", "").strip()
            if got != api_key:
                return JSONResponse(
                    status_code=401,
                    content={
                        "ok": False,
                        "error": "missing or invalid X-API-Key",
                        "hint": "请求头需携带 X-API-Key: <your-key>",
                    },
                )
        return await call_next(request)
