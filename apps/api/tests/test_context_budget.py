from __future__ import annotations

from app.core.context_budget import (
    CONTEXT_PROFILES,
    apply_dynamic_context_budget,
    estimate_tokens,
    fold_arc_lines_into_volumes,
    resolve_context_profile,
)


def _make_160_episode_context() -> dict:
    arc_lines = [
        f"【第{i * 10 + 1}~{(i + 1) * 10}话篇章纪要】"
        + f"第{i * 10 + 1}话至第{(i + 1) * 10}话主线推进：主角团在遗迹探索中发现古老星纹封印，"
        + "反派军团多次阻挠并揭示王国百年前的禁忌契约与失落王冠下落，角色羁绊深化。" * 3
        for i in range(16)
    ]
    return {
        "project_title": "长篇连载压测 (160话)",
        "story_bible": {
            "main_plot": {
                "core_conflict": "阻止深渊王座重启并找回七枚星辰碎片",
                "current_arc": "北境冰原决战篇",
                "protagonist_goal": "在日蚀降临前解开北境圣殿封印",
                "next_hook": "古老守门人突然苏醒并喊出主角真名",
            }
        },
        "canon_rules": '{"魔法代价": "每次禁术消耗一年记忆", "禁忌": "已故角色不可无因复活"}',
        "long_summary": "\n".join(arc_lines),
        "previous_bridge": {
            "episode_number": "160",
            "title": "冰原大门开启",
            "summary": "主角团抵达圣殿入口，守门人苏醒。",
            "ending_state": {"location": "北境圣殿", "cliffhanger": "守门人喊出主角真名"},
            "closing_dialogue": ["守门人: 终于回来了，第七任继承者。"],
        },
        "recent_episodes": [
            {
                "number": 151 + i,
                "title": f"第{151 + i}话 冰原行军",
                "summary": "主角团穿越暴风雪并遭遇冰霜魔像袭击，解开石碑铭文。" * 6,
                "events": [{"description": f"关键事件 {j}：战斗与线索发现" * 4} for j in range(6)],
                "state_changes": [{"character": "主角", "attribute": f"状态{i}", "after": "魔力透支"}],
            }
            for i in range(10)
        ],
        "character_dossier": [
            {
                "id": f"char-{i}",
                "name": f"角色{i}",
                "description": f"第{i}号角色外貌设定：黑色披风、银色短发、左眼疤痕与古董护符。" * 5,
                "current_state": "; ".join(f"attr{k}=状态变更说明{k}" for k in range(12)),
                "speech_samples": [f"台词样本{s}：绝不会退缩一步！" for s in range(5)],
            }
            for i in range(40)
        ],
        "unavailable_characters": [
            {
                "id": f"dead-{i}",
                "name": f"已故反派{i}",
                "vital_status": "deceased",
                "vital_status_episode": str(i * 4 + 2),
                "vital_status_note": f"在第{i * 4 + 2}话决战中彻底陨落",
            }
            for i in range(30)
        ],
        "world_assets": [
            {
                "id": f"item-{i}",
                "type": "item",
                "name": f"神器{i}",
                "description": f"拥有古老符文与空间共鸣能力的传奇遗物第{i}号。" * 4,
            }
            for i in range(45)
        ],
        "active_pits": [
            {
                "id": f"pit-{i}",
                "title": f"伏笔{i}",
                "description": f"第{i + 1}话埋下的关键悬念与线索追踪说明。" * 4,
                "priority": 9 if i < 6 else 5,
                "clues": [f"[第{i + 10}话线索] 再次出现相关纹章" for _ in range(4)],
            }
            for i in range(40)
        ],
        "rag_memories": [
            {
                "episode_number": i * 8 + 1,
                "type": "event",
                "content": f"早期第{i * 8 + 1}话关键回忆片段：星纹钥匙与圣殿密文的呼应。" * 3,
            }
            for i in range(16)
        ],
    }


def test_fold_arcs_into_50_episode_volumes():
    arcs = "\n".join(
        f"【第{i * 10 + 1}~{(i + 1) * 10}话篇章纪要】第{i + 1}篇章剧情摘要内容。"
        for i in range(16)
    )
    folded, did_fold, vol_cnt = fold_arc_lines_into_volumes(arcs, arcs_per_volume=5, keep_recent_arcs=4)
    assert did_fold is True
    assert vol_cnt >= 2
    assert "大卷纪要】" in folded
    # Recent 4 arcs (Ep 121~160) remain intact at full 10-ep granularity
    assert "【第151~160话篇章纪要】" in folded
    assert len(folded) < len(arcs)


def test_quality_profile_preserves_full_rich_context_for_200k_models():
    ctx = _make_160_episode_context()
    out = apply_dynamic_context_budget(ctx, profile=CONTEXT_PROFILES["quality"])
    budget = out["context_budget"]
    assert budget["profile"] == "quality"
    assert budget["budget_tokens"] == 64000
    assert budget["estimated_tokens_after"] <= 64000
    assert len(out["recent_episodes"]) == 10
    assert len(out["character_dossier"]) == 40
    assert out["previous_bridge"]["episode_number"] == "160"


def test_cost_profile_dynamically_trims_and_preserves_sacred_anchors():
    ctx = _make_160_episode_context()
    out = apply_dynamic_context_budget(ctx, profile=CONTEXT_PROFILES["cost"])
    budget = out["context_budget"]
    assert budget["profile"] == "cost"
    assert budget["budget_tokens"] == 10000
    assert budget["trimmed"] is True
    assert len(budget["trim_actions"]) >= 2
    assert budget["estimated_tokens_after"] <= budget["budget_tokens"]
    assert budget["estimated_tokens_after"] < budget["estimated_tokens_before"]
    # Sacred Tier-0 anchors must NEVER be dropped
    assert out["previous_bridge"]["episode_number"] == "160"
    assert out["story_bible"]["main_plot"]["core_conflict"]
    assert len(out["recent_episodes"]) >= 2
    # All 6 high-priority (P9) pits must survive
    surviving_high = [p for p in out["active_pits"] if p["priority"] >= 8]
    assert len(surviving_high) == 6


def test_resolve_profile_and_token_estimator():
    assert resolve_context_profile("quality").budget_tokens == 64000
    assert resolve_context_profile("balanced").budget_tokens == 28000
    assert resolve_context_profile("cost").budget_tokens == 10000
    assert resolve_context_profile("unknown", default_name="balanced").name == "balanced"
    assert estimate_tokens("异世界舅舅第十五话剧情摘要") > 8
    assert estimate_tokens("Hello world test string") > 4
