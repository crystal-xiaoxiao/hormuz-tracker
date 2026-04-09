#!/usr/bin/env python3
"""
霍尔木兹海峡通航量每日追踪
- 调用 Claude API + web_search 抓取最新数据
- 写入 history/YYYY-MM-DD.json
- 重建 docs/data.json (供网页加载)
- 可选: 推送飞书机器人

环境变量:
  ANTHROPIC_API_KEY    必填
  FEISHU_WEBHOOK_URL   选填
  FEISHU_SECRET        选填
"""
import os
import sys
import json
import hmac
import time
import base64
import hashlib
import traceback
from pathlib import Path
from datetime import datetime, timezone

import requests
from anthropic import Anthropic

# ─────────────────────── 配置 ───────────────────────
ROOT = Path(__file__).parent
HISTORY_DIR = ROOT / "history"
DOCS_DIR = ROOT / "docs"
MODEL = "claude-sonnet-4-6"

ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
FEISHU_WEBHOOK = os.environ.get("FEISHU_WEBHOOK_URL", "")
FEISHU_SECRET = os.environ.get("FEISHU_SECRET", "")

client = Anthropic(api_key=ANTHROPIC_API_KEY)

# ─────────────────────── Prompt ───────────────────────
PROMPT_TEMPLATE = """你是一名专业的海运情报分析师，为一位投资人每天追踪霍尔木兹海峡通航恢复情况。
今天是 {today} (UTC)。请使用 web_search 工具检索过去 24-48 小时的最新数据。

**优先来源**: windward.ai/blog (最权威的日报源)、bloomberg.com、cnbc.com、
reuters.com、maritime-executive.com、lloydslist.com、tradewindsnews.com、
gcaptain.com。同时关注 Brent 油价、WTI Midland 价差、防务股 (LMT/RTX/NOC)
和战争险保费的最新报道。

完成检索后，**只输出一段 JSON**（不要任何解释、不要 markdown 代码块），严格遵循以下 schema:

{{
  "report_date": "YYYY-MM-DD",
  "data_window": "覆盖的时段，例如 'April 8-9, 2026'",
  "daily_transits": {{
    "count": <int 或 null>,
    "inbound": <int 或 null>,
    "outbound": <int 或 null>,
    "source": "主口径来源",
    "confidence": "high|medium|low"
  }},
  "cross_validation": [
    {{"source": "Windward", "count": <int 或 null>, "note": "简短说明"}},
    {{"source": "Lloyd's List 或 Kpler", "count": <int 或 null>, "note": "..."}},
    {{"source": "Iranian state media (Fars/Tasnim)", "count": <int 或 null>, "note": "..."}}
  ],
  "milestones": {{
    "bluechip_operators_returning": "yes|no|partial + 具体公司名",
    "war_risk_premium_status": "peak|elevated|declining|normalized + 数字 (如能找到)",
    "non_iran_inbound_share_pct": <0-100 的数字 或 null>,
    "negotiation_progress": "伊斯兰堡谈判或相关外交进展简述",
    "iran_toll_status": "implemented|negotiating|rejected|silent"
  }},
  "recovery_score": {{
    "transit_volume_score": <0-30>,
    "balance_score": <0-20>,
    "non_iran_share_score": <0-20>,
    "bluechip_score": <0-15>,
    "insurance_score": <0-15>,
    "total": <0-100>
  }},
  "market_signals": {{
    "brent_spot": <数字或null>,
    "brent_change_pct": <数字或null>,
    "wti_midland_premium": <数字或null>,
    "defense_stocks_note": "LMT/RTX/NOC 当日动向简述"
  }},
  "trading_signal": "重要的市场信号变化总结",
  "verdict": "一句话判断当日恢复程度",
  "key_news": ["要点1", "要点2", "要点3"]
}}

**评分方法（必须严格执行）**:
- transit_volume_score = min(30, count / 135 * 30)
- balance_score: |inbound/(inbound+outbound) - 0.5| < 0.1 → 20；线性递减至 0
- non_iran_share_score = (non_iran_inbound_share_pct / 100) * 20
- bluechip_score: 0 家=0；1 家=5；2-3 家=10；4+ 家=15
- insurance_score: 战争险保费仍在峰值=0；下降<25%=5；下降 25-50%=10；接近战前=15
- total = 五项之和

如果某个数据找不到，对应字段填 null，并在评分中给 0 分。**不要编造数字。**"""


# ─────────────────────── 抓取 ───────────────────────
def fetch_report() -> dict:
    prompt = PROMPT_TEMPLATE.format(today=datetime.now(timezone.utc).strftime("%Y-%m-%d"))
    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": 10}],
        messages=[{"role": "user", "content": prompt}],
    )
    text = "\n".join(b.text for b in response.content if getattr(b, "type", None) == "text")
    if "```json" in text:
        text = text.split("```json", 1)[1].split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1].split("```", 1)[0]
    return json.loads(text.strip())


