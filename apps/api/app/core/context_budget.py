from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ContextProfile:
    name: str
    label: str
    description: str
    budget_tokens: int
    recent_window: int
    max_characters: int
    max_char_state_attrs: int
    max_speech_samples: int
    max_unavailable: int
    max_world_assets: int
    max_pits: int
    max_pit_clues: int
    rag_top_k: int
    arc_char_budget: int
    volume_fold_arcs: int


CONTEXT_PROFILES: dict[str, ContextProfile] = {
    "quality": ContextProfile(
        name="quality",
        label="效果优先 (200K+)",
        description="面向 200K+ 大上下文模型：近 10 话详窗、最多 40 角色 / 40 伏笔 / 16 路召回，64K 动态预算",
        budget_tokens=64000,
        recent_window=10,
        max_characters=40,
        max_char_state_attrs=12,
        max_speech_samples=5,
        max_unavailable=40,
        max_world_assets=45,
        max_pits=40,
        max_pit_clues=6,
        rag_top_k=16,
        arc_char_budget=620,
        volume_fold_arcs=20,
    ),
    "balanced": ContextProfile(
        name="balanced",
        label="均衡模式 (128K)",
        description="兼顾连续性与成本：近 5 话详窗、最多 22 角色 / 22 伏笔 / 10 路召回，28K 动态预算",
        budget_tokens=28000,
        recent_window=5,
        max_characters=22,
        max_char_state_attrs=8,
        max_speech_samples=3,
        max_unavailable=24,
        max_world_assets=25,
        max_pits=22,
        max_pit_clues=4,
        rag_top_k=10,
        arc_char_budget=420,
        volume_fold_arcs=15,
    ),
    "cost": ContextProfile(
        name="cost",
        label="成本优先 (32K / 省 Token)",
        description="适配小窗口模型或控成本：近 3 话详窗、最多 12 角色 / 12 伏笔 / 5 路召回，10K 硬预算",
        budget_tokens=10000,
        recent_window=3,
        max_characters=12,
        max_char_state_attrs=5,
        max_speech_samples=2,
        max_unavailable=12,
        max_world_assets=12,
        max_pits=12,
        max_pit_clues=3,
        rag_top_k=5,
        arc_char_budget=260,
        volume_fold_arcs=8,
    ),
}

_CJK_RE = re.compile(r"[\u3000-\u9fff\uf900-\ufaff]")
_ARC_HEADER_RE = re.compile(r"^【第([^~】]+)~([^】]+)话篇章纪要】(.*)$")


def resolve_context_profile(name: str | None, default_name: str = "quality") -> ContextProfile:
    key = (name or default_name or "quality").strip().lower()
    if key in CONTEXT_PROFILES:
        return CONTEXT_PROFILES[key]
    return CONTEXT_PROFILES.get(default_name, CONTEXT_PROFILES["quality"])


def estimate_tokens(value: Any) -> int:
    """Fast, tokenizer-calibrated token estimator for mixed CJK + English JSON/Markdown prompts."""
    if value is None:
        return 0
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False, default=str)
    if not text:
        return 0
    cjk_count = len(_CJK_RE.findall(text))
    other_count = len(text) - cjk_count
    # Calibrated against GPT-4o / Claude / GLM tokenizers: ~0.75 tok/CJK char, ~0.28 tok/ASCII char
    return max(1, int(cjk_count * 0.75 + other_count * 0.28))


def _condense_inline(text: str, max_chars: int) -> str:
    clean = " ".join((text or "").split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max(1, max_chars - 1)].rstrip("，。；、 ") + "…"


