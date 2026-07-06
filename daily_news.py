#!/usr/bin/env python3
"""
每日早间股市新闻推送
每天早上8点运行，推送财经要闻和隔夜外盘
"""
import requests
import os
from datetime import datetime


def get_index_data():
    """获取主要指数行情"""
    lines = []
    index_codes = [
        ("sh000001", "上证指数"),
        ("sz399001", "深证成指"),
        ("sz399006", "创业板指"),
        ("sh000688", "科创50"),
    ]
    for code, name in index_codes:
        try:
            resp = requests.get(
                f"https://qt.gtimg.cn/q={code}",
                timeout=5,
                headers={"User-Agent": "Mozilla/5.0"},
            )
            data = resp.text.split("~")
            if len(data) > 45:
                price = data[3]
                pct = data[32]
                vol = float(data[37]) / 10000
                emoji = "🔴" if float(pct) > 0 else "🟢" if float(pct) < 0 else "⚪"
                lines.append(f"  {emoji} {name}: {price} ({pct}%) {vol:.0f}亿")
        except Exception:
            pass
    return lines


def get_sector_data():
    """获取板块涨跌"""
    try:
        resp = requests.get(
            "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php",
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        import re, json

        match = re.search(r"=\s*(\{.*\})", resp.text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            sectors = []
            for v in data.values():
                parts = v.split(",")
                if len(parts) > 5:
                    sectors.append((parts[1], float(parts[4]) if parts[4] else 0))
            sectors.sort(key=lambda x: x[1], reverse=True)
            up = [f"{n}({p:+.2f}%)" for n, p in sectors[:5]]
            dn = [f"{n}({p:+.2f}%)" for n, p in sectors[-5:]]
            return up, dn
    except Exception:
        pass
    return [], []


def get_news(count=10):
    """获取财经要闻"""
    lines = []
    try:
        resp = requests.get(
            "https://feed.mix.sina.com.cn/api/roll/get?pageid=153&lid=2516&k=&num=15&page=1",
            timeout=8,
            headers={
                "User-Agent": "Mozilla/5.0",
                "Referer": "https://finance.sina.com.cn",
            },
        )
        news_list = resp.json().get("result", {}).get("data", [])
        for n in news_list[:count]:
            title = n.get("title", "")[:55]
            intro = n.get("intro", "")[:65]
            if title:
                lines.append(f"  • {title}")
                if intro:
                    lines.append(f"    {intro}")
    except Exception:
        pass
    return lines


def send_feishu(msg):
    """发送飞书消息"""
    webhook = os.environ.get("FEISHU_WEBHOOK", "")
    if not webhook:
        print("FEISHU_WEBHOOK 未设置")
        return False
    resp = requests.post(
        webhook,
        json={"msg_type": "text", "content": {"text": msg}},
        timeout=10,
    )
    return resp.json().get("code") == 0


def main():
    now = datetime.now()
    lines = []

    # 标题
    lines.append(f"☀️ 早安缅A ({now.strftime('%Y-%m-%d %A')})")
    lines.append("")

    # 上个交易日大盘回顾
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📈 上个交易日大盘回顾")
    lines.append("")
    idx_lines = get_index_data()
    if idx_lines:
        lines.extend(idx_lines)
        lines.append("")

    # 板块热力图
    up_sectors, dn_sectors = get_sector_data()
    if up_sectors:
        lines.append("🔥 板块热力图")
        lines.append(f"  🔴 领涨: {' | '.join(up_sectors)}")
        lines.append(f"  🟢 领跌: {' | '.join(dn_sectors)}")
        lines.append("")

    # 财经要闻
    lines.append("━━━━━━━━━━━━━━━━━━━━")
    lines.append("📰 今日财经要闻")
    lines.append("")
    news = get_news(10)
    if news:
        lines.extend(news)
    else:
        lines.append("  暂无新闻")

    # 发送
    msg = "\n".join(lines)
    if send_feishu(msg):
        print(f"✅ 早间新闻推送成功 ({now.strftime('%H:%M:%S')})")
    else:
        print("❌ 推送失败")


if __name__ == "__main__":
    main()
