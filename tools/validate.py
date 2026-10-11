#!/usr/bin/env python3
"""data/ 폴더 전체를 출제 규격(스키마)대로 검사한다 (파이썬 3 표준 라이브러리만).

사용법 (어디서 실행해도 된다. 저장소 루트는 이 스크립트 위치 기준 ../ 이다):
    python3 tools/validate.py              # data/ 전체 검사
    python3 tools/validate.py data/u2_r1.json data/u2_unit.json   # 지정한 파일만(단원 정보는 자동으로 함께 읽음)
    python3 tools/validate.py --strict     # 경고도 오류로 친다

검사 항목
- 단원 정보(u{N}_unit.json): unit·name·topics·concepts, 개념 ID 형식(u{N}-t{주제}-c{두자리}), 중복, importance(상·중·하)
- 세트(u{N}_r{R}.json, mock_*.json, boost_*.json): id = 파일 이름, kind, items
- 문항: 필수 필드, ID 형식과 단원 접두어, 세트를 넘나드는 문항 ID 중복, method A~O, difficulty, type,
  mc(선지 5개·정답 1~5·wrongReasons 5개), short(accept 또는 blanks), essay(modelAnswer·rubric),
  conceptId가 단원 정보에 있는지, image 파일이 실제로 있는지, 금지 마크업(script·style·on* 속성·외부 링크)
- manifest.json이 있으면 data/의 세트를 모두 담고 있는지(빠졌으면 build_manifest.py를 다시 돌리라고 알림)
종료 코드: 오류가 있으면 1, 없으면 0
"""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

RE_UNIT = re.compile(r"^u(\d+)_unit\.json$")
RE_ROUND = re.compile(r"^u(\d+)_r(\d+)\.json$")
RE_MOCK = re.compile(r"^mock_([A-Za-z0-9-]+)\.json$")
RE_BOOST = re.compile(r"^boost_([A-Za-z0-9-]+)\.json$")
RE_CONCEPT = re.compile(r"^u(\d+)-t(\d+)-c(\d{2})$")
RE_ITEM_ROUND = re.compile(r"^u(\d+)-r(\d+)-t(\d+)-(\d{2})$")
RE_ITEM_OTHER = re.compile(r"^(mock|boost)[A-Za-z0-9]*-\d{2,3}$")
RE_ITEM_SAMPLE = re.compile(r"^u(\d+)-sample-\d{2}$")
METHODS = set("ABCDEFGHIJKLMNO")
MC_METHODS = set("ABCDEFGHIJK")
ESSAY_METHODS = set("MNO")
DIFF = {"하", "중", "상"}
TYPES = {"mc", "short", "essay"}
KINDS = {"round", "mock", "boost"}
BANNED = [
    (re.compile(r"<\s*script", re.I), "script 태그"),
    (re.compile(r"<\s*style", re.I), "style 태그"),
    (re.compile(r"\son[a-z]+\s*=", re.I), "on* 속성"),
    (re.compile(r"\sstyle\s*=", re.I), "인라인 style"),
    (re.compile(r"<\s*a\s", re.I), "링크(a) 태그"),
    (re.compile(r"<\s*iframe", re.I), "iframe"),
    (re.compile(r"javascript:", re.I), "javascript: 주소"),
]
HTML_FIELDS = ["stem", "passage", "explanation", "modelAnswer", "trap", "imageCaption"]

errors, warnings = [], []


def err(where, msg):
    errors.append(f"[오류] {where}: {msg}")


def warn(where, msg):
    warnings.append(f"[경고] {where}: {msg}")


def load(p):
    try:
        return json.loads(p.read_text(encoding="utf-8-sig"))
    except Exception as e:  # noqa: BLE001
        err(p.name, f"JSON을 읽을 수 없음 ({e})")
        return None


def check_html(where, text):
    if not isinstance(text, str):
        return
    for rx, label in BANNED:
        if rx.search(text):
            err(where, f"금지 마크업: {label}")


