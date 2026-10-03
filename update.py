#!/usr/bin/env python3
"""每日更新 LME 鋁價日報 index.html，並保留當日快照 snapshots/YYYY-MM-DD.html。
資料來源：Westmetall(LME)、鋁道網(長江A00)、Frankfurter(USD/CNY)、CMoney(台指期夜盤)。
任一來源失敗時保留該區舊資料；全部來源都失敗才讓工作流程失敗。"""
import re, json, sys, shutil, datetime as dt, urllib.request, html as htmllib
from pathlib import Path

ROOT = Path(__file__).parent
PAGE = ROOT / "index.html"
UA = {"User-Agent": "Mozilla/5.0 (compatible; lme-al-daily/1.0)"}

def get(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")

def text_rows(page):
    """HTML 表格 → [[儲存格文字,...], ...]"""
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        cells = [htmllib.unescape(re.sub(r"<[^>]+>", "", c)).strip()
                 for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", tr, re.S | re.I)]
        if cells:
            rows.append(cells)
    return rows

def num(x):
    return float(x.replace(",", "").replace("\xa0", "").strip())

# ── 1. LME (Westmetall) ──────────────────────────────────────────
def fetch_lme():
    page = get("https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Al_cash")
    out = {}
    for c in text_rows(page):
        if len(c) < 4:
            continue
        try:
            d = dt.datetime.strptime(re.sub(r"\s+", " ", c[0]), "%d. %B %Y").date().isoformat()
            out[d] = dict(cash=num(c[1]), fwd=num(c[2]), stock=int(num(c[3])))
        except ValueError:
            continue
    return out

# ── 2. 長江 A00（鋁道網）──────────────────────────────────────────
def fetch_a00():
    page = get("https://hq.alu.cn/data/4/")
    out = {}
    for c in text_rows(page):
        m = re.search(r"\d{4}-\d{2}-\d{2}", " ".join(c))
        if not m:
            continue
        nums = [int(v.replace(",", "")) for v in c if re.fullmatch(r"\d{2},?\d{3}", v.strip())]
        if len(nums) >= 3:                      # 最低、最高、均價
            out[m.group(0)] = nums[2]
    return out

# ── 3. 匯率 USD/CNY（Frankfurter / ECB）──────────────────────────
def fetch_fx(since):
    data = json.loads(get(f"https://api.frankfurter.dev/v1/{since}..?base=USD&symbols=CNY"))
    return {d: round(v["CNY"], 4) for d, v in data["rates"].items()}

# ── 4. 台指期夜盤（CMoney）───────────────────────────────────────
def fetch_tx():
    page = htmllib.unescape(re.sub(r"<[^>]+>", " ", get("https://www.cmoney.tw/forum/futures/TXF1?s=p")))
    page = re.sub(r"\s+", " ", page)
    price = re.search(r"成交\s*([\d,]+(?:\.\d+)?)", page)
    chg = re.search(r"漲跌(?!幅)\s*([\d,]+(?:\.\d+)?)", page)
    pct = re.search(r"漲跌幅\s*([+\-−]?\s*[\d.]+)\s*%", page)
    if not (price and chg and pct):
        raise ValueError("CMoney 欄位解析失敗")
    p = float(pct.group(1).replace("−", "-").replace(" ", ""))
    c = float(chg.group(1).replace(",", ""))
    sign = -1 if p < 0 else 1
    return dict(price=num(price.group(1)), change=sign * c, pct=p)

# ── 頁面內資料讀寫 ───────────────────────────────────────────────
def read_array(src, name, pat):
    m = re.search(rf"const {name} = \[\n(.*?)\n\];", src, re.S)
    return {mm.group(1): mm.groups()[1:] for mm in re.finditer(pat, m.group(1))}, m

def fmt_n(v):
    return f"{v:.2f}"

def replace_block(src, name, lines):
    return re.sub(rf"(const {name} = \[\n).*?(\n\];)", lambda m: m.group(1) + "\n".join(lines) + m.group(2), src, count=1, flags=re.S)

def add_months(ym, k):
    y, m = map(int, ym.split("-"))
    i = y * 12 + (m - 1) + k
    return f"{i // 12}-{i % 12 + 1:02d}"

ZH = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]

def shift_month_names(seg, k):
    def f(m):
        i = ZH.index(m.group(1))
        return ZH[(i + k) % 12] + "月"
    return re.sub(r"(十一|十二|十|一|二|三|四|五|六|七|八|九)月", f, seg)

def main():
    src = PAGE.read_text(encoding="utf-8")
    ok = 0

    # LME
    try:
        lme = fetch_lme()
        old, _ = read_array(src, "raw", r'\{ date:"([\d-]+)", cash:([\d.]+), fwd:([\d.]+), stock:(\d+) \}')
        rows = {d: dict(cash=float(a), fwd=float(b), stock=int(c)) for d, (a, b, c) in old.items()}
        rows.update(lme)
        lines = [f'  {{ date:"{d}", cash:{fmt_n(r["cash"])}, fwd:{fmt_n(r["fwd"])}, stock:{r["stock"]} }},'
                 for d, r in sorted(rows.items(), reverse=True)]
        src = replace_block(src, "raw", lines)
        latest = max(rows)
        ok += 1
        print("LME ok, latest", latest, "新增", len(set(rows) - set(old)))
    except Exception as e:
        print("LME 失敗：", e); latest = None
        rows = None

    # A00
    try:
        a00 = fetch_a00()
        old, _ = read_array(src, "cnAl", r'\{ date:"([\d-]+)", avg:(\d+) \}')
        cn = {d: int(v[0]) for d, v in old.items()}
        cn.update(a00)
        lines = [f'  {{ date:"{d}", avg:{v} }},' for d, v in sorted(cn.items(), reverse=True)]
        src = replace_block(src, "cnAl", lines)
        ok += 1
        print("A00 ok, latest", max(cn), "新增", len(set(cn) - set(old)))
    except Exception as e:
        print("A00 失敗：", e)

    # FX
    try:
        m = re.search(r"const FX = (\{.*?\});", src, re.S)
        fx = json.loads(m.group(1))
        fx_new = fetch_fx(max(fx))
        fx.update(fx_new)
        lit = "{" + ",".join(f'"{d}":{v}' for d, v in sorted(fx.items(), reverse=True)) + "}"
        src = src.replace(m.group(0), f"const FX = {lit};", 1)
        ok += 1
        print("FX ok, latest", max(fx))
    except Exception as e:
        print("FX 失敗：", e)

    # 台指期
    today = dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).date().isoformat()
    try:
        tx = fetch_tx()
        line = f'const txData = {{ price: {tx["price"]:g}, change: {tx["change"]:g}, pct: {tx["pct"]:g}, updated: "{today}" }};'
        src = re.sub(r"const txData = \{[^}]*\};", line, src, count=1)
        ok += 1
        print("TX ok", line)
    except Exception as e:
        print("TX 失敗：", e)

    if ok == 0:
        print("所有來源都失敗，不更新"); sys.exit(1)

    # 資料截至、月份
    if latest:
        src = re.sub(r"(<span>資料截至</span>)\d{4}-\d{2}-\d{2}", rf"\g<1>{latest}", src, count=1)
        cur = latest[:7]
        old_cur = re.search(r"const curMonthKey\s*= '(\d{4}-\d{2})'", src).group(1)
        k = (int(cur[:4]) * 12 + int(cur[5:])) - (int(old_cur[:4]) * 12 + int(old_cur[5:]))
        if k:
            names = [("lastMonthKey", -1), ("curMonthKey", 0), ("prevPrevMonthKey", -2),
                     ("prevPrevPrevMonthKey", -3), ("febMonthKey", -4), ("janMonthKey", -5)]
            for n, off in names:
                src = re.sub(rf"(const {n}\s*= ')\d{{4}}-\d{{2}}'", rf"\g<1>{add_months(cur, off)}'", src, count=1)
            for n, off in zip(["cnMayAvg", "cnAprAvg", "cnMarAvg", "cnFebAvg", "cnJanAvg"], range(-1, -6, -1)):
                src = re.sub(rf"(const {n} = cnMonthAvg\(')\d{{4}}-\d{{2}}'", rf"\g<1>{add_months(cur, off)}'", src, count=1)
            a = src.index("const lastMonthKey")
            b = src.index("]);", src.index("月均價 · 3M 期貨")) if "月均價 · 3M 期貨" in src else len(src)
            src = src[:a] + shift_month_names(src[a:b], k) + src[b:]
            print("月份已位移", k)

    PAGE.write_text(src, encoding="utf-8")

    # 每日快照
    snap = ROOT / "snapshots"
    snap.mkdir(exist_ok=True)
    stamp = latest or today
    shutil.copy(PAGE, snap / f"{stamp}.html")
    files = sorted((p.stem for p in snap.glob("????-??-??.html")), reverse=True)
    items = "\n".join(f'<li><a href="{f}.html">{f}</a></li>' for f in files)
    (snap / "index.html").write_text(
        '<!doctype html><html lang="zh-TW"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
        '<title>LME 鋁價日報 歷史版本</title><style>body{font-family:-apple-system,"Segoe UI",sans-serif;max-width:560px;margin:32px auto;padding:0 16px;color:#1e293b}'
        'li{margin:6px 0}a{color:#0f5ea8}</style></head><body><h1>歷史版本</h1><p><a href="../">回到最新版</a></p><ul>'
        + items + "</ul></body></html>", encoding="utf-8")
    print("快照", stamp)

if __name__ == "__main__":
    main()
