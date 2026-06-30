// osAgent 极简前端逻辑（无依赖、原生 ES）

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => Array.from(root.querySelectorAll(sel));

const fmtBytes = (n) => {
  if (!n) return "-";
  if (n < 1024) return n + " B";
  if (n < 1024 * 1024) return (n / 1024).toFixed(0) + " KB";
  return (n / 1024 / 1024).toFixed(1) + " MB";
};

async function api(path, opts = {}) {
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
    $("#repo-table tbody").innerHTML = `<tr><td colspan="8" class="muted">无结果</td></tr>`;
    return;
  }
  $("#repo-table tbody").innerHTML = rows
    .map(
      (r) => `<tr>
        <td>${r.year}</td>
        <td class="mono">${r.repo_id}</td>
        <td>${r.school}</td>
        <td>${r.team}</td>
        <td><span class="badge ${r.status}">${r.status}</span></td>
        <td>${r.file_count || "-"}</td>
        <td>${fmtBytes(r.size_bytes)}</td>
        <td><button class="btn ghost" data-repo="${r.repo_id}">查看</button></td>
      </tr>`
    )
    .join("");

  $$("#repo-table button[data-repo]").forEach((b) =>
    b.addEventListener("click", () => openDrawer(b.dataset.repo))
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
async function openDrawer(repoId) {
  currentRepoId = repoId;
  $("#drawer-title").textContent = repoId;
  $("#drawer-content").textContent = "加载中…";
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
    $("#drawer-content").textContent = JSON.stringify(data, null, 2);
  } catch (e) {
    $("#drawer-content").textContent = "错误：" + e.message;
  }
  // 顺手加载已有事实表（如果存在）
  loadFactsIfExists(repoId);
  // 顺手检查报告是否已存在
  refreshReportStatus(repoId);
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

// 默认加载概览
loadOverview();