def fold_arc_lines_into_volumes(
    long_summary: str,
    *,
    arcs_per_volume: int = 5,
    keep_recent_arcs: int = 4,
    max_chars_per_volume: int = 460,
) -> tuple[str, bool, int]:
    """Fold older 10-episode arc blocks into 50-episode Volume Digests while keeping recent arcs intact."""
    lines = [ln.strip() for ln in (long_summary or "").splitlines() if ln.strip()]
    arc_lines = [ln for ln in lines if ln.startswith("【第") and "篇章纪要】" in ln]
    if len(arc_lines) <= keep_recent_arcs + arcs_per_volume - 1:
        return long_summary, False, 0

    older = lines[:-keep_recent_arcs] if keep_recent_arcs > 0 else lines
    recent = lines[-keep_recent_arcs:] if keep_recent_arcs > 0 else []

    folded_lines: list[str] = []
    volumes_created = 0
    for i in range(0, len(older), arcs_per_volume):
        chunk = older[i : i + arcs_per_volume]
        if len(chunk) < 2:
            folded_lines.extend(chunk)
            continue

        start_ep = None
        end_ep = None
        snippets: list[str] = []
        per_item = max(55, max_chars_per_volume // len(chunk))
        for ln in chunk:
            m = _ARC_HEADER_RE.match(ln)
            if m:
                if start_ep is None:
                    start_ep = m.group(1)
                end_ep = m.group(2)
                snippets.append(_condense_inline(m.group(3), per_item))
            else:
                snippets.append(_condense_inline(ln, per_item))
        body = _condense_inline(" / ".join(s for s in snippets if s), max_chars_per_volume)
        if start_ep and end_ep:
            folded_lines.append(f"【第{start_ep}~{end_ep}话大卷纪要】{body}")
        else:
            folded_lines.append(f"【早期篇章合集】{body}")
        volumes_created += 1

    folded_lines.extend(recent)
    return "\n".join(folded_lines), volumes_created > 0, volumes_created


def _measure_sections(context: dict) -> dict[str, int]:
    sb = context.get("story_bible") or {}
    # Only main_plot + art_style from story_bible are rendered into the prompt
    # (arc_summaries and discovered_rules are already measured via long_summary & canon_rules)
    sb_for_prompt = {
        "main_plot": sb.get("main_plot"),
        "art_style": sb.get("art_style"),
    } if isinstance(sb, dict) else sb
    return {
        "story_bible": estimate_tokens(sb_for_prompt),
        "canon_rules": estimate_tokens(context.get("canon_rules")),
        "long_summary": estimate_tokens(context.get("long_summary")),
        "previous_bridge": estimate_tokens(context.get("previous_bridge")),
        "recent_episodes": estimate_tokens(context.get("recent_episodes")),
        "character_dossier": estimate_tokens(context.get("character_dossier")),
        "unavailable_characters": estimate_tokens(context.get("unavailable_characters")),
        "world_assets": estimate_tokens(context.get("world_assets")),
        "active_pits": estimate_tokens(context.get("active_pits")),
        "rag_memories": estimate_tokens(context.get("rag_memories")),
    }


def apply_dynamic_context_budget(
    context: dict,
    *,
    profile: ContextProfile,
    max_context_tokens: int | None = None,
) -> dict:
    """Enforce a hard dynamic token budget by trimming lower-priority sections in strict order.

    Sacred Tier-0 anchors (`story_bible.main_plot`, `previous_bridge`, and at least the latest 2
    `recent_episodes` + top characters/high-priority pits) are preserved first.
    """
    budget = max(2500, int(max_context_tokens or profile.budget_tokens))
    trim_actions: list[str] = []

    before_sections = _measure_sections(context)
    tokens_before = sum(before_sections.values())

    def current_total() -> int:
        return sum(_measure_sections(context).values())

    # Step 0: Proactive volume folding when arc count exceeds profile threshold (150~500+ eps)
    arc_lines = [ln for ln in (context.get("long_summary") or "").splitlines() if "篇章纪要】" in ln]
    if len(arc_lines) > profile.volume_fold_arcs:
        folded, did_fold, vol_cnt = fold_arc_lines_into_volumes(
            context.get("long_summary") or "",
            arcs_per_volume=5,
            keep_recent_arcs=4,
            max_chars_per_volume=max(320, profile.arc_char_budget),
        )
        if did_fold:
            context["long_summary"] = folded
            trim_actions.append(
                f"早期长程史料超过 {profile.volume_fold_arcs} 个篇章块，已按每 50 话自动折叠为 {vol_cnt} 卷大卷纪要"
            )

    # Step 1: Trim low-ranked world_assets if over budget
    if current_total() > budget and len(context.get("world_assets") or []) > min(8, profile.max_world_assets):
        wa = context["world_assets"]
        target_len = min(profile.max_world_assets, max(6, len(wa) // 2))
        context["world_assets"] = wa[:target_len]
        trim_actions.append(f"道具与场景资产由 {len(wa)} 项动态裁剪至 Top {target_len} 项")

    # Step 2: Trim secondary rag_memories tail
    if current_total() > budget and len(context.get("rag_memories") or []) > min(4, profile.rag_top_k):
        rm = context["rag_memories"]
        target_len = min(profile.rag_top_k, max(4, len(rm) // 2))
        context["rag_memories"] = rm[:target_len]
        trim_actions.append(f"跨话 RRF 记忆召回由 {len(rm)} 条裁剪至高相关 Top {target_len} 条")

    # Step 3: Trim lower-priority active_pits (protecting P8+ core mysteries)
    if current_total() > budget and len(context.get("active_pits") or []) > 8:
        pits = context["active_pits"]
        high_prio = [p for p in pits if (p.get("priority") or 0) >= 8]
        target_len = min(profile.max_pits, max(8, len(high_prio)))
        if target_len < len(pits):
            context["active_pits"] = pits[:target_len]
            trim_actions.append(f"活跃伏笔由 {len(pits)} 条裁剪至 {target_len} 条（保留全部 P8+ 主线伏笔）")

    # Step 4: Trim lower-ranked character_dossier tail + tighten verbose descriptions
    if current_total() > budget and len(context.get("character_dossier") or []) > 8:
        chars = context["character_dossier"]
        target_len = min(profile.max_characters, max(8, len(chars) // 2))
        trimmed_chars = []
        for c in chars[:target_len]:
            c_copy = dict(c)
            if len(c_copy.get("description") or "") > 160:
                c_copy["description"] = _condense_inline(c_copy["description"], 160)
            if len(c_copy.get("current_state") or "") > 180:
                c_copy["current_state"] = _condense_inline(c_copy["current_state"], 180)
            c_copy["speech_samples"] = (c_copy.get("speech_samples") or [])[-profile.max_speech_samples :]
            trimmed_chars.append(c_copy)
        context["character_dossier"] = trimmed_chars
        trim_actions.append(f"角色档案由 {len(chars)} 人裁剪至 Top {target_len} 人并压缩冗长状态与外貌描述")

    # Step 5: Fold long_summary into 50-ep volumes if still over budget
    if current_total() > budget and context.get("long_summary"):
        folded, did_fold, vol_cnt = fold_arc_lines_into_volumes(
            context["long_summary"],
            arcs_per_volume=5,
            keep_recent_arcs=3,
            max_chars_per_volume=340,
        )
        if did_fold:
            context["long_summary"] = folded
            trim_actions.append(f"触发预算保护：将早期篇章进一步折叠为 {vol_cnt} 卷大卷纪要")

    # Step 6: Trim unavailable_characters tail if huge
    if current_total() > budget and len(context.get("unavailable_characters") or []) > min(12, profile.max_unavailable):
        unavail = context["unavailable_characters"]
        keep_n = min(12, profile.max_unavailable)
        kept = unavail[:keep_n]
        omitted = len(unavail) - len(kept)
        context["unavailable_characters"] = kept
        trim_actions.append(f"已故/失踪硬锁定名单保留高相关 Top {keep_n} 人（其余 {omitted} 名次要退场角色已折叠）")

    # Step 7: Shrink recent_episodes window (always keeping at least latest 2 episodes!)
    if current_total() > budget and len(context.get("recent_episodes") or []) > 2:
        rec = context["recent_episodes"]
        context["recent_episodes"] = rec[-2:]
        trim_actions.append(f"近期详尽窗口由 {len(rec)} 话收紧至最近 2 话（保留上话完整桥接）")

    # Step 8: Secondary tightening pass for extreme long-running payloads on small-budget profiles
    if current_total() > budget:
        if len(context.get("world_assets") or []) > 5:
            context["world_assets"] = context["world_assets"][:5]
        if len(context.get("character_dossier") or []) > 8:
            context["character_dossier"] = [
                {
                    **c,
                    "description": _condense_inline(c.get("description") or "", 100),
                    "current_state": _condense_inline(c.get("current_state") or "", 110),
                    "speech_samples": (c.get("speech_samples") or [])[-1:],
                }
                for c in context["character_dossier"][:8]
            ]
        if context.get("active_pits"):
            high_only = [p for p in context["active_pits"] if (p.get("priority") or 0) >= 8]
            kept_pits = high_only if len(high_only) >= 6 else context["active_pits"][: max(6, len(high_only))]
            context["active_pits"] = [
                {
                    **p,
                    "description": _condense_inline(p.get("description") or "", 100),
                    "clues": (p.get("clues") or [])[-2:],
                }
                for p in kept_pits
            ]
        if context.get("recent_episodes"):
            context["recent_episodes"] = [
                {
                    **ep,
                    "summary": _condense_inline(ep.get("summary") or "", 260),
                    "events": (ep.get("events") or [])[:4],
                }
                for ep in context["recent_episodes"]
            ]
        trim_actions.append("启动紧凑预算二级收紧：压缩单条摘要、角色描述与低优伏笔详情以严格守住 Token 上限")

    # Step 9: Last-resort soft char budget on long_summary while preserving Chapter 1 & latest tail
    if current_total() > budget and len(context.get("long_summary") or "") > 1000:
        ls = context["long_summary"]
        excess_tokens = current_total() - budget
        shrink_chars = int(excess_tokens / 0.72) + 200
        target_chars = max(800, len(ls) - shrink_chars)
        if target_chars < len(ls):
            head_len = int(target_chars * 0.45)
            tail_len = target_chars - head_len
            context["long_summary"] = (
                ls[:head_len].rstrip()
                + "\n…（中段常规过渡篇章已按预算自动折叠，关键回调请参考下方 RAG 召回与伏笔账本）…\n"
                + ls[-tail_len:].lstrip()
            )
            trim_actions.append(f"长程历史摘要按首尾保真策略压缩至约 {target_chars} 字（保留开篇与近期脉络）")

    after_sections = _measure_sections(context)
    tokens_after = sum(after_sections.values())

    context["context_budget"] = {
        "profile": profile.name,
        "profile_label": profile.label,
        "budget_tokens": budget,
        "estimated_tokens_before": tokens_before,
        "estimated_tokens_after": tokens_after,
        "utilization_pct": round((tokens_after / budget) * 100.0, 1) if budget else 0.0,
        "trimmed": len(trim_actions) > 0,
        "trim_actions": trim_actions,
        "section_tokens": after_sections,
    }
    return context
