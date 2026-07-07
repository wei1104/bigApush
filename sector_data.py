"""
板块数据获取模块
获取行业板块、概念板块、资金流向数据
"""
import requests
import re
import json


def get_industry_sectors():
    """获取行业板块涨跌"""
    try:
        url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaHy.php"
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        match = re.search(r"=\s*(\{.*\})", resp.text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            sectors = []
            for v in data.values():
                parts = v.split(",")
                if len(parts) > 5:
                    name = parts[1]
                    pct = float(parts[4]) if parts[4] else 0
                    sectors.append({"name": name, "pct": pct})
            sectors.sort(key=lambda x: x["pct"], reverse=True)
            return sectors
    except Exception:
        pass
    return []


def get_concept_sectors():
    """获取概念板块涨跌"""
    try:
        url = "https://vip.stock.finance.sina.com.cn/q/view/newSinaGN.php"
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        match = re.search(r"=\s*(\{.*\})", resp.text, re.DOTALL)
        if match:
            data = json.loads(match.group(1))
            sectors = []
            for v in data.values():
                parts = v.split(",")
                if len(parts) > 4:
                    name = parts[1]
                    pct = float(parts[3]) if parts[3] else 0
                    sectors.append({"name": name, "pct": pct})
            sectors.sort(key=lambda x: x["pct"], reverse=True)
            return sectors
    except Exception:
        pass
    return []


def get_sector_fund_flow():
    """获取板块资金流向（新浪）"""
    try:
        url = "https://vip.stock.finance.sina.com.cn/quotes_service/api/json_v2.php/MoneyFlow.ssl_bkzj_bk"
        params = {
            "page": 1,
            "num": 20,
            "sort": "netamount",
            "asc": 0,
            "fenlei": 1
        }
        resp = requests.get(url, params=params, timeout=8, headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://finance.sina.com.cn"
        })
        data = resp.json()
        if data and isinstance(data, list):
            result = []
            for item in data:
                name = item.get("name", "")
                net = float(item.get("netamount", 0)) / 100000000  # 转换为亿
                result.append({"name": name, "fund": net})
            return result
    except Exception:
        pass
    return []


def format_sector_message():
    """格式化板块数据为飞书消息"""
    lines = []

    # 行业板块
    industries = get_industry_sectors()
    if industries:
        up = [f"{s['name']}({s['pct']:+.2f}%)" for s in industries[:5]]
        dn = [f"{s['name']}({s['pct']:+.2f}%)" for s in industries[-5:]]
        lines.append("📊 行业板块")
        lines.append(f"  🔴 领涨: {' | '.join(up)}")
        lines.append(f"  🟢 领跌: {' | '.join(dn)}")
        lines.append("")

    # 概念板块
    concepts = get_concept_sectors()
    if concepts:
        up = [f"{s['name']}({s['pct']:+.2f}%)" for s in concepts[:5]]
        dn = [f"{s['name']}({s['pct']:+.2f}%)" for s in concepts[-5:]]
        lines.append("💡 概念板块")
        lines.append(f"  🔴 领涨: {' | '.join(up)}")
        lines.append(f"  🟢 领跌: {' | '.join(dn)}")
        lines.append("")

    # 资金流向
    lines.append("💰 板块资金流向")
    fund_flow = get_sector_fund_flow()
    if fund_flow:
        sorted_flow = sorted(fund_flow, key=lambda x: x['fund'], reverse=True)
        inflow = [f"{s['name']}({s['fund']:+.2f}亿)" for s in sorted_flow if s['fund'] > 0][:5]
        outflow = [f"{s['name']}({s['fund']:+.2f}亿)" for s in sorted_flow if s['fund'] < 0][:5]
        if inflow:
            lines.append(f"  净流入: {' | '.join(inflow)}")
        if outflow:
            lines.append(f"  净流出: {' | '.join(outflow)}")
        if not inflow and not outflow:
            lines.append("  无数据")
    else:
        lines.append("  数据暂不可用")
    lines.append("")

    return "\n".join(lines)


if __name__ == "__main__":
    print(format_sector_message())