def check_unit(p, d, unit_from_name):
    w = p.name
    if not isinstance(d, dict):
        err(w, "객체가 아님")
        return None
    if d.get("unit") != unit_from_name:
        err(w, f"unit 값({d.get('unit')})이 파일 이름의 단원({unit_from_name})과 다름")
    for k in ("name", "topics", "concepts"):
        if k not in d:
            err(w, f"필드 없음: {k}")
    topics = {t.get("topic") for t in d.get("topics", []) if isinstance(t, dict)}
    seen = set()
    concepts = {}
    for c in d.get("concepts", []):
        cid = c.get("conceptId", "")
        m = RE_CONCEPT.match(cid or "")
        if not m:
            err(w, f"개념 ID 형식 오류: {cid!r} (u{{단원}}-t{{주제}}-c{{두자리}})")
            continue
        if int(m.group(1)) != unit_from_name:
            err(w, f"개념 ID의 단원 접두어가 다름: {cid}")
        if c.get("topic") != int(m.group(2)):
            err(w, f"{cid}: topic 값({c.get('topic')})이 ID의 주제와 다름")
        if c.get("topic") not in topics:
            err(w, f"{cid}: topics 목록에 없는 주제 {c.get('topic')}")
        if cid in seen:
            err(w, f"개념 ID 중복: {cid}")
        seen.add(cid)
        if c.get("importance") not in DIFF:
            err(w, f"{cid}: importance는 상·중·하 중 하나")
        if not c.get("name"):
            err(w, f"{cid}: name 없음")
        concepts[cid] = c
    return concepts