# ─────────────────────── 持久化 ───────────────────────
def save_history(data: dict) -> Path:
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = HISTORY_DIR / f"{data['report_date']}.json"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return path


def rebuild_data_json() -> None:
    """把所有 history/*.json 聚合成 docs/data.json 供前端加载"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    reports = []
    for f in sorted(HISTORY_DIR.glob("*.json")):
        try:
            with open(f, encoding="utf-8") as fp:
                reports.append(json.load(fp))
        except Exception as e:
            print(f"[warn] skipping {f}: {e}", file=sys.stderr)
    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "report_count": len(reports),
        "reports": reports,
    }
    with open(DOCS_DIR / "data.json", "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    print(f"[ok] data.json rebuilt with {len(reports)} reports")


# ─────────────────────── 飞书 (可选) ───────────────────────
def status_from_score(score: int) -> tuple[str, str]:
    if score < 20:
        return "🔴 严重受阻", "red"
    if score < 50:
        return "🟠 有限放行", "orange"
    if score < 75:
        return "🟡 部分恢复", "yellow"
    return "🟢 接近正常", "green"


def sign_feishu(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    h = hmac.new(string_to_sign.encode(), digestmod=hashlib.sha256).digest()
    return base64.b64encode(h).decode()


def push_feishu(data: dict) -> None:
    if not FEISHU_WEBHOOK:
        print("[skip] FEISHU_WEBHOOK_URL 未设置，跳过推送")
        return

    score = data["recovery_score"]["total"]
    status, color = status_from_score(score)
    t = data["daily_transits"]
    ms = data["milestones"]
    rs = data["recovery_score"]

    cross_lines = "\n".join(
        f"• **{c['source']}**: {c['count'] if c['count'] is not None else 'N/A'} — {c['note']}"
        for c in data["cross_validation"]
    )
    news_lines = "\n".join(f"• {n}" for n in data["key_news"])

    body = f"""**📊 日通航数据**
主口径: **{t['count']}** 艘 (进 {t['inbound']} / 出 {t['outbound']})
来源: {t['source']} | 置信度: {t['confidence']}

**🔍 多源交叉验证**
{cross_lines}

**🎯 关键里程碑**
• 蓝筹运营商: {ms['bluechip_operators_returning']}
• 战争险保费: {ms['war_risk_premium_status']}
• 非伊朗入港占比: {ms['non_iran_inbound_share_pct']}%
• 外交进展: {ms['negotiation_progress']}
• 通行费: {ms['iran_toll_status']}

**📈 恢复评分: {score}/100**
通航量 {rs['transit_volume_score']}/30 · 收支平衡 {rs['balance_score']}/20 · 非伊关联 {rs['non_iran_share_score']}/20 · 蓝筹 {rs['bluechip_score']}/15 · 保险 {rs['insurance_score']}/15

**💹 交易信号**
{data['trading_signal']}

**📰 今日要闻**
{news_lines}

---
**结论**: {data['verdict']}

🔗 完整网页: https://你的用户名.github.io/hormuz-tracker/"""

    payload = {
        "msg_type": "interactive",
        "card": {
            "config": {"wide_screen_mode": True},
            "header": {
                "title": {"tag": "plain_text",
                          "content": f"霍尔木兹通航追踪 · {data['report_date']}"},
                "subtitle": {"tag": "plain_text",
                             "content": f"{status} · {data['data_window']}"},
                "template": color,
            },
            "elements": [{"tag": "div",
                          "text": {"tag": "lark_md", "content": body}}],
        },
    }

    if FEISHU_SECRET:
        ts = str(int(time.time()))
        payload["timestamp"] = ts
        payload["sign"] = sign_feishu(ts, FEISHU_SECRET)

    r = requests.post(FEISHU_WEBHOOK, json=payload, timeout=30)
    r.raise_for_status()
    print(f"[ok] feishu push: {r.json()}")


# ─────────────────────── main ───────────────────────
def main() -> int:
    try:
        print(f"[{datetime.now():%H:%M:%S}] 抓取中…")
        data = fetch_report()
        print(f"[ok] 评分 {data['recovery_score']['total']}/100")

        save_history(data)
        rebuild_data_json()
        push_feishu(data)
        return 0
    except Exception as e:
        tb = traceback.format_exc()
        print(tb, file=sys.stderr)
        if FEISHU_WEBHOOK:
            try:
                payload = {"msg_type": "text",
                           "content": {"text": f"❌ 霍尔木兹追踪失败 "
                                               f"({datetime.now():%Y-%m-%d %H:%M})\n{e}"}}
                if FEISHU_SECRET:
                    ts = str(int(time.time()))
                    payload["timestamp"] = ts
                    payload["sign"] = sign_feishu(ts, FEISHU_SECRET)
                requests.post(FEISHU_WEBHOOK, json=payload, timeout=10)
            except Exception:
                pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
