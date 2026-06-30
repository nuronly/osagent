"""diff 引擎：把两份 RepoFacts 转成一份 CompareReport。

设计要点：
- 集合 diff：Jaccard = |A∩B| / |A∪B|
- 子系统相似度：files 主导 + 关键函数 + 数据结构 + 标签 加权
- 整体相似度：8 个子分加权
"""
from __future__ import annotations

from datetime import datetime
from typing import Iterable

from ..analyzer import has_facts, load_facts
from ..analyzer.syscall_dict import CATEGORY_LABEL_ZH, CATEGORY_ORDER
from ..ingest import load_manifest
from ..schemas import KernelFeature, RepoFacts
from ..schemas.compare import (
    BasicsDiff,
    CompareReport,
    CompareScores,
    DevDiff,
    RepoMeta,
    SetDiff,
    SubsystemDiff,
    SyscallDiff,
)

# 与 report/single.py 保持一致
_FEATURE_ORDER: list[tuple[str, str]] = [
    ("boot",       "引导与初始化系统"),
    ("memory",     "内存管理系统"),
    ("process",    "进程与线程管理系统"),
    ("scheduler",  "任务调度系统"),
    ("syscall",    "异常与系统调用系统"),
    ("trap",       "陷入与中断系统"),
    ("filesystem", "文件系统"),
    ("driver",     "设备驱动"),
    ("virtio",     "VirtIO 子系统"),
    ("ipc",        "进程间通信与同步"),
    ("signal",     "信号机制"),
    ("smp",        "多核支持"),
    ("network",    "网络协议栈"),
]


# =================== 基础工具 ===================

def _set_diff(a: Iterable[str], b: Iterable[str]) -> SetDiff:
    """两个字符串集合的 diff + Jaccard。空集 vs 空集 → jaccard=1.0；空 vs 非空 → 0.0。"""
    sa = set(x for x in a if x)
    sb = set(x for x in b if x)
    if not sa and not sb:
        return SetDiff(jaccard=1.0)
    inter = sa & sb
    union = sa | sb
    return SetDiff(
        a_only=sorted(sa - sb),
        b_only=sorted(sb - sa),
        common=sorted(inter),
        jaccard=round(len(inter) / len(union), 4) if union else 0.0,
    )


def _scale_similarity(a: int, b: int) -> float:
    """规模接近度：min/max ∈ (0,1]；两个都 0 → 1.0；其中一个 0 → 0.0。"""
    if a == 0 and b == 0:
        return 1.0
    if a == 0 or b == 0:
        return 0.0
    lo, hi = min(a, b), max(a, b)
    return round(lo / hi, 4)


# =================== 各段 diff ===================

def _diff_basics(fa: RepoFacts, fb: RepoFacts) -> BasicsDiff:
    a, b = fa.basics, fb.basics
    lang_a = a.languages[0].language if a.languages else ""
    lang_b = b.languages[0].language if b.languages else ""
    return BasicsDiff(
        language_main_a=lang_a,
        language_main_b=lang_b,
        language_set=_set_diff(
            [s.language for s in a.languages],
            [s.language for s in b.languages],
        ),
        arch_a=list(a.arch),
        arch_b=list(b.arch),
        arch_set=_set_diff(a.arch, b.arch),
        build_a=a.build.kind,
        build_b=b.build.kind,
        base_template_a=a.base_template or "",
        base_template_b=b.base_template or "",
        base_template_same=(a.base_template or "") == (b.base_template or "") and bool(a.base_template),
        total_loc_a=a.total_loc,
        total_loc_b=b.total_loc,
        loc_ratio=_scale_similarity(a.total_loc, b.total_loc),
    )


def _subsystem_similarity(d: SubsystemDiff) -> float:
    """子系统综合相似度。仅一边有 → 强罚到 0.0；两边都缺 → 不出现在结果中。"""
    if not (d.present_a and d.present_b):
        return 0.0
    # 权重：files 主导（同子系统的命中文件最具代表性）
    return round(
        0.5 * d.files_diff.jaccard
        + 0.3 * d.key_functions_diff.jaccard
        + 0.1 * d.data_structures_diff.jaccard
        + 0.1 * d.feature_tags_diff.jaccard,
        4,
    )


