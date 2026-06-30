// osAgent 极简前端逻辑（无依赖、原生 ES）

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const fmtBytes = (n) => {
  if (!n) return "-";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
};

const fmtNum = (n) => (n == null ? "-" : Number(n).toLocaleString());

// escapeHtml 在文件底部已声明（function escapeHtml(s) ...），此处不再重复

// "2 天前" / "刚刚" / "3 小时前" — 输入 ISO string 或 null
function fmtRelativeTime(iso) {
  if (!iso) return "-";
  const t = new Date(iso).getTime();
  if (isNaN(t)) return "-";
  const diff = (Date.now() - t) / 1000;
  if (diff < 60) return "刚刚";
  if (diff < 3600) return `${Math.floor(diff / 60)} 分钟前`;
  if (diff < 86400) return `${Math.floor(diff / 3600)} 小时前`;
  if (diff < 86400 * 30) return `${Math.floor(diff / 86400)} 天前`;
  if (diff < 86400 * 365) return `${Math.floor(diff / 86400 / 30)} 个月前`;
  return `${Math.floor(diff / 86400 / 365)} 年前`;
}

const STATUS_META = {
  ok:          { icon: "✅", label: "已克隆", cls: "ok" },
  pending:     { icon: "⏸",  label: "待克隆", cls: "pending" },
  unreachable: { icon: "❌", label: "不可达", cls: "fail" },
  timeout:     { icon: "⏱",  label: "超时",   cls: "fail" },
  error:       { icon: "⚠️", label: "出错",   cls: "fail" },
};

async function copyToClipboard(text, srcBtn) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = document.createElement("textarea");
    ta.value = text; document.body.appendChild(ta); ta.select();
    document.execCommand("copy"); ta.remove();
  }
  if (srcBtn) {
    const old = srcBtn.textContent;
    srcBtn.textContent = "✓ 已复制";
    setTimeout(() => (srcBtn.textContent = old), 1200);
  }
}

async function api(path, opts = {}) {
  // 支持 body: object → 自动 JSON 序列化
  if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
    opts = { ...opts, body: JSON.stringify(opts.body) };
  }
  const resp = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...opts,
  });
  if (!resp.ok) {
    const text = await resp.text();
    throw new Error(`${resp.status}: ${text}`);
  }
  return resp.json();
}

// ===== 路由（顶栏切换） =====
function switchView(name) {
  $$(".nav-btn").forEach((b) =>
    b.classList.toggle("active", b.dataset.view === name)
  );
  $$(".view").forEach((v) =>
    v.classList.toggle("active", v.dataset.view === name)
  );
  if (name === "overview") loadOverview();
  if (name === "repos") loadRepos();
}

$$(".nav-btn").forEach((b) => b.addEventListener("click", () => switchView(b.dataset.view)));

// ===== 概览 =====
async function loadOverview() {
  try {
    const stats = await api("/api/manifest/stats");
    renderCards(stats);
    renderYearChart(stats.by_year);
    const yearly = await api("/api/dashboard/yearly");
    renderYearlyTable(yearly.rows);
  } catch (e) {
    $("#stats-cards").innerHTML = `<div class="card"><div class="card-label">错误</div><div class="card-value" style="font-size:14px;color:var(--danger)">${e.message}</div></div>`;
  }
}

function renderCards(s) {
  const okCount = (s.by_status && s.by_status.ok) || 0;
  const pendingCount = (s.by_status && s.by_status.pending) || 0;
  const failCount = ["unreachable", "timeout", "error"]
    .reduce((acc, k) => acc + ((s.by_status && s.by_status[k]) || 0), 0);
  const cards = [
    { label: "总仓库数", value: s.total, sub: `来自 ${s.source_xlsx.split("/").pop()}` },
    { label: "覆盖学校", value: s.schools_count, sub: "去重统计" },
    { label: "已克隆", value: okCount, sub: `${((okCount / s.total) * 100).toFixed(1)}%` },
    { label: "待处理", value: pendingCount },
    { label: "失败 / 失效", value: failCount, sub: failCount ? "见详情" : "无" },
  ];
  $("#stats-cards").innerHTML = cards
    .map(
      (c) => `<div class="card">
        <div class="card-label">${c.label}</div>
        <div class="card-value">${c.value}</div>
        ${c.sub ? `<div class="card-sub">${c.sub}</div>` : ""}
      </div>`
    )
    .join("");
}

function renderYearChart(byYear) {
  const entries = Object.entries(byYear).sort();
  const max = Math.max(...entries.map(([, v]) => v));
  $("#year-chart").innerHTML = entries
    .map(([year, count]) => {
      const heightPct = (count / max) * 100;
      return `<div class="bar-item">
        <span class="bar-value">${count}</span>
        <div class="bar" style="height:${heightPct}%" title="${year}: ${count}"></div>
        <span class="bar-label">${year}</span>
      </div>`;
    })
    .join("");
}

function renderYearlyTable(rows) {
  $("#yearly-table tbody").innerHTML = rows
    .map(
      (r) => `<tr>
        <td>${r.year}</td>
        <td>${r.total}</td>
        <td>${r.ok}</td>
        <td>${r.avg_files || "-"}</td>
        <td>${r.avg_size_kb || "-"}</td>
      </tr>`
    )
    .join("");
}

// 重建 manifest
$("#btn-rebuild").addEventListener("click", async () => {
  const btn = $("#btn-rebuild");
  const out = $("#rebuild-result");
  btn.disabled = true;
  out.textContent = "重建中…";
  try {
    const r = await api("/api/manifest/build", { method: "POST" });
    out.textContent = `已重建：${r.total} 条`;
    loadOverview();
  } catch (e) {
    out.textContent = "失败：" + e.message;
  } finally {
    btn.disabled = false;
  }
});