def check_item(where, it, set_kind, unit_concepts, all_ids, set_units):
    if not isinstance(it, dict):
        err(where, "문항이 객체가 아님")
        return
    iid = it.get("id", "")
    w = f"{where} {iid}"
    for k in ("id", "unit", "topic", "conceptId", "concept", "method", "difficulty", "type", "stem",
              "explanation", "pages", "trap"):
        if k not in it or it[k] in (None, "") and k not in ("trap",):
            err(w, f"필드 없음/빈 값: {k}")
    for k in ("passage", "image", "imageCaption", "round"):
        if k not in it:
            warn(w, f"필드 없음: {k} (빈 값이라도 넣기 권장)")
    # ID
    if iid in all_ids:
        err(w, f"문항 ID 중복 (다른 곳: {all_ids[iid]})")
    all_ids[iid] = where
    m = RE_ITEM_ROUND.match(iid or "")
    if m:
        if int(m.group(1)) != it.get("unit"):
            err(w, "문항 ID의 단원 접두어와 unit 값이 다름")
        if it.get("round") is not None and int(m.group(2)) != it.get("round"):
            err(w, "문항 ID의 회차와 round 값이 다름")
        if int(m.group(3)) != it.get("topic"):
            err(w, "문항 ID의 주제와 topic 값이 다름")
    elif not (RE_ITEM_OTHER.match(iid or "") or RE_ITEM_SAMPLE.match(iid or "")):
        err(w, "문항 ID 형식 오류 (u{단원}-r{회차}-t{주제}-{두자리}, mock{K}-NN, boost{K}-NN)")
    if set_kind == "round" and it.get("unit") not in set_units:
        err(w, f"세트의 units {set_units}에 없는 단원 {it.get('unit')}")
    # 개념
    cid = it.get("conceptId")
    cmap = unit_concepts.get(it.get("unit"))
    if cmap is None:
        err(w, f"단원 {it.get('unit')}의 단원 정보 파일(u{it.get('unit')}_unit.json)이 없음")
    elif cid not in cmap:
        err(w, f"conceptId {cid}가 단원 정보 파일에 없음")
    else:
        if cmap[cid].get("topic") != it.get("topic"):
            err(w, f"topic({it.get('topic')})이 개념 {cid}의 주제({cmap[cid].get('topic')})와 다름")
    # 분류
    meth, typ = it.get("method"), it.get("type")
    if meth not in METHODS:
        err(w, f"method는 A~O 중 하나 (지금 {meth!r})")
    if it.get("difficulty") not in DIFF:
        err(w, f"difficulty는 하·중·상 중 하나 (지금 {it.get('difficulty')!r})")
    if typ not in TYPES:
        err(w, f"type은 mc·short·essay 중 하나 (지금 {typ!r})")
    if typ == "mc" and meth not in MC_METHODS:
        warn(w, f"선택형인데 method가 {meth}")
    if typ == "short" and meth != "L":
        warn(w, f"단답형인데 method가 {meth}")
    if typ == "essay" and meth not in ESSAY_METHODS:
        warn(w, f"서술형인데 method가 {meth}")
    # 형식별
    if typ == "mc":
        ch = it.get("choices")
        if not (isinstance(ch, list) and len(ch) == 5 and all(isinstance(c, str) and c.strip() for c in ch)):
            err(w, "choices는 빈칸 없는 문자열 5개")
        else:
            for c in ch:
                check_html(w + " choices", c)
                if re.match(r"^\s*[①②③④⑤]", c):
                    warn(w, "선지 앞에 번호 기호가 들어 있음(앱이 번호를 붙임)")
        if not (isinstance(it.get("answer"), int) and 1 <= it["answer"] <= 5):
            err(w, "answer는 1~5 정수")
        wr = it.get("wrongReasons")
        if not (isinstance(wr, list) and len(wr) == 5):
            err(w, "wrongReasons는 5개")
    elif typ == "short":
        blanks = it.get("blanks")
        if blanks:
            if not all(isinstance(b, dict) and b.get("label") and isinstance(b.get("accept"), list) and b["accept"] for b in blanks):
                err(w, "blanks는 [{label, accept[…]}] 형식")
        elif not (isinstance(it.get("accept"), list) and it["accept"]):
            err(w, "단답형은 accept[] 또는 blanks 필요")
        if not it.get("answer"):
            err(w, "단답형 answer(대표 정답 문자열) 없음")
    elif typ == "essay":
        if not it.get("modelAnswer"):
            err(w, "서술형 modelAnswer 없음")
        rb = it.get("rubric")
        if not (isinstance(rb, list) and rb and all(isinstance(r, dict) and r.get("criterion") and isinstance(r.get("points"), (int, float)) and r["points"] > 0 for r in rb)):
            err(w, "rubric은 [{criterion, points>0}] 1개 이상")
    # 이미지
    img = it.get("image")
    if img:
        if not isinstance(img, str) or img.startswith("/") or "://" in img:
            err(w, f"image는 저장소 기준 상대 경로 (지금 {img!r})")
        elif not (ROOT / img).is_file():
            err(w, f"이미지 파일 없음: {img}")
        elif not re.match(rf"^images/u{it.get('unit')}/", img) and set_kind == "round":
            warn(w, f"이미지가 images/u{it.get('unit')}/ 아래가 아님: {img}")
    # 마크업
    for k in HTML_FIELDS:
        check_html(f"{w} {k}", it.get(k))
    for r in it.get("wrongReasons") or []:
        check_html(f"{w} wrongReasons", r)
    pts = it.get("points")
    if pts is not None and not (isinstance(pts, (int, float)) and pts > 0):
        err(w, "points는 양수")