def _build_subsystem_note(d: SubsystemDiff) -> str:
    """生成确定性文字小结。"""
    if d.present_a and not d.present_b:
        return f"仅 A 实现了 {d.label_zh}（{d.file_count_a} 个文件）"
    if d.present_b and not d.present_a:
        return f"仅 B 实现了 {d.label_zh}（{d.file_count_b} 个文件）"
    if not (d.present_a or d.present_b):
        return f"双方均未实现 {d.label_zh}"
    fj = d.files_diff.jaccard
    if fj >= 0.7:
        return f"双方实现高度相似（文件 Jaccard={fj:.2f}），可能同基线"
    if fj >= 0.3:
        return f"双方实现部分重叠（文件 Jaccard={fj:.2f}），但有各自扩展"
    return f"双方均实现 {d.label_zh}，但文件组织差异较大（Jaccard={fj:.2f}）"


def _diff_one_subsystem(
    feat_key: str,
    label_zh: str,
    kfa: KernelFeature | None,
    kfb: KernelFeature | None,
) -> SubsystemDiff:
    present_a = kfa is not None
    present_b = kfb is not None
    d = SubsystemDiff(
        feature=feat_key,
        label_zh=label_zh,
        present_a=present_a,
        present_b=present_b,
        files_diff=_set_diff(kfa.files if kfa else [], kfb.files if kfb else []),
        key_functions_diff=_set_diff(
            kfa.key_functions if kfa else [], kfb.key_functions if kfb else []
        ),
        data_structures_diff=_set_diff(
            kfa.data_structures if kfa else [], kfb.data_structures if kfb else []
        ),
        feature_tags_diff=_set_diff(
            kfa.feature_tags if kfa else [], kfb.feature_tags if kfb else []
        ),
        file_count_a=len(kfa.files) if kfa else 0,
        file_count_b=len(kfb.files) if kfb else 0,
    )
    d.similarity = _subsystem_similarity(d)
    d.note = _build_subsystem_note(d)
    return d


def _diff_subsystems(fa: RepoFacts, fb: RepoFacts) -> list[SubsystemDiff]:
    by_a = {x.feature: x for x in fa.kernel_features}
    by_b = {x.feature: x for x in fb.kernel_features}
    out: list[SubsystemDiff] = []
    seen: set[str] = set()
    for key, label in _FEATURE_ORDER:
        seen.add(key)
        if key not in by_a and key not in by_b:
            continue  # 双方都没有的就不出现，避免噪音
        out.append(_diff_one_subsystem(key, label, by_a.get(key), by_b.get(key)))
    # 兜底：处理未列在 _FEATURE_ORDER 里的 feature 值（如 "other"）
    for key in sorted(set(by_a) | set(by_b)):
        if key not in seen:
            out.append(_diff_one_subsystem(key, key, by_a.get(key), by_b.get(key)))
    return out


def _diff_syscalls(fa: RepoFacts, fb: RepoFacts) -> SyscallDiff:
    sa = fa.syscalls
    sb = fb.syscalls
    names_a = [s.name for s in sa.items if s.name]
    names_b = [s.name for s in sb.items if s.name]
    names_diff = _set_diff(names_a, names_b)
    return SyscallDiff(
        count_a=sa.count,
        count_b=sb.count,
        by_category_a=dict(sa.by_category),
        by_category_b=dict(sb.by_category),
        names_diff=names_diff,
        common_count=len(names_diff.common),
    )


def _diff_dev(fa: RepoFacts, fb: RepoFacts) -> DevDiff:
    da, db = fa.dev_history, fb.dev_history

    def _ymd(dt) -> str:
        return dt.strftime("%Y-%m-%d") if dt else ""

    return DevDiff(
        commits_a=da.commits_total,
        commits_b=db.commits_total,
        contributors_a=da.contributors_total,
        contributors_b=db.contributors_total,
        first_a=_ymd(da.first_commit_at),
        first_b=_ymd(db.first_commit_at),
        last_a=_ymd(da.last_commit_at),
        last_b=_ymd(db.last_commit_at),
    )