// ===== 仓库列表 =====
let repoState = { page: 1, pageSize: 30 };

async function loadRepos() {
  // 初始化年份过滤器
  if ($("#filter-year").options.length <= 1) {
    try {
      const stats = await api("/api/manifest/stats");
      const years = Object.keys(stats.by_year).sort();
      years.forEach((y) => {
        const o = document.createElement("option");
        o.value = y;
        o.textContent = y;
        $("#filter-year").appendChild(o);
      });
    } catch {}
  }
  await fetchAndRenderRepos();
}

async function fetchAndRenderRepos() {
  const params = new URLSearchParams();
  const year = $("#filter-year").value;
  const status = $("#filter-status").value;
  const q = $("#filter-q").value.trim();
  if (year) params.set("year", year);
  if (status) params.set("status", status);
  if (q) params.set("q", q);
  params.set("page", repoState.page);
  params.set("page_size", repoState.pageSize);

  try {
    const data = await api(`/api/manifest/repos?${params}`);
    $("#repo-total").textContent = `共 ${data.total} 条，第 ${data.page} 页`;
    $("#page-info").textContent = `第 ${data.page} 页 / 共 ${Math.max(1, Math.ceil(data.total / data.page_size))} 页`;
    renderRepoRows(data.items);
  } catch (e) {
    $("#repo-table tbody").innerHTML = `<tr><td colspan="8" style="color:var(--danger)">加载失败: ${e.message}</td></tr>`;
  }
}

function renderRepoRows(rows) {
  if (!rows.length) {
    $("#repo-table tbody").innerHTML = `<tr><td colspan="9" class="muted">无结果</td></tr>`;
    return;
  }
  $("#repo-table tbody").innerHTML = rows
    .map((r) => {
      const checked = compareState.selected.has(r.repo_id) ? "checked" : "";
      return `<tr>
        <td><input type="checkbox" class="cmp-pick" data-repo="${r.repo_id}" ${checked}></td>
        <td>${r.year}</td>
        <td class="mono">${r.repo_id}</td>
        <td>${r.school}</td>
        <td>${r.team}</td>
        <td><span class="badge ${r.status}">${r.status}</span></td>
        <td>${r.file_count || "-"}</td>
        <td>${fmtBytes(r.size_bytes)}</td>
        <td><button class="btn ghost" data-repo="${r.repo_id}">查看</button></td>
      </tr>`;
    })
    .join("");

  $$("#repo-table button[data-repo]").forEach((b) =>
    b.addEventListener("click", () => openDrawer(b.dataset.repo))
  );
  $$("#repo-table input.cmp-pick").forEach((cb) =>
    cb.addEventListener("change", () => onComparePickToggle(cb))
  );
}

$("#btn-search").addEventListener("click", () => {
  repoState.page = 1;
  fetchAndRenderRepos();
});
$("#filter-q").addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    repoState.page = 1;
    fetchAndRenderRepos();
  }
});
$("#btn-prev").addEventListener("click", () => {
  if (repoState.page > 1) {
    repoState.page--;
    fetchAndRenderRepos();
  }
});
$("#btn-next").addEventListener("click", () => {
  repoState.page++;
  fetchAndRenderRepos();
});

// ===== 抽屉（仓库详情） =====
let currentRepoId = null;

/**
 * 渲染仓库基本信息：身份头 + 链接 + 状态指标 + 进阶细节 + 错误条
 * 字段来自 GET /api/manifest/repos/{repo_id}
 */
