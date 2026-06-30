/**
 * osAgent · 独立报告页面交互 (v0.7.2)
 *
 * 功能：
 *   1. Scroll-spy：滚动时高亮 TOC 当前对应章节
 *   2. 点击 TOC 平滑滚动到目标章节（CSS scroll-behavior 已配合 scroll-margin-top）
 */
(function () {
  "use strict";

  const tocLinks = Array.from(document.querySelectorAll(".toc a[href^='#']"));
  if (tocLinks.length === 0) return;

  // 建立 anchor -> link 映射
  const linkByHash = new Map();
  const targets = [];
  for (const link of tocLinks) {
    const hash = link.getAttribute("href");
    const id = decodeURIComponent(hash.slice(1));
    const el = document.getElementById(id);
    if (el) {
      linkByHash.set(hash, link);
      targets.push(el);
    }
  }
  if (targets.length === 0) return;

  let activeLink = null;
  const setActive = (link) => {
    if (activeLink === link) return;
    if (activeLink) activeLink.classList.remove("active");
    activeLink = link;
    if (link) {
      link.classList.add("active");
      // 让 active 项滚到 TOC 可视区中
      const toc = document.querySelector(".toc-inner");
      if (toc) {
        const lr = link.getBoundingClientRect();
        const tr = toc.getBoundingClientRect();
        if (lr.top < tr.top || lr.bottom > tr.bottom) {
          link.scrollIntoView({ block: "nearest", behavior: "smooth" });
        }
      }
    }
  };

  // 用 IntersectionObserver 监测哪些 heading 进入视口顶部
  // rootMargin 把视口顶部往下推 80px（对应 sticky header），底部抬高 70%
  // → 只在 heading 进入"屏幕上 1/3"区域时才算 active
  const visibleIds = new Set();
  const observer = new IntersectionObserver(
    (entries) => {
      for (const e of entries) {
        if (e.isIntersecting) visibleIds.add(e.target.id);
        else visibleIds.delete(e.target.id);
      }
      // 选最靠前的可见 heading 作 active
      let topMost = null;
      let topY = Infinity;
      for (const id of visibleIds) {
        const el = document.getElementById(id);
        if (!el) continue;
        const y = el.getBoundingClientRect().top;
        if (y < topY) {
          topY = y;
          topMost = el;
        }
      }
      if (topMost) {
        const link = linkByHash.get("#" + encodeURIComponent(topMost.id))
                  || linkByHash.get("#" + topMost.id);
        if (link) setActive(link);
      }
    },
    {
      // 上 80px：避开 sticky header；下 -65%：只关心屏幕上半区
      rootMargin: "-80px 0px -65% 0px",
      threshold: 0,
    }
  );
  targets.forEach((t) => observer.observe(t));

  // 兜底：scroll 到顶部 / 底部时手动校正
  window.addEventListener("scroll", () => {
    if (window.scrollY < 100) setActive(linkByHash.get("#" + targets[0].id));
    else if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 20) {
      const last = targets[targets.length - 1];
      const link = linkByHash.get("#" + last.id);
      if (link) setActive(link);
    }
  }, { passive: true });
})();