# =================== 整体打分 ===================

def _compute_scores(
    basics: BasicsDiff,
    subs: list[SubsystemDiff],
    sysc: SyscallDiff,
) -> CompareScores:
    # 子系统层：覆盖度 + 共有子系统的平均 similarity
    feats_a = {s.feature for s in subs if s.present_a}
    feats_b = {s.feature for s in subs if s.present_b}
    inter = feats_a & feats_b
    union = feats_a | feats_b
    coverage = round(len(inter) / len(union), 4) if union else 1.0
    common_subs = [s for s in subs if s.present_a and s.present_b]
    sub_avg = round(
        sum(s.similarity for s in common_subs) / len(common_subs), 4
    ) if common_subs else 0.0

    base_same = 1.0 if basics.base_template_same else 0.0
    build_same = 1.0 if basics.build_a == basics.build_b and basics.build_a else 0.0

    scores = CompareScores(
        language=basics.language_set.jaccard,
        architecture=basics.arch_set.jaccard,
        build=build_same,
        base_template=base_same,
        subsystem_coverage=coverage,
        subsystem_avg=sub_avg,
        syscall=sysc.names_diff.jaccard,
        scale=basics.loc_ratio,
    )
    # 加权：子系统是主体，syscall + 基线次之，其他做辅助
    overall = (
        0.10 * scores.language
        + 0.05 * scores.architecture
        + 0.05 * scores.build
        + 0.10 * scores.base_template
        + 0.15 * scores.subsystem_coverage
        + 0.30 * scores.subsystem_avg
        + 0.20 * scores.syscall
        + 0.05 * scores.scale
    )
    scores.overall = round(overall, 4)
    return scores


# =================== 摘要 bullets ===================

def _build_highlights_and_differences(
    a_meta: RepoMeta,
    b_meta: RepoMeta,
    basics: BasicsDiff,
    subs: list[SubsystemDiff],
    sysc: SyscallDiff,
    scores: CompareScores,
) -> tuple[list[str], list[str]]:
    hl: list[str] = []
    df: list[str] = []

    # 整体定性
    ov = scores.overall
    if ov >= 0.7:
        hl.append(f"整体相似度高达 {ov:.2f}，两份实现疑似同源或同基线深度改造")
    elif ov >= 0.4:
        hl.append(f"整体相似度 {ov:.2f}，存在显著公共结构但各自有差异")
    else:
        hl.append(f"整体相似度仅 {ov:.2f}，两份实现整体差异较大")

    # 基线
    if basics.base_template_same:
        hl.append(f"双方基线模板一致：`{basics.base_template_a}`")
    elif basics.base_template_a or basics.base_template_b:
        df.append(
            f"基线不同：A=`{basics.base_template_a or '未识别'}` vs "
            f"B=`{basics.base_template_b or '未识别'}`"
        )

    # 语言 / 架构
    if basics.language_main_a == basics.language_main_b and basics.language_main_a:
        hl.append(f"主语言相同：`{basics.language_main_a}`")
    else:
        df.append(
            f"主语言不同：A=`{basics.language_main_a or '未知'}` vs "
            f"B=`{basics.language_main_b or '未知'}`"
        )
    if basics.arch_set.a_only or basics.arch_set.b_only:
        df.append(
            f"目标架构差异：A=`{','.join(basics.arch_a) or '?'}` vs "
            f"B=`{','.join(basics.arch_b) or '?'}`"
        )

    # 规模
    if basics.loc_ratio >= 0.8:
        hl.append(
            f"代码规模相近：A={basics.total_loc_a:,} LOC vs B={basics.total_loc_b:,} LOC"
            f"（接近度 {basics.loc_ratio:.2f}）"
        )
    else:
        df.append(
            f"代码规模差异大：A={basics.total_loc_a:,} LOC vs B={basics.total_loc_b:,} LOC"
            f"（接近度 {basics.loc_ratio:.2f}）"
        )

    # 子系统覆盖
    only_a = [s.label_zh for s in subs if s.present_a and not s.present_b]
    only_b = [s.label_zh for s in subs if s.present_b and not s.present_a]
    if only_a:
        df.append(f"A 独有的子系统：{('、'.join(only_a))}")
    if only_b:
        df.append(f"B 独有的子系统：{('、'.join(only_b))}")

    # 高/低相似子系统
    common_subs = [s for s in subs if s.present_a and s.present_b]
    top_sim = sorted(common_subs, key=lambda s: s.similarity, reverse=True)[:3]
    low_sim = sorted(common_subs, key=lambda s: s.similarity)[:3]
    for s in top_sim:
        if s.similarity >= 0.6:
            hl.append(f"`{s.label_zh}` 实现高度相似（相似度 {s.similarity:.2f}）")
    for s in low_sim:
        if s.similarity < 0.2 and s not in top_sim:
            df.append(f"`{s.label_zh}` 实现差异显著（相似度 {s.similarity:.2f}）")

    # syscall
    if sysc.count_a and sysc.count_b:
        if sysc.names_diff.jaccard >= 0.6:
            hl.append(
                f"syscall 集合高度重合：共有 {sysc.common_count} 个"
                f"（Jaccard={sysc.names_diff.jaccard:.2f}）"
            )
        elif sysc.names_diff.jaccard < 0.2:
            df.append(
                f"syscall 设计差异大：A={sysc.count_a} 个 / B={sysc.count_b} 个，"
                f"共有仅 {sysc.common_count} 个（Jaccard={sysc.names_diff.jaccard:.2f}）"
            )

    return hl, df


