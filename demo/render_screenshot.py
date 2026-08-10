# -*- coding: utf-8 -*-
"""
실행이 끝난 데모 노트북의 stdout 을 읽어 터미널 모양 PNG 로 그린다.

왜 필요한가:
    README 에 넣을 실행 증거가 필요한데, 노트북 셀 출력을 그대로 복사하면
    코드 블록이 되어 버리고 창을 캡처하면 바탕화면이 함께 찍힌다.
    여기서는 **실제로 실행되어 .ipynb 에 저장된 출력 텍스트**만 뽑아 이미지로 만든다.
    없는 내용을 지어내지 않으므로, 노트북을 다시 실행하면 이미지도 그대로 재생성된다.

한글 정렬:
    Consolas 에는 한글 글자가 없고 맑은 고딕은 고정폭이 아니다.
    그래서 글자 단위로 폰트를 갈라 쓰고, 동아시아 전각 문자는 2칸을 차지하도록
    직접 커서를 움직인다. 덕분에 ASCII 표가 한글 문장과 섞여도 열이 맞는다.

사용법:
    python demo/render_screenshot.py
"""
from __future__ import annotations

import unicodedata
from pathlib import Path

import nbformat as nbf
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DEMO = ROOT / "demo"
OUT = ROOT / "docs" / "images"

FONT_MONO = r"C:\Windows\Fonts\consola.ttf"   # ASCII — 고정폭
FONT_KR = r"C:\Windows\Fonts\malgun.ttf"      # 한글 — 맑은 고딕

SIZE = 15
COLS = 96
PAD = 24
TITLEBAR = 36
LINE_H = int(SIZE * 1.58)

BG = "#1e1e2e"
FG = "#cdd6f4"
TITLE_BG = "#181825"
TITLE_FG = "#a6adc8"
DIM = "#6c7086"
GREEN = "#a6e3a1"
BLUE = "#89b4fa"
YELLOW = "#f9e2af"
MAUVE = "#cba6f7"

DOTS = ["#ff5f56", "#ffbd2e", "#27c93f"]


# ---------------------------------------------------------------- 폭 계산
def _wide(ch: str) -> bool:
    return unicodedata.east_asian_width(ch) in ("W", "F")


def _wrap(line: str, cols: int) -> list[str]:
    """전각을 2칸으로 세면서 cols 칸에 맞춰 접는다. 이어지는 줄은 3칸 들여쓴다."""
    out: list[str] = []
    cur, w = "", 0
    limit = cols
    for ch in line:
        cw = 2 if _wide(ch) else 1
        if w + cw > limit:
            out.append(cur)
            cur, w = "   ", 3          # 연속 줄임을 표시
            limit = cols
        cur += ch
        w += cw
    out.append(cur)
    return out or [""]


def _color_for(line: str) -> str:
    s = line.strip()
    if not s:
        return FG
    if s.startswith("OK"):
        return GREEN
    if s.startswith("PEAK") or s.startswith("saved"):
        return YELLOW
    if s.startswith("["):
        return BLUE
    if s.startswith("#") and not s.startswith("# "):
        return DIM
    if set(s) <= {"-", "="}:
        return DIM
    if s.startswith("$"):
        return GREEN
    if s.startswith("//"):
        return MAUVE
    return FG


# ---------------------------------------------------------------- 노트북 읽기
def cell_stdout(nb, index: int) -> list[str]:
    """해당 코드 셀의 stdout 을 줄 리스트로 돌려준다(stderr 는 버린다)."""
    cell = nb.cells[index]
    text = "".join(
        o.get("text", "")
        for o in cell.get("outputs", [])
        if o.get("output_type") == "stream" and o.get("name") == "stdout"
    )
    return text.rstrip("\n").split("\n") if text.strip() else []


def clip(lines: list[str], max_lines: int | None) -> list[str]:
    if max_lines is None or len(lines) <= max_lines:
        return lines
    return lines[:max_lines] + ["", f"   ... ({len(lines) - max_lines} lines omitted)"]


# ---------------------------------------------------------------- 그리기
def _draw_row(d, x: float, baseline: float, text: str, mono, kr, cw: float, fill: str) -> None:
    """글자마다 폰트를 갈라 쓰고, 전각은 두 칸을 차지하도록 커서를 밀어 준다."""
    for ch in text:
        if ch != " ":
            d.text((x, baseline), ch, font=(kr if _wide(ch) else mono),
                   fill=fill, anchor="ls")
        x += cw * (2 if _wide(ch) else 1)