def main(argv):
    strict = "--strict" in argv
    targets = [a for a in argv if not a.startswith("--")]
    if not DATA.is_dir():
        print("data/ 폴더가 없어요:", DATA)
        return 1
    all_files = sorted(p for p in DATA.glob("*.json") if p.name not in ("manifest.json", "guide.json"))
    # 단원 정보는 항상 전부 읽는다
    unit_concepts = {}
    for p in all_files:
        m = RE_UNIT.match(p.name)
        if m:
            d = load(p)
            if d is not None:
                c = check_unit(p, d, int(m.group(1)))
                if c is not None:
                    unit_concepts[int(m.group(1))] = c
    if targets:
        sel = []
        for t in targets:
            p = pathlib.Path(t)
            p = p if p.is_absolute() else (pathlib.Path.cwd() / p)
            if not p.exists():
                p = DATA / pathlib.Path(t).name
            sel.append(p.resolve())
        set_files = [p for p in sel if not RE_UNIT.match(p.name)]
    else:
        set_files = [p for p in all_files if not RE_UNIT.match(p.name)]
    all_ids = {}
    # 다른 세트의 ID도 중복 검사에 넣기 위해 지정 검사여도 전체 ID를 먼저 모은다
    if targets:
        for p in all_files:
            if RE_UNIT.match(p.name) or p.resolve() in [s.resolve() for s in set_files]:
                continue
            d = load(p)
            if isinstance(d, dict):
                for it in d.get("items", []):
                    if isinstance(it, dict) and it.get("id"):
                        all_ids[it["id"]] = p.name
    counts = {}
    for p in set_files:
        name = p.name
        if not (RE_ROUND.match(name) or RE_MOCK.match(name) or RE_BOOST.match(name)):
            warn(name, "알 수 없는 파일 이름 (u{N}_r{R}.json, mock_K.json, boost_K.json만 세트로 읽힘)")
            continue
        d = load(p)
        if not isinstance(d, dict):
            continue
        sid = name[:-5]
        if d.get("id") != sid:
            err(name, f"세트 id({d.get('id')})가 파일 이름({sid})과 다름")
        kind = d.get("kind") or ("round" if RE_ROUND.match(name) else "mock" if RE_MOCK.match(name) else "boost")
        if kind not in KINDS:
            err(name, f"kind는 round·mock·boost 중 하나 (지금 {kind!r})")
        mr = RE_ROUND.match(name)
        if mr:
            if d.get("unit") != int(mr.group(1)):
                err(name, "unit 값이 파일 이름과 다름")
            if d.get("round") != int(mr.group(2)):
                err(name, "round 값이 파일 이름과 다름")
        units = d.get("units") or ([d.get("unit")] if d.get("unit") else [])
        if not d.get("title"):
            err(name, "title 없음")
        items = d.get("items")
        if not isinstance(items, list) or not items:
            err(name, "items가 비어 있음")
            continue
        for it in items:
            check_item(name, it, kind, unit_concepts, all_ids, units)
        if kind == "mock" and not d.get("timeLimitMin"):
            warn(name, "실전 모의인데 timeLimitMin 없음")
        by = {}
        for it in items:
            by[it.get("type")] = by.get(it.get("type"), 0) + 1
        counts[sid] = (len(items), by)
    # manifest 대조
    mpath = DATA / "manifest.json"
    if mpath.exists() and not targets:
        try:
            man = json.loads(mpath.read_text(encoding="utf-8"))
            listed = {s.get("id") for s in man.get("sets", [])}
            missing = sorted(set(counts) - listed)
            if missing:
                warn("manifest.json", f"세트가 빠져 있음 {missing} → python3 tools/build_manifest.py 를 다시 돌리세요")
            for s in man.get("sets", []):
                if s.get("id") in counts and s.get("count") != counts[s["id"]][0]:
                    warn("manifest.json", f"{s['id']} 문항 수가 실제와 다름 → build_manifest.py 다시 실행")
        except Exception as e:  # noqa: BLE001
            err("manifest.json", f"읽을 수 없음 ({e})")
    for sid, (n, by) in sorted(counts.items()):
        print(f"  {sid}: {n}문항 {by}")
    for line in errors + warnings:
        print(line)
    n_err = len(errors) + (len(warnings) if strict else 0)
    print(f"검사 끝: 세트 {len(counts)}개, 단원 정보 {len(unit_concepts)}개, 오류 {len(errors)}건, 경고 {len(warnings)}건")
    return 1 if n_err else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
