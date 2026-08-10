"""
일일 리포트 — 통계 중심(Tableau 스타일)의 자체완결형 HTML 생성기.

설계 방침(사용자 취향):
  - 통계를 크게 앞세움(BAN: big-ass-numbers 배너)
  - 볼거리 최소화 — 화려한 차트/무지개 색 지양
  - 신뢰되는 뮤트 톤 2색: 뮤트 블루(맥락·데이터) + 뮤트 레드(이상), 나머지는 회색
  - 구성: 통계 배너 → 정상/이상 비율 슬림바 → 시간대별 이상 추이(단색) → 이상 요약 테이블

외부 라이브러리·CDN 없음(오프라인/이메일 가능). Slack 요약(report_utils)과 같은 inference_log 사용.
"""

import os
import html
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2

KST = ZoneInfo("Asia/Seoul")

# ---- 뮤트 2색 팔레트 (Tableau 계열, 신뢰 톤) ----
ACCENT = "#4e79a7"   # 뮤트 블루 — 맥락/데이터
ANOM   = "#c94b4b"   # 뮤트 레드 — 이상
NORMAL_G = "#d3d7dd" # 정상 비율바 회색
INK    = "#1f2328"
INK2   = "#57606a"
MUTED  = "#8b949e"
GRID   = "#eaecef"
BASELINE = "#d0d4d9"
SURFACE = "#ffffff"
EQUIP_IDS = [f"EQ-{i:02d}" for i in range(1, 11)]


def _dsn():
    dsn = os.getenv("POSTGRES_DSN")
    if not dsn:
        raise RuntimeError("POSTGRES_DSN 미설정")
    return dsn


# ======================================================================
# 집계
# ======================================================================
def fetch_rich_stats(start: datetime, end: datetime, threshold=None) -> dict:
    from report_utils import fetch_stats, disp_fault, REAL_ANOM
    base = fetch_stats(start, end)

    conn = psycopg2.connect(_dsn())
    try:
        with conn.cursor() as cur:
            # 시간대별 추이는 '전체 이상'(통계값) 유지 — 미분류 포함
            cur.execute("""
                SELECT extract(hour from (ts AT TIME ZONE 'Asia/Seoul'))::int AS h,
                       count(*) FILTER (WHERE is_anomaly IS TRUE) AS anom
                FROM inference_log WHERE ts >= %(s)s AND ts < %(e)s
                GROUP BY h ORDER BY h
            """, {"s": start, "e": end})
            hourly = {h: a for h, a in cur.fetchall()}

            cur.execute(f"""
                SELECT equipment_id,
                       count(*) FILTER (WHERE {REAL_ANOM}) AS anom_ticks,
                       max(mse) AS mx
                FROM inference_log WHERE ts >= %(s)s AND ts < %(e)s
                GROUP BY equipment_id
            """, {"s": start, "e": end})
            eq_extra = {eq: {"ticks": t, "maxmse": mx} for eq, t, mx in cur.fetchall()}

            # 결함 유형별 '이상 Run 수' (실제 결함만) — 감지요약 테이블의 '회'와 동일 단위로 일치
            cur.execute(f"""
                WITH run_label AS (
                    SELECT equipment_id, run_name,
                           mode() WITHIN GROUP (ORDER BY predicted_label) AS label
                    FROM inference_log
                    WHERE ts >= %(s)s AND ts < %(e)s AND {REAL_ANOM}
                    GROUP BY equipment_id, run_name
                )
                SELECT label, count(*) AS c FROM run_label GROUP BY label ORDER BY c DESC
            """, {"s": start, "e": end})
            fault_counts = [(disp_fault(l), c) for l, c in cur.fetchall()]

            # MSE 심각도 구간 (임계치 배수 기준)
            severity = None
            if threshold:
                cur.execute("""
                    SELECT count(*) FILTER (WHERE mse < %(t)s)                          AS c_normal,
                           count(*) FILTER (WHERE mse >= %(t)s   AND mse < 2*%(t)s)      AS c_mild,
                           count(*) FILTER (WHERE mse >= 2*%(t)s AND mse < 4*%(t)s)      AS c_moderate,
                           count(*) FILTER (WHERE mse >= 4*%(t)s)                        AS c_severe
                    FROM inference_log WHERE ts >= %(s)s AND ts < %(e)s AND mse IS NOT NULL
                """, {"s": start, "e": end, "t": threshold})
                n, mi, mo, se = cur.fetchone()
                severity = {"normal": n, "mild": mi, "moderate": mo, "severe": se}
    finally:
        conn.close()

    base.update({"hourly": hourly, "eq_extra": eq_extra,
                 "fault_counts": fault_counts, "severity": severity})
    return base