# =================== 顶层 ===================

def diff_two(
    facts_a: RepoFacts,
    facts_b: RepoFacts,
    *,
    meta_a: RepoMeta,
    meta_b: RepoMeta,
) -> CompareReport:
    basics = _diff_basics(facts_a, facts_b)
    subs = _diff_subsystems(facts_a, facts_b)
    sysc = _diff_syscalls(facts_a, facts_b)
    dev = _diff_dev(facts_a, facts_b)
    scores = _compute_scores(basics, subs, sysc)
    hl, df = _build_highlights_and_differences(meta_a, meta_b, basics, subs, sysc, scores)
    return CompareReport(
        generated_at=datetime.now(),
        a=meta_a,
        b=meta_b,
        basics=basics,
        subsystems=subs,
        syscalls=sysc,
        dev=dev,
        scores=scores,
        highlights=hl,
        differences=df,
    )


def _build_meta(repo_id: str, facts: RepoFacts) -> RepoMeta:
    """从 manifest 抽元信息，不强依赖（manifest 不存在则只给 repo_id）。"""
    try:
        m = load_manifest()
        entry = next((r for r in m.repos if r.repo_id == repo_id), None)
    except Exception:
        entry = None
    if entry is None:
        return RepoMeta(repo_id=repo_id, head_commit=facts.head_commit)
    return RepoMeta(
        repo_id=repo_id,
        team=entry.team,
        school=entry.school,
        year=entry.year,
        repo_url=entry.repo_url,
        head_commit=facts.head_commit,
    )


def compare_repos(repo_id_a: str, repo_id_b: str) -> CompareReport:
    """一站式：从 repo_id 加载事实表 + manifest 元 → CompareReport。"""
    if repo_id_a == repo_id_b:
        raise ValueError(f"两侧 repo_id 相同: {repo_id_a}")
    for rid in (repo_id_a, repo_id_b):
        if not has_facts(rid):
            raise FileNotFoundError(
                f"事实表不存在: {rid}. 请先 `osagent analyzer analyze {rid}`"
            )
    fa = load_facts(repo_id_a)
    fb = load_facts(repo_id_b)
    return diff_two(
        fa, fb,
        meta_a=_build_meta(repo_id_a, fa),
        meta_b=_build_meta(repo_id_b, fb),
    )