function renderRepoSummary(d) {
  const meta = STATUS_META[d.status] || { icon: "·", label: d.status || "-", cls: "" };
  const shortHash = d.head_commit ? d.head_commit.slice(0, 7) : null;
  const hostShort = (d.repo_url || "").replace(/^https?:\/\//, "").replace(/\/$/, "");

  // 出错条件
  const errBanner = d.error_msg
    ? `<div class="error-banner">⚠️ ${escapeHtml(d.error_msg)}</div>`
    : "";

  // 本地实际存在 vs status 不一致
  const inconsistent = (d.local_exists === false && d.status === "ok")
    ? `<div class="warn-banner">⚠ status=ok 但本地路径不存在</div>` : "";

  // local_path 行（仅 ok / 有 local_path 时显示）
  const localRow = d.local_path
    ? `<div class="repo-info-row">
         <span class="k">本地路径</span>
         <code class="mono ellipsis" title="${escapeHtml(d.local_path)}">${escapeHtml(d.local_path)}</code>
         <button class="btn ghost mini" data-copy="${escapeHtml(d.local_path)}">📋</button>
       </div>` : "";

  // head_commit + branch 一行
  const commitRow = (shortHash || d.default_branch)
    ? `<div class="repo-info-row">
         <span class="k">HEAD</span>
         ${shortHash ? `<code class="mono">${shortHash}</code>` : '<span class="muted">-</span>'}
         ${d.default_branch ? `<span class="branch-tag">${escapeHtml(d.default_branch)}</span>` : ""}
       </div>` : "";

  $("#repo-summary").innerHTML = `
    <div class="repo-meta-head">
      <div class="repo-chips">
        <span class="chip year">${d.year ?? "-"}</span>
        <span class="chip">${escapeHtml(d.contest || "")}</span>
        <span class="chip">${escapeHtml(d.track || "")}</span>
      </div>
      <div class="repo-school">
        <span class="emoji">🏫</span>
        <b>${escapeHtml(d.school || "未知学校")}</b>
        <span class="sep">·</span>
        <span class="muted">队伍</span>
        <b>${escapeHtml(d.team || "未知队伍")}</b>
      </div>
      <div class="repo-url-row">
        <span class="emoji">🔗</span>
        <a class="repo-url" href="${escapeHtml(d.repo_url || "#")}" target="_blank" rel="noopener"
           title="${escapeHtml(d.repo_url || "")}">${escapeHtml(hostShort || "-")}</a>
        <button class="btn ghost mini" data-copy="${escapeHtml(d.repo_url || "")}" title="复制 URL">📋</button>
      </div>
    </div>

    ${errBanner}
    ${inconsistent}

    <div class="repo-stat-grid">
      <div class="repo-stat">
        <span class="label">状态</span>
        <span class="value"><span class="status-pill ${meta.cls}">${meta.icon} ${meta.label}</span></span>
      </div>
      <div class="repo-stat">
        <span class="label">文件数</span>
        <span class="value">${fmtNum(d.file_count)}</span>
      </div>
      <div class="repo-stat">
        <span class="label">大小</span>
        <span class="value">${fmtBytes(d.size_bytes)}</span>
      </div>
      <div class="repo-stat">
        <span class="label">克隆于</span>
        <span class="value" title="${escapeHtml(d.cloned_at || "")}">${fmtRelativeTime(d.cloned_at)}</span>
      </div>
    </div>

    ${commitRow}
    ${localRow}
  `;

  // 复制按钮绑定（事件委托）
  $$("#repo-summary [data-copy]").forEach((b) => {
    b.addEventListener("click", () => copyToClipboard(b.dataset.copy, b));
  });
}

async function openDrawer(repoId) {
  currentRepoId = repoId;
  $("#drawer-title").textContent = repoId;
  $("#repo-summary").innerHTML = '<div class="muted">加载中…</div>';
  $("#repo-raw").open = false;
  $("#drawer-content").textContent = "";
  $("#clone-result").textContent = "";
  $("#analyze-result").textContent = "";
  $("#facts-content").textContent = "";
  $("#analyze-progress").style.display = "none";
  $("#report-result").textContent = "";
  $("#report-frame").style.display = "none";
  $("#report-frame").src = "about:blank";
  $("#btn-open-html").disabled = true;
  $("#btn-open-md").disabled = true;
  $("#drawer").classList.add("open");
  try {
    const data = await api(`/api/manifest/repos/${encodeURIComponent(repoId)}`);
    renderRepoSummary(data);
    $("#drawer-content").textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    $("#repo-summary").innerHTML =
      `<div class="error-banner">加载失败：${escapeHtml(e.message)}</div>`;
    $("#drawer-content").textContent = "";
  }
  // 顺手加载已有事实表（如果存在）
  loadFactsIfExists(repoId);
  // 顺手检查报告是否已存在
  refreshReportStatus(repoId);
  // 清空 QA 历史
  qaResetHistory("qa-history");
  $("#qa-status").textContent = "";
  $("#qa-question").value = "";
}

async function refreshReportStatus(repoId) {
  try {
    const s = await api(`/api/repos/${encodeURIComponent(repoId)}/report/status`);
    $("#btn-open-html").disabled = !s.has_html;
    $("#btn-open-md").disabled = !s.has_md;
    if (s.has_html || s.has_md) {
      $("#report-result").textContent = "已存在历史报告";
    }
  } catch {}
}
async function loadFactsIfExists(repoId) {
  try {
    const f = await api(`/api/repos/${encodeURIComponent(repoId)}/facts/summary`);
    renderFacts(f);
    $("#analyze-result").textContent = `事实表已存在，提取于 ${new Date(f.extracted_at).toLocaleString()}`;
  } catch {
    // 没有就静默
  }
}
function renderFacts(f) {
  const text =
    `仓库: ${f.repo_id}\n` +
    `语言占比: ${f.languages.map(l => `${l.language}(${l.percent}%)`).join(", ")}\n` +
    `总 LOC: ${f.total_loc}\n` +
    `架构: ${f.arch.join(", ")}\n` +
    `构建: ${f.build}\n` +
    `基线模板: ${f.base_template || "—"}\n` +
    `子系统: ${f.subsystems.join(", ") || "—"}\n` +
    `syscall 数: ${f.syscall_count}\n` +
    `函数节点: ${f.function_node_count}\n` +
    `Git: ${f.dev_history.commits} commits / ${f.dev_history.contributors} contributors\n` +
    `时间跨度: ${f.dev_history.first || "?"} → ${f.dev_history.last || "?"}\n` +
    `\n${f.summary}`;
  $("#facts-content").textContent = text;
}
$("#drawer-close").addEventListener("click", () => $("#drawer").classList.remove("open"));

async function cloneCurrent(depth) {
  if (!currentRepoId) return;
  const out = $("#clone-result");
  out.textContent = "克隆中（可能需要 5–60 秒）…";
  try {
    const data = await api(
      `/api/repos/${encodeURIComponent(currentRepoId)}/clone?depth=${depth}`,
      { method: "POST" }
    );
    out.textContent = `状态：${data.status}`;
    $("#drawer-content").textContent = JSON.stringify(data, null, 2);
    fetchAndRenderRepos();
  } catch (e) {
    out.textContent = "失败：" + e.message;
  }
}
$("#btn-clone").addEventListener("click", () => cloneCurrent(1));
$("#btn-clone-full").addEventListener("click", () => cloneCurrent(0));

// ===== 静态分析（异步 + 进度轮询） =====
async function startAnalyze(force) {
  if (!currentRepoId) return;
  const level = $("#analyze-level").value;
  const out = $("#analyze-result");
  const bar = $("#analyze-bar");
  const msg = $("#analyze-msg");
  const wrap = $("#analyze-progress");

  $("#btn-analyze").disabled = true;
  $("#btn-analyze-force").disabled = true;
  out.textContent = "提交中…";
  wrap.style.display = "block";
  bar.style.width = "0%";
  msg.textContent = "准备";

  try {
    const url = `/api/repos/${encodeURIComponent(currentRepoId)}/analyze?level=${level}&force=${force ? "true" : "false"}`;
    const r = await api(url, { method: "POST" });
    if (r.cached) {
      out.textContent = "命中缓存，直接加载事实表";
      bar.style.width = "100%";
      msg.textContent = "完成（缓存）";
      await loadFactsIfExists(currentRepoId);
      return;
    }
    out.textContent = `任务已提交 (${r.job_id})`;
    await pollJob(r.job_id);
  } catch (e) {
    out.textContent = "失败：" + e.message;
  } finally {
    $("#btn-analyze").disabled = false;
    $("#btn-analyze-force").disabled = false;
  }
}

async function pollJob(jobId) {
  const bar = $("#analyze-bar");
  const msg = $("#analyze-msg");
  while (true) {
    await new Promise((r) => setTimeout(r, 600));
    const j = await api(`/api/jobs/${jobId}`);
    bar.style.width = `${j.progress.pct}%`;
    msg.textContent = `[${j.progress.stage}] ${j.progress.msg}`;
    if (j.status === "done") {
      $("#analyze-result").textContent = "✅ 分析完成";
      await loadFactsIfExists(currentRepoId);
      return;
    }
    if (j.status === "error") {
      $("#analyze-result").textContent = "❌ 失败";
      msg.textContent = (j.error || "").split("\n")[0];
      return;
    }
  }
}

$("#btn-analyze").addEventListener("click", () => startAnalyze(false));
$("#btn-analyze-force").addEventListener("click", () => startAnalyze(true));

// ===== 分析报告 =====
async function buildReport() {
  if (!currentRepoId) return;
  const btn = $("#btn-build-report");
  const out = $("#report-result");
  btn.disabled = true;
  out.textContent = "生成中（一般 < 2 秒）…";
  try {
    const r = await api(`/api/repos/${encodeURIComponent(currentRepoId)}/report`, { method: "POST" });
    const parts = [];
    if (r.md_chars != null) parts.push(`md ${(r.md_chars / 1024).toFixed(1)}KB`);
    if (r.html_chars != null) parts.push(`html ${(r.html_chars / 1024).toFixed(1)}KB`);
    out.textContent = "已生成：" + parts.join(" / ");
    $("#btn-open-html").disabled = false;
    $("#btn-open-md").disabled = false;
    // 自动加载到 iframe 预览
    openReportHtml();
  } catch (e) {
    out.textContent = "失败：" + e.message;
  } finally {
    btn.disabled = false;
  }
}

function openReportHtml() {
  if (!currentRepoId) return;
  const url = `/api/repos/${encodeURIComponent(currentRepoId)}/report.html?t=${Date.now()}`;
  const frame = $("#report-frame");
  frame.src = url;
  frame.style.display = "block";
}

function openReportMd() {
  if (!currentRepoId) return;
  window.open(`/api/repos/${encodeURIComponent(currentRepoId)}/report.md?t=${Date.now()}`, "_blank");
}

$("#btn-build-report").addEventListener("click", buildReport);
$("#btn-open-html").addEventListener("click", openReportHtml);
$("#btn-open-md").addEventListener("click", openReportMd);

// ===== LLM =====
$("#btn-ping").addEventListener("click", async () => {
  const out = $("#ping-output");
  const btn = $("#btn-ping");
  btn.disabled = true;
  out.textContent = "请求中…";
  try {
    const data = await api("/api/llm/ping");
    $("#llm-model").textContent = data.model || "?";
    out.textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    out.textContent = "失败：" + e.message;
  } finally {
    btn.disabled = false;
  }
});

// ===== 两仓库对比 =====
const compareState = {
  selected: new Set(), // 顺序无关
  order: [],           // 按勾选顺序保持 A→B
  currentA: null,
  currentB: null,
};

function onComparePickToggle(cb) {
  const id = cb.dataset.repo;
  if (cb.checked) {
    if (compareState.selected.size >= 2) {
      cb.checked = false;
      alert("最多只能选 2 个仓库进行对比。请先取消已选项。");
      return;
    }
    compareState.selected.add(id);
    compareState.order.push(id);
  } else {
    compareState.selected.delete(id);
    compareState.order = compareState.order.filter((x) => x !== id);
  }
  refreshCompareUI();
}

function refreshCompareUI() {
  const n = compareState.selected.size;
  const btn = $("#btn-compare-selected");
  btn.textContent = `🆚 对比所选（${n}/2）`;
  btn.disabled = n !== 2;
  $("#btn-clear-selection").disabled = n === 0;
}

function clearSelection() {
  compareState.selected.clear();
  compareState.order = [];
  $$("#repo-table input.cmp-pick").forEach((cb) => (cb.checked = false));
  refreshCompareUI();
}

$("#btn-clear-selection").addEventListener("click", clearSelection);

$("#btn-compare-selected").addEventListener("click", () => {
  if (compareState.order.length !== 2) return;
  const [a, b] = compareState.order;
  openCompareDrawer(a, b);
});

async function openCompareDrawer(a, b) {
  compareState.currentA = a;
  compareState.currentB = b;
  $("#compare-title").textContent = `对比：${a}  vs  ${b}`;
  $("#compare-result").textContent = "";
  $("#compare-scores").innerHTML = "";
  $("#compare-frame").style.display = "none";
  $("#compare-frame").src = "about:blank";
  $("#btn-open-compare-html").disabled = true;
  $("#btn-open-compare-md").disabled = true;
  $("#btn-open-compare-json").disabled = true;
  $("#compare-drawer").classList.add("open");
  // 清空 QA 历史
  qaResetHistory("qa-history-compare");
  $("#qa-status-compare").textContent = "";
  $("#qa-question-compare").value = "";

  // 查询是否已存在
  try {
    const params = `a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`;
    const s = await api(`/api/compare/status?${params}`);
    $("#btn-open-compare-html").disabled = !s.has_html;
    $("#btn-open-compare-md").disabled = !s.has_md;
    $("#btn-open-compare-json").disabled = !s.has_json;
    if (s.has_html) {
      $("#compare-result").textContent = "已存在历史报告，可直接打开";
      await loadCompareScores(a, b);
    } else if (!s.has_facts_a || !s.has_facts_b) {
      const miss = [];
      if (!s.has_facts_a) miss.push(a);
      if (!s.has_facts_b) miss.push(b);
      $("#compare-result").textContent = `⚠️ 以下仓库尚无事实表：${miss.join("、")}（请先到对应仓库详情运行分析）`;
    }
  } catch {}
}

$("#compare-close").addEventListener("click", () => $("#compare-drawer").classList.remove("open"));

async function buildCompare() {
  const a = compareState.currentA, b = compareState.currentB;
  if (!a || !b) return;
  const btn = $("#btn-build-compare");
  const out = $("#compare-result");
  btn.disabled = true;
  out.textContent = "生成中（一般 < 1 秒）…";
  try {
    const params = `a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`;
    const r = await api(`/api/compare?${params}`, { method: "POST" });
    out.textContent =
      `已生成：整体相似度 ${r.overall.toFixed(2)} · 子系统平均 ${r.subsystem_avg.toFixed(2)}` +
      (r.md_chars ? ` · md ${(r.md_chars/1024).toFixed(1)}KB` : "") +
      (r.html_chars ? ` / html ${(r.html_chars/1024).toFixed(1)}KB` : "");
    $("#btn-open-compare-html").disabled = false;
    $("#btn-open-compare-md").disabled = false;
    $("#btn-open-compare-json").disabled = false;
    await loadCompareScores(a, b);
    openCompareHtml();
  } catch (e) {
    out.textContent = "失败：" + e.message;
  } finally {
    btn.disabled = false;
  }
}

async function loadCompareScores(a, b) {
  try {
    const params = `a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`;
    const j = await api(`/api/compare.json?${params}`);
    const s = j.scores || {};
    const order = [
      ["overall", "整体相似度"],
      ["subsystem_avg", "子系统平均"],
      ["subsystem_coverage", "子系统覆盖"],
      ["syscall", "syscall"],
      ["base_template", "基线"],
      ["scale", "规模接近度"],
    ];
    $("#compare-scores").innerHTML = order
      .map(([k, label]) => {
        const v = (s[k] ?? 0);
        const pct = Math.round(v * 100);
        return `<div class="card">
          <div class="card-label">${label}</div>
          <div class="card-value">${v.toFixed(2)}</div>
          <div class="card-sub">${pct}%</div>
        </div>`;
      })
      .join("");
  } catch {}
}

function openCompareHtml() {
  const a = compareState.currentA, b = compareState.currentB;
  if (!a || !b) return;
  const params = `a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&t=${Date.now()}`;
  $("#compare-frame").src = `/api/compare.html?${params}`;
  $("#compare-frame").style.display = "block";
}

function openCompareMd() {
  const a = compareState.currentA, b = compareState.currentB;
  if (!a || !b) return;
  const params = `a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}&t=${Date.now()}`;
  window.open(`/api/compare.md?${params}`, "_blank");
}

function openCompareJson() {
  const a = compareState.currentA, b = compareState.currentB;
  if (!a || !b) return;
  const params = `a=${encodeURIComponent(a)}&b=${encodeURIComponent(b)}`;
  window.open(`/api/compare.json?${params}`, "_blank");
}

$("#btn-build-compare").addEventListener("click", buildCompare);
$("#btn-open-compare-html").addEventListener("click", openCompareHtml);
$("#btn-open-compare-md").addEventListener("click", openCompareMd);
$("#btn-open-compare-json").addEventListener("click", openCompareJson);

// ===== QA（检索增强问答） =====

function qaResetHistory(historyId) {
  const el = document.getElementById(historyId);
  if (el) el.innerHTML = "";
}

function escapeHtml(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
}

/** 把答复里的 [1] / [1,2] 渲染成可点击 chip，外层基础富文本（保留代码块 / inline code）。 */
function renderAnswer(text) {
  // 1) 先转义 + 还原 `code` / ```code blocks```
  let html = escapeHtml(text);
  // ```code``` 代码块
  html = html.replace(/```([\w-]*)\n([\s\S]*?)```/g, (_m, lang, code) => {
    return `<pre><code class="lang-${escapeHtml(lang)}">${code}</code></pre>`;
  });
  // 反引号 inline code
  html = html.replace(/`([^`\n]+)`/g, (_m, code) => `<code>${code}</code>`);
  // 2) 把 [1] / [1,2] 替换成 chip
  html = html.replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (_m, group) => {
    return group.split(",").map(n => {
      const idx = n.trim();
      return `<span class="qa-cite" data-cite="${idx}">[${idx}]</span>`;
    }).join("");
  });
  return html;
}

function renderSourceLine(idx, s) {
  let loc = "";
  if (s.file) {
    loc = `<span class="src-loc">${escapeHtml(s.file)}`;
    if (s.start_line) loc += `:${s.start_line}-${s.end_line || s.start_line}`;
    loc += "</span>";
  }
  const anchor = s.anchor ? `<span class="src-anchor">${escapeHtml(s.anchor)}</span>` : "";
  const repo = s.repo_id ? `<span class="badge">${escapeHtml(s.repo_id)}</span> ` : "";
  return `<li>[${idx}] ${repo}${escapeHtml(s.label || "")} ${anchor} ${loc} <span class="muted">(${escapeHtml(s.type)})</span></li>`;
}

function appendQaMsg(historyId, role, html, extra) {
  const wrap = document.getElementById(historyId);
  if (!wrap) return null;
  const div = document.createElement("div");
  div.className = `qa-msg ${role}`;
  div.innerHTML = `<div class="qa-role">${role}</div><div class="qa-body">${html}</div>${extra || ""}`;
  wrap.appendChild(div);
  wrap.scrollTop = wrap.scrollHeight;
  return div;
}

function buildVerificationBadge(v) {
  if (!v) return "";
  const statusMap = {
    verified: { icon: "✅", cls: "ok", label: "已核验" },
    partial:  { icon: "⚠️", cls: "warn", label: "部分支持" },
    rejected: { icon: "❌", cls: "bad", label: "建议拒收" },
    skipped:  { icon: "⚪", cls: "skip", label: "未核验" },
  };
  const meta = statusMap[v.status] || statusMap.skipped;
  const counts = (v.n_supported + v.n_partial + v.n_unsupported + v.n_unverifiable) > 0
    ? `<span class="qa-vcount">✓${v.n_supported} ⚠${v.n_partial} ✗${v.n_unsupported} ?${v.n_unverifiable}</span>`
    : "";

  const claimsHtml = (v.claims || []).map((c, i) => {
    const verdictIcon = {supported:"✅", partial:"⚠️", unsupported:"❌", unverifiable:"⚪"}[c.verdict] || "⚪";
    const cited = (c.cited_indices || []).length ? `[${c.cited_indices.join(",")}]` : "";
    const quote = c.evidence_quote ? `<div class="qa-vevidence">证据："${escapeHtml(c.evidence_quote)}"</div>` : "";
    return `
      <li class="qa-vclaim qa-v-${c.verdict}">
        <div class="qa-vhead">${verdictIcon} <span class="qa-vcite">${cited}</span> ${escapeHtml(c.claim)}</div>
        ${c.reason ? `<div class="qa-vreason">${escapeHtml(c.reason)}</div>` : ""}
        ${quote}
      </li>
    `;
  }).join("");

  const cchecks = (v.citation_checks || []).filter(c => !c.ok);
  const cchecksHtml = cchecks.length
    ? `<div class="qa-vcchecks"><b>形式审查问题：</b><ul>${cchecks.map(c => `<li>[${c.index}] ${escapeHtml(c.reason)}</li>`).join("")}</ul></div>`
    : "";

  const detail = `
    <details class="qa-vdetail">
      <summary class="qa-vsummary qa-vsummary-${meta.cls}">${meta.icon} ${escapeHtml(v.summary || meta.label)} ${counts}</summary>
      ${cchecksHtml}
      ${claimsHtml ? `<ol class="qa-vclaims">${claimsHtml}</ol>` : ""}
      ${v.verifier_model ? `<div class="qa-vmeta">verifier: ${escapeHtml(v.verifier_model)} · ${v.verifier_latency_ms}ms</div>` : ""}
    </details>
  `;
  return detail;
}

function buildSourcesBlock(resp) {
  let extra = "";
  // verifier badge 放在最前面，最显眼
  if (resp.verification) {
    extra += buildVerificationBadge(resp.verification);
  }
  if (resp.sources && resp.sources.length > 0) {
    const lis = resp.sources.map((s, i) => renderSourceLine(i + 1, s)).join("");
    extra += `<div class="qa-sources"><b>引用</b>（${resp.sources.length} 条）<ol>${lis}</ol></div>`;
  }
  if (resp.warnings && resp.warnings.length) {
    extra += `<div class="qa-warnings">⚠️ ${resp.warnings.map(escapeHtml).join(" · ")}</div>`;
  }
  if (resp.usage && resp.usage.total_tokens) {
    extra += `<div class="qa-meta">model=${escapeHtml(resp.model)} · prompt=${resp.usage.prompt_tokens} · completion=${resp.usage.completion_tokens} · total=${resp.usage.total_tokens} · ${resp.latency_ms}ms</div>`;
  }
  return extra;
}

async function qaAsk(scope, payload, historyId, statusId, btn) {
  appendQaMsg(historyId, "user", escapeHtml(payload.question));
  const thinking = appendQaMsg(historyId, "assistant",
    "<span class='qa-thinking'>思考中…（约 5–15 秒）</span>");
  document.getElementById(statusId).textContent = "正在调用 DeepSeek…";
  btn.disabled = true;
  try {
    const resp = await api("/api/qa", {
      method: "POST",
      body: { scope, ...payload },
    });
    // 移除"思考中"占位 → 重新渲染最终消息
    thinking.remove();
    const div = appendQaMsg(historyId, "assistant",
      renderAnswer(resp.answer || "（空）"),
      buildSourcesBlock(resp));
    document.getElementById(statusId).textContent = "";
    // 引用 chip 点击：滚到引用列表对应项并高亮
    div.querySelectorAll(".qa-cite").forEach(c => {
      c.addEventListener("click", () => {
        const idx = parseInt(c.dataset.cite, 10) - 1;
        const li = div.querySelectorAll(".qa-sources li")[idx];
        if (li) {
          li.scrollIntoView({ block: "center", behavior: "smooth" });
          li.style.background = "rgba(96,165,250,.25)";
          setTimeout(() => (li.style.background = ""), 1200);
        }
      });
    });
  } catch (e) {
    thinking.remove();
    appendQaMsg(historyId, "error", "❌ " + escapeHtml(e.message));
    document.getElementById(statusId).textContent = "请求失败";
  } finally {
    btn.disabled = false;
  }
}

// 仓库详情聊天框
function bindQaForRepo() {
  const btn = $("#btn-qa-ask");
  const textarea = $("#qa-question");
  if (!btn || !textarea) return;
  const submit = () => {
    const q = textarea.value.trim();
    if (!q || !currentRepoId) return;
    textarea.value = "";
    qaAsk("repo", { question: q, repo_id: currentRepoId },
      "qa-history", "qa-status", btn);
  };
  btn.addEventListener("click", submit);
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  });
  document.querySelectorAll("#drawer .qa-suggest .chip").forEach(c => {
    c.addEventListener("click", () => {
      textarea.value = c.dataset.q;
      submit();
    });
  });
}

// 对比抽屉聊天框
function bindQaForCompare() {
  const btn = $("#btn-qa-ask-compare");
  const textarea = $("#qa-question-compare");
  if (!btn || !textarea) return;
  const submit = () => {
    const q = textarea.value.trim();
    if (!q || !compareState.currentA || !compareState.currentB) return;
    textarea.value = "";
    qaAsk("compare", {
      question: q,
      repo_id_a: compareState.currentA,
      repo_id_b: compareState.currentB,
    }, "qa-history-compare", "qa-status-compare", btn);
  };
  btn.addEventListener("click", submit);
  textarea.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      submit();
    }
  });
  document.querySelectorAll("#compare-drawer .qa-suggest .chip").forEach(c => {
    c.addEventListener("click", () => {
      textarea.value = c.dataset.q;
      submit();
    });
  });
}

bindQaForRepo();
bindQaForCompare();

// ===========================================================
//  导入仓库 modal（v0.7：批量 Excel + 单仓库 + 删除确认）
// ===========================================================

const importModal = $("#import-modal");
const confirmModal = $("#confirm-modal");

function openModal(modal) {
  modal.setAttribute("aria-hidden", "false");
  modal.classList.add("open");
}
function closeModal(modal) {
  modal.setAttribute("aria-hidden", "true");
  modal.classList.remove("open");
}

// 通用：所有 [data-modal-close] 都能关闭它所在的 modal
document.addEventListener("click", (e) => {
  const t = e.target;
  if (t.matches("[data-modal-close]")) {
    const m = t.closest(".modal");
    if (m) closeModal(m);
  }
});

// 顶部按钮打开
$("#btn-open-import").addEventListener("click", () => {
  // 重置状态
  $("#import-file").value = "";
  $("#file-chosen").textContent = "尚未选择文件";
  $("#btn-import-confirm").disabled = true;
  $("#import-status").textContent = "";
  $("#import-report").hidden = true;
  $("#import-report").innerHTML = "";
  $("#add-repo-status").textContent = "";
  $("#add-repo-form").reset();
  openModal(importModal);
});

// tab 切换
$$(".tab-btn").forEach((b) => {
  b.addEventListener("click", () => {
    const target = b.dataset.tab;
    $$(".tab-btn").forEach((x) => x.classList.toggle("active", x === b));
    $$(".tab-pane").forEach((p) => {
      const on = p.dataset.tab === target;
      p.classList.toggle("active", on);
      p.hidden = !on;
    });
  });
});

// 文件选择 / 拖拽
const fileInput = $("#import-file");
const fileDrop = $("#file-drop");

fileInput.addEventListener("change", () => onFilePicked(fileInput.files[0]));
fileDrop.addEventListener("dragover", (e) => {
  e.preventDefault();
  fileDrop.classList.add("dragover");
});
fileDrop.addEventListener("dragleave", () => fileDrop.classList.remove("dragover"));
fileDrop.addEventListener("drop", (e) => {
  e.preventDefault();
  fileDrop.classList.remove("dragover");
  const f = e.dataTransfer.files[0];
  if (f) {
    // 把文件塞回 input 以便后续 form 提交
    const dt = new DataTransfer();
    dt.items.add(f);
    fileInput.files = dt.files;
    onFilePicked(f);
  }
});

function onFilePicked(file) {
  if (!file) return;
  $("#file-chosen").textContent = `已选择: ${file.name} (${fmtBytes(file.size)})`;
  // 选了文件之后，预览按钮可用，但确认按钮仍需先跑一次预览
  $("#btn-import-confirm").disabled = true;
  $("#import-report").hidden = true;
}

async function uploadXlsx(dryRun) {
  const file = fileInput.files[0];
  if (!file) {
    $("#import-status").textContent = "请先选择 xlsx 文件";
    return null;
  }
  const fd = new FormData();
  fd.append("file", file);
  fd.append("dry_run", dryRun ? "true" : "false");
  $("#import-status").textContent = dryRun ? "预览中…" : "导入中…";
  $("#btn-import-preview").disabled = true;
  $("#btn-import-confirm").disabled = true;
  try {
    const resp = await fetch("/api/manifest/import-xlsx", {
      method: "POST",
      body: fd,  // 让浏览器自动加 boundary
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.detail || `HTTP ${resp.status}`);
    }
    return data.report;
  } catch (e) {
    $("#import-status").textContent = "失败：" + e.message;
    return null;
  } finally {
    $("#btn-import-preview").disabled = false;
  }
}

function renderImportReport(report, isPreview) {
  const rows = report.rows || [];
  const errs = rows.filter((r) => r.action === "error");
  const skipReasons = {};
  rows.filter((r) => r.action === "skipped").forEach((r) => {
    skipReasons[r.reason] = (skipReasons[r.reason] || 0) + 1;
  });

  const reasonHtml = Object.entries(skipReasons)
    .map(([k, v]) => `<li><b>${v}</b> 条：${k}</li>`)
    .join("");

  const errHtml = errs.slice(0, 10)
    .map((r) => `<li>row ${r.row}: ${r.reason}</li>`)
    .join("");

  $("#import-report").innerHTML = `
    <div class="ir-summary">
      <div class="ir-stat ok"><span>新增</span><b>${report.added}</b></div>
      <div class="ir-stat warn"><span>跳过</span><b>${report.skipped}</b></div>
      <div class="ir-stat err"><span>错误</span><b>${report.errors}</b></div>
      <div class="ir-stat"><span>总行数</span><b>${report.total_rows}</b></div>
    </div>
    ${reasonHtml ? `<details open><summary>跳过原因分布</summary><ul>${reasonHtml}</ul></details>` : ""}
    ${errHtml ? `<details open><summary>错误明细（前 10 条）</summary><ul>${errHtml}</ul></details>` : ""}
    ${report.backup_path ? `<p class="muted">备份: ${report.backup_path}</p>` : ""}
  `;
  $("#import-report").hidden = false;

  if (isPreview) {
    if (report.added > 0) {
      $("#btn-import-confirm").disabled = false;
      $("#import-status").textContent = `预览完成：${report.added} 条将新增，点"确认导入"写盘`;
    } else {
      $("#btn-import-confirm").disabled = true;
      $("#import-status").textContent = "预览完成：没有可导入的新仓库";
    }
  } else {
    $("#btn-import-confirm").disabled = true;
    $("#import-status").textContent = `已导入 ${report.added} 条`;
  }
}

$("#btn-import-preview").addEventListener("click", async () => {
  const report = await uploadXlsx(true);
  if (report) renderImportReport(report, true);
});

$("#btn-import-confirm").addEventListener("click", async () => {
  const report = await uploadXlsx(false);
  if (report) {
    renderImportReport(report, false);
    // 同时刷新概览数据，便于用户看到变化
    loadOverview();
    // 强制让"仓库列表"年份过滤器下次重新拉
    $("#filter-year").innerHTML = '<option value="">全部年份</option>';
  }
});

// ---- 单仓库添加表单 ----
$("#add-repo-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const fd = new FormData(e.target);
  const body = {
    year: parseInt(fd.get("year"), 10),
    team: fd.get("team").trim(),
    school: fd.get("school").trim(),
    repo_url: fd.get("repo_url").trim(),
    contest: fd.get("contest").trim() || "操作系统赛",
    track: fd.get("track").trim() || "内核实现赛道",
  };
  $("#add-repo-status").textContent = "添加中…";
  try {
    const resp = await fetch("/api/manifest/add-repo", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      throw new Error(data.detail || `HTTP ${resp.status}`);
    }
    $("#add-repo-status").innerHTML =
      `<span style="color:var(--ok,#19a974)">✓ 已添加: ${data.entry.repo_id}</span>`;
    e.target.reset();
    loadOverview();
    $("#filter-year").innerHTML = '<option value="">全部年份</option>';
  } catch (err) {
    $("#add-repo-status").innerHTML =
      `<span style="color:var(--danger)">✗ ${err.message}</span>`;
  }
});

// ===========================================================
//  通用确认对话框 + 删除仓库
// ===========================================================

function askConfirm({ title = "确认", message = "", showPurge = false }) {
  return new Promise((resolve) => {
    $("#confirm-title").textContent = title;
    $("#confirm-message").textContent = message;
    $("#confirm-purge-wrap").hidden = !showPurge;
    $("#confirm-purge").checked = false;
    openModal(confirmModal);

    const cleanup = () => {
      $("#confirm-ok").removeEventListener("click", onOk);
      $("#confirm-cancel").removeEventListener("click", onCancel);
    };
    const onOk = () => {
      const purge = showPurge ? $("#confirm-purge").checked : false;
      cleanup();
      closeModal(confirmModal);
      resolve({ ok: true, purge });
    };
    const onCancel = () => {
      cleanup();
      closeModal(confirmModal);
      resolve({ ok: false, purge: false });
    };
    $("#confirm-ok").addEventListener("click", onOk);
    $("#confirm-cancel").addEventListener("click", onCancel);
  });
}

// 抽屉里的删除按钮
$("#btn-delete-repo").addEventListener("click", async () => {
  if (!currentRepoId) return;
  const decision = await askConfirm({
    title: "删除仓库",
    message: `确认从 manifest 删除 "${currentRepoId}" 吗？此操作会自动备份当前 manifest。`,
    showPurge: true,
  });
  if (!decision.ok) return;
  const out = $("#clone-result");
  out.textContent = "删除中…";
  try {
    const url = `/api/manifest/repos/${encodeURIComponent(currentRepoId)}?purge_data=${decision.purge}`;
    const resp = await fetch(url, { method: "DELETE" });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) throw new Error(data.detail || `HTTP ${resp.status}`);
    out.innerHTML = `<span style="color:var(--ok,#19a974)">✓ 已删除${decision.purge ? `（清理 ${data.result.purged_paths.length} 个文件 / 目录）` : ""}</span>`;
    // 关抽屉 + 刷列表
    $("#drawer").classList.remove("open");
    currentRepoId = null;
    fetchAndRenderRepos();
    loadOverview();
    $("#filter-year").innerHTML = '<option value="">全部年份</option>';
  } catch (e) {
    out.innerHTML = `<span style="color:var(--danger)">✗ ${e.message}</span>`;
  }
});

// 默认加载概览
loadOverview();