# ======================================================================
# 헬퍼
# ======================================================================
def _esc(s): return html.escape(str(s))
def _fmt(n): return f"{n:,}"


def _uptime(min_ts, max_ts):
    if not min_ts or not max_ts:
        return "0시간 0분"
    m = int((max_ts - min_ts).total_seconds() // 60)
    return f"{m // 60}시간 {m % 60}분"


def _ratio_bar(normal, anomaly):
    total = normal + anomaly or 1
    a_pct = anomaly / total * 100
    n_pct = 100 - a_pct
    return f"""
<div class="ratio">
  <div class="ratio-track">
    <div class="ratio-normal" style="width:{n_pct:.2f}%"></div>
    <div class="ratio-anom" style="width:{a_pct:.2f}%"></div>
  </div>
  <div class="ratio-lbls">
    <span><i class="sw" style="background:{NORMAL_G}"></i>정상 {_fmt(normal)} · {n_pct:.1f}%</span>
    <span><i class="sw" style="background:{ANOM}"></i>이상 {_fmt(anomaly)} · {a_pct:.1f}%</span>
  </div>
</div>"""


def svg_hourly(hourly):
    W, H = 900, 200
    pl, pr, pt, pb = 40, 16, 18, 30
    pw, ph = W - pl - pr, H - pt - pb
    vals = [hourly.get(h, 0) for h in range(24)]
    vmax = max(vals) or 1
    def X(h): return pl + pw * (h / 23)
    def Y(v): return pt + ph * (1 - v / vmax)
    grid = []
    for gv in sorted(set([0, round(vmax / 2), vmax])):
        gy = Y(gv)
        grid.append(f'<line x1="{pl}" y1="{gy:.1f}" x2="{W-pr}" y2="{gy:.1f}" stroke="{GRID}" stroke-width="1"/>')
        grid.append(f'<text x="{pl-8}" y="{gy+4:.1f}" text-anchor="end" font-size="11" '
                    f'fill="{MUTED}" font-variant-numeric="tabular-nums">{gv}</text>')
    pts = " ".join(f"{X(h):.1f},{Y(v):.1f}" for h, v in enumerate(vals))
    area = f"{pl},{pt+ph} {pts} {W-pr},{pt+ph}"
    xlab = "".join(
        f'<text x="{X(h):.1f}" y="{H-9}" text-anchor="middle" font-size="11" '
        f'fill="{MUTED}" font-variant-numeric="tabular-nums">{h}시</text>'
        for h in [0, 6, 12, 18, 23])
    dots = "".join(
        f'<circle cx="{X(h):.1f}" cy="{Y(v):.1f}" r="3.5" fill="{ANOM}" stroke="{SURFACE}" '
        f'stroke-width="1.5"><title>{h}시: 이상 {v}건</title></circle>'
        for h, v in enumerate(vals) if v > 0)
    peak = max(range(24), key=lambda h: vals[h])
    plab = (f'<text x="{X(peak):.1f}" y="{Y(vals[peak])-10:.1f}" text-anchor="middle" '
            f'font-size="12" font-weight="700" fill="{INK}">{vals[peak]}</text>') if vals[peak] > 0 else ""
    return f"""
<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="시간대별 이상 감지 추이">
  {''.join(grid)}
  <polygon points="{area}" fill="{ANOM}" fill-opacity="0.08"/>
  <polyline points="{pts}" fill="none" stroke="{ANOM}" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
  {dots}{plab}{xlab}
</svg>"""


def anomaly_table(stats, threshold=None):
    eq = stats["equipment"]
    if not eq:
        return '<p class="empty">이상으로 판정된 설비가 없습니다. 전 설비 정상 가동.</p>'
    extra = stats["eq_extra"]
    rows = []
    for eqid, info in eq.items():
        e = extra.get(eqid, {})
        rows.append({
            "eq": eqid,
            "faults": ", ".join(f"{lbl}({n})" for lbl, n in info["breakdown"]),
            "runs": info["total"],
            "ticks": e.get("ticks", 0),
            "maxmse": e.get("maxmse") or 0.0,
        })
    rows.sort(key=lambda r: -r["maxmse"])
    trs = []
    for r in rows:
        over = threshold and r["maxmse"] > threshold
        mse_cls = ' class="mse-over"' if over else ''
        trs.append(
            f'<tr><td class="eqc">{_esc(r["eq"])}</td>'
            f'<td>{_esc(r["faults"])}</td>'
            f'<td class="num">{r["runs"]}</td>'
            f'<td class="num">{_fmt(r["ticks"])}</td>'
            f'<td class="num"{mse_cls}>{r["maxmse"]:.3f}</td></tr>')
    thr = f'<span class="thr">임계치 {threshold:.3f} 초과 = <b style="color:{ANOM}">빨강</b></span>' if threshold else ''
    return f"""
<table class="atbl">
  <thead><tr><th>설비</th><th>결함 종류 (횟수)</th><th class="num">이상 Run</th>
    <th class="num">이상 tick</th><th class="num">최고 MSE</th></tr></thead>
  <tbody>{''.join(trs)}</tbody>
</table>{thr}"""


def svg_severity(sev, threshold):
    if not sev:
        return '<p class="empty">MSE 데이터가 없습니다.</p>'
    import math
    cats = [
        ("정상", "< 임계치", sev["normal"], NORMAL_G),
        ("경미", "임계치~2×", sev["mild"], "#e0a3a3"),
        ("중간", "2×~4×", sev["moderate"], "#cf6b6b"),
        ("심각", "4× 이상", sev["severe"], ANOM),
    ]
    W, H = 440, 210
    pl, pr, pt, pb = 8, 8, 24, 42
    pw, ph = W - pl - pr, H - pt - pb
    hmax = max(math.sqrt(c) for _, _, c, _ in cats) or 1  # sqrt 스케일(치우침 완화), 값은 라벨로 명시
    n = len(cats)
    slot = pw / n
    bw = min(72, slot * 0.6)
    parts = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="MSE 심각도 구간 분포">']
    parts.append(f'<line x1="{pl}" y1="{pt+ph}" x2="{W-pr}" y2="{pt+ph}" stroke="{BASELINE}" stroke-width="1"/>')
    for i, (name, rng, c, col) in enumerate(cats):
        cx = pl + slot * (i + 0.5)
        bh = ph * (math.sqrt(c) / hmax) if c else 0
        y = pt + ph - bh
        parts.append(f'<rect x="{cx-bw/2:.1f}" y="{y:.1f}" width="{bw:.1f}" height="{bh:.1f}" rx="4" '
                     f'fill="{col}"><title>{name} ({rng}): {_fmt(c)}건</title></rect>')
        parts.append(f'<text x="{cx:.1f}" y="{y-7:.1f}" text-anchor="middle" font-size="12.5" '
                     f'font-weight="700" fill="{INK}" font-variant-numeric="tabular-nums">{_fmt(c)}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{pt+ph+17}" text-anchor="middle" font-size="12" fill="{INK2}">{name}</text>')
        parts.append(f'<text x="{cx:.1f}" y="{pt+ph+32}" text-anchor="middle" font-size="10.5" fill="{MUTED}">{rng}</text>')
    parts.append('</svg>')
    return "".join(parts)


def bars_fault_counts(fault_counts):
    if not fault_counts:
        return '<p class="empty">감지된 결함이 없습니다.</p>'
    items = fault_counts[:7]
    mx = max(c for _, c in items) or 1
    out = ['<div class="hbars">']
    for lbl, c in items:
        out.append(
            f'<div class="hb"><span class="hb-l">{_esc(lbl)}</span>'
            f'<span class="hb-t"><i style="width:{c/mx*100:.1f}%"></i></span>'
            f'<span class="hb-v">{_fmt(c)}회</span></div>')
    out.append('</div>')
    return "".join(out)


# ======================================================================
# HTML 조립
# ======================================================================
def _stat(label, value, sub="", accent=None):
    col = f' style="color:{accent}"' if accent else ""
    subhtml = f'<div class="s-sub">{sub}</div>' if sub else ""
    return (f'<div class="stat"><div class="s-label">{label}</div>'
            f'<div class="s-val"{col}>{value}</div>{subhtml}</div>')


def build_html(stats, day_label, threshold=None):
    total = stats["total"]; normal = stats["normal"]; anomaly = stats["anomaly"]
    a_pct = anomaly / total * 100 if total else 0
    n_pct = 100 - a_pct if total else 0
    fault_runs = sum(i["total"] for i in stats["equipment"].values())
    mm = stats["max_mse"]
    if mm and mm["mse"] is not None:
        mm_val = f'{mm["mse"]:.3f}'
        mm_sub = f'{mm["equipment_id"]} · {mm["ts"].astimezone(KST).strftime("%H:%M:%S")}'
    else:
        mm_val, mm_sub = "—", ""
    uptime = _uptime(stats["min_ts"], stats["max_ts"])

    if total == 0:
        body = ('<div class="empty-day">어제 수집된 데이터가 없습니다.<br>'
                '<span>상시 워커/Kafka 스트림 상태를 확인하세요.</span></div>')
    else:
        body = f"""
      <section class="stats">
        {_stat("총 처리", _fmt(total), "데이터 포인트")}
        {_stat("이상 감지", _fmt(anomaly), f"{a_pct:.1f}%", ANOM)}
        {_stat("이상 Run", f"{fault_runs}", "결함 판정 Run")}
        {_stat("최고 MSE", mm_val, mm_sub, ANOM if (threshold and mm and mm["mse"] and mm["mse"]>threshold) else None)}
        {_stat("가동 시간", uptime, "데이터 수집 구간")}
      </section>

      {_ratio_bar(normal, anomaly)}

      <section class="block">
        <h2>시간대별 이상 감지 추이</h2>
        {svg_hourly(stats["hourly"])}
      </section>

      <section class="block">
        <h2>이상 감지 요약</h2>
        {anomaly_table(stats, threshold)}
      </section>

      <div class="row2">
        <section class="block">
          <h2>MSE 심각도 구간 분포</h2>
          {svg_severity(stats.get("severity"), threshold)}
        </section>
        <section class="block">
          <h2>결함 유형별 이상 감지 (Run 수)</h2>
          {bars_fault_counts(stats.get("fault_counts", []))}
        </section>
      </div>
"""

    return f"""<!doctype html>
<html lang="ko"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>일일 모니터링 리포트 {day_label}</title>
<style>
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:#f6f7f9; color:{INK};
    font-family:system-ui,-apple-system,"Segoe UI","Malgun Gothic",sans-serif; }}
  .wrap {{ max-width:960px; margin:0 auto; padding:30px 24px 50px; }}
  header.rpt {{ display:flex; align-items:baseline; justify-content:space-between;
    border-bottom:1px solid {BASELINE}; padding-bottom:16px; margin-bottom:26px; flex-wrap:wrap; gap:6px; }}
  header.rpt .eyebrow {{ font-size:11px; font-weight:700; letter-spacing:1.5px; color:{MUTED}; }}
  header.rpt h1 {{ font-size:22px; margin:5px 0 0; font-weight:650; }}
  header.rpt .date {{ font-size:14px; color:{INK2}; font-variant-numeric:tabular-nums; }}

  /* 통계 배너 (BAN) */
  .stats {{ display:grid; grid-template-columns:repeat(5,1fr); gap:1px; background:{GRID};
    border:1px solid {GRID}; border-radius:10px; overflow:hidden; margin-bottom:20px; }}
  .stat {{ background:{SURFACE}; padding:18px 18px 16px; }}
  .s-label {{ font-size:11px; color:{INK2}; letter-spacing:.3px; margin-bottom:10px; }}
  .s-val {{ font-size:34px; font-weight:700; line-height:1; letter-spacing:-.5px; }}
  .s-sub {{ font-size:11.5px; color:{MUTED}; margin-top:7px; font-variant-numeric:tabular-nums; }}

  /* 정상/이상 비율 바 */
  .ratio {{ margin:0 0 28px; }}
  .ratio-track {{ display:flex; height:12px; border-radius:6px; overflow:hidden; background:{GRID}; }}
  .ratio-normal {{ background:{NORMAL_G}; }}
  .ratio-anom {{ background:{ANOM}; }}
  .ratio-lbls {{ display:flex; justify-content:space-between; margin-top:8px;
    font-size:12.5px; color:{INK2}; font-variant-numeric:tabular-nums; }}
  .ratio-lbls .sw {{ display:inline-block; width:9px; height:9px; border-radius:2px; margin-right:6px; vertical-align:middle; }}

  .block {{ background:{SURFACE}; border:1px solid {GRID}; border-radius:10px; padding:20px 22px; margin-bottom:20px; overflow-x:auto; }}
  .block h2 {{ font-size:13px; font-weight:600; color:{INK}; margin:0 0 16px; letter-spacing:.2px; }}

  /* 이상 요약 테이블 */
  table.atbl {{ width:100%; border-collapse:collapse; font-size:13px; }}
  table.atbl th {{ text-align:left; font-weight:600; color:{INK2}; font-size:11.5px;
    letter-spacing:.3px; padding:0 14px 10px; border-bottom:1.5px solid {BASELINE}; }}
  table.atbl td {{ padding:11px 14px; border-bottom:1px solid {GRID}; color:{INK}; }}
  table.atbl td.eqc {{ font-weight:650; }}
  table.atbl .num {{ text-align:right; font-variant-numeric:tabular-nums; }}
  table.atbl td.mse-over {{ color:{ANOM}; font-weight:700; }}
  .thr {{ display:inline-block; margin-top:12px; font-size:11.5px; color:{MUTED}; }}

  .row2 {{ display:grid; grid-template-columns:1fr 1fr; gap:20px; }}
  .row2 .block {{ margin-bottom:20px; }}
  .hbars {{ display:flex; flex-direction:column; gap:12px; padding-top:2px; }}
  .hb {{ display:grid; grid-template-columns:88px 1fr 46px; align-items:center; gap:10px; font-size:12.5px; }}
  .hb-l {{ color:{INK2}; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }}
  .hb-t {{ background:{GRID}; border-radius:5px; height:14px; overflow:hidden; }}
  .hb-t i {{ display:block; height:100%; border-radius:5px; background:{ANOM}; }}
  .hb-v {{ text-align:right; color:{INK}; font-weight:700; font-variant-numeric:tabular-nums; }}

  .empty {{ color:{MUTED}; font-size:13.5px; padding:8px 0; }}
  .empty-day {{ text-align:center; padding:70px 0; font-size:18px; color:{INK2}; }}
  .empty-day span {{ font-size:13px; color:{MUTED}; }}
  circle {{ transition:opacity .12s; }} circle:hover {{ opacity:.7; }}
  footer.rpt {{ margin-top:28px; font-size:11px; color:{MUTED}; text-align:center; }}
  @media (max-width:760px) {{ .stats {{ grid-template-columns:repeat(2,1fr); }} .row2 {{ grid-template-columns:1fr; }} }}
</style></head>
<body><div class="wrap">
  <header class="rpt">
    <div><div class="eyebrow">SMART FACTORY · 식각 공정</div><h1>일일 모니터링 리포트</h1></div>
    <div class="date">{day_label} (KST)</div>
  </header>
  {body}
  <footer class="rpt">반도체 식각 공정 지능형 관제 · 자동 생성 리포트 · inference_log 기반</footer>
</div></body></html>"""


def _load_threshold():
    try:
        import torch
        p = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "models", "autoencoder.pth")
        data = torch.load(p, map_location="cpu", weights_only=False)
        return float(data.get("threshold"))
    except Exception:
        return None


def write_html_report(start, end, out_dir=None):
    proj = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out_dir = out_dir or os.path.join(proj, "reports")
    os.makedirs(out_dir, exist_ok=True)
    day_label = start.astimezone(KST).strftime("%Y-%m-%d")
    thr = _load_threshold()
    stats = fetch_rich_stats(start, end, threshold=thr)
    htmls = build_html(stats, day_label, threshold=thr)
    path = os.path.join(out_dir, f"report_{day_label}.html")
    with open(path, "w", encoding="utf-8") as f:
        f.write(htmls)
    return path


if __name__ == "__main__":
    import sys
    end = datetime.now(tz=KST).replace(hour=0, minute=0, second=0, microsecond=0)
    start = end - timedelta(days=1)
    if len(sys.argv) > 1:
        d = datetime.strptime(sys.argv[1], "%Y-%m-%d").replace(tzinfo=KST)
        start, end = d, d + timedelta(days=1)
    print(write_html_report(start, end))