def render(lines: list[str], title: str, dest: Path) -> None:
    mono = ImageFont.truetype(FONT_MONO, SIZE)
    kr = ImageFont.truetype(FONT_KR, SIZE)
    cw = mono.getlength("M")
    ascent = mono.getmetrics()[0]

    wrapped: list[str] = []
    for ln in lines:
        wrapped.extend(_wrap(ln.rstrip(), COLS))

    w = int(PAD * 2 + cw * COLS)
    h = int(TITLEBAR + PAD * 2 + LINE_H * len(wrapped))

    img = Image.new("RGB", (w, h), BG)
    d = ImageDraw.Draw(img)

    # 타이틀바
    d.rectangle([0, 0, w, TITLEBAR], fill=TITLE_BG)
    for i, c in enumerate(DOTS):
        cx = 18 + i * 18
        d.ellipse([cx - 5, TITLEBAR // 2 - 5, cx + 5, TITLEBAR // 2 + 5], fill=c)
    # 타이틀에도 한글이 들어가므로 본문과 같은 방식으로 그린다
    _draw_row(d, 84, TITLEBAR // 2 + SIZE // 2 - 1, title, mono, kr, cw, TITLE_FG)

    # 본문
    y = TITLEBAR + PAD
    for ln in wrapped:
        _draw_row(d, PAD, y + ascent, ln, mono, kr, cw, _color_for(ln))
        y += LINE_H

    dest.parent.mkdir(parents=True, exist_ok=True)
    img.save(dest)
    print(f"saved {dest.relative_to(ROOT)}  ({w}x{h}, {len(wrapped)} lines)")


# ---------------------------------------------------------------- 어떤 셀을 어느 그림에
# (파일명, 타이틀, [(노트북, 셀 index, 최대 줄수, 캡션), ...])
SPEC = [
    (
        "demo1-minimal.png",
        "demo/01_llm_minimal.ipynb",
        [
            ("01_llm_minimal.ipynb", 1, None, "// [0] 환경 준비"),
            ("01_llm_minimal.ipynb", 3, None, "// [1] raw openai SDK - 최소 호출"),
            ("01_llm_minimal.ipynb", 5, 14, "// [2] SHAPAgent - 프로젝트 LangChain 경로"),
            ("01_llm_minimal.ipynb", 7, None, "// [3] 비용 요약"),
        ],
    ),
    (
        "demo2-pipeline-front.png",
        "demo/02_full_pipeline.ipynb  (1/2)  센서 -> 추론 -> SHAP",
        [
            ("02_full_pipeline.ipynb", 3, None, "// [1/5] 3-소스 병합"),
            ("02_full_pipeline.ipynb", 5, None, "// [2/5] AutoEncoder + LightGBM 추론"),
            ("02_full_pipeline.ipynb", 7, None, "// [3/5] SHAP 기여 센서 Top-5"),
        ],
    ),
    (
        "demo2-llm-answer.png",
        "demo/02_full_pipeline.ipynb  (2/2)  LLM -> GraphRAG",
        [
            ("02_full_pipeline.ipynb", 10, 12, "// [4/5] SHAPAgent - LLM 원인 해설"),
            ("02_full_pipeline.ipynb", 12, None, "// [5/5] GraphRAG V2 - KG 조회 + 정비 지침"),
            ("02_full_pipeline.ipynb", 14, None, "// 요약"),
        ],
    ),
]


def main() -> None:
    cache: dict[str, object] = {}
    for fname, title, blocks in SPEC:
        lines: list[str] = []
        for nb_name, idx, limit, caption in blocks:
            if nb_name not in cache:
                cache[nb_name] = nbf.read(str(DEMO / nb_name), as_version=4)
            body = clip(cell_stdout(cache[nb_name], idx), limit)
            if not body:
                raise SystemExit(
                    f"{nb_name} 셀 {idx} 에 stdout 이 없다. 노트북을 먼저 실행할 것."
                )
            if lines:
                lines.append("")
            lines.append(caption)
            lines.append("")
            lines.extend(body)
        render(lines, title, OUT / fname)


if __name__ == "__main__":
    main()
