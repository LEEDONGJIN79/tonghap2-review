#!/usr/bin/env python3
"""data/ 폴더를 훑어 data/manifest.json을 다시 만든다 (파이썬 3 표준 라이브러리만).

사용법 (어디서 실행해도 된다. 저장소 루트는 이 스크립트 위치 기준 ../ 이다):
    python3 tools/build_manifest.py            # data/manifest.json 쓰기
    python3 tools/build_manifest.py --check    # 쓰지 않고 내용만 검사·요약 출력

읽는 파일:
    data/u{N}_unit.json   단원 정보
    data/u{N}_r{R}.json   회차 세트            (kind 기본값 "round")
    data/mock_{K}.json    실전 모의고사         (kind 기본값 "mock")
    data/boost_{K}.json   보강 세트            (kind 기본값 "boost")
    data/guide.json       처음 사용법 (있으면 manifest.guide가 가리킴)

version = 위 파일들을 이름순으로 정렬해 (파일 이름 + 내용)을 이어 붙인 sha1의 앞 10자리.
sets는 order → id 순, images는 모든 세트 문항의 image를 모아 중복 제거·정렬.
JSON이 깨진 파일이 하나라도 있으면 manifest를 쓰지 않고 종료 코드 1로 끝낸다.
"""
import datetime
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "manifest.json"

RE_UNIT = re.compile(r"^u(\d+)_unit\.json$")
RE_ROUND = re.compile(r"^u(\d+)_r(\d+)\.json$")
RE_MOCK = re.compile(r"^mock_([A-Za-z0-9-]+)\.json$")
RE_BOOST = re.compile(r"^boost_([A-Za-z0-9-]+)\.json$")
KST = datetime.timezone(datetime.timedelta(hours=9))


def load(path):
    with open(path, "rb") as f:
        raw = f.read()
    return raw, json.loads(raw.decode("utf-8-sig"))


def as_int(v, default=None):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def main(argv):
    check_only = "--check" in argv
    if not DATA.is_dir():
        print("data/ 폴더가 없어요:", DATA, file=sys.stderr)
        return 1
    files = sorted(p for p in DATA.iterdir() if p.is_file() and p.suffix == ".json" and p.name != "manifest.json")
    hasher = hashlib.sha1()
    units, sets, errors, warnings = [], [], [], []
    all_images = set()
    guide = None
    for p in files:
        name = p.name
        kind = None
        if RE_UNIT.match(name):
            kind = "unit"
        elif RE_ROUND.match(name):
            kind = "round"
        elif RE_MOCK.match(name):
            kind = "mock"
        elif RE_BOOST.match(name):
            kind = "boost"
        elif name == "guide.json":
            kind = "guide"
        else:
            continue  # 규격 밖 파일은 무시
        try:
            raw, doc = load(p)
        except (ValueError, OSError) as e:
            errors.append(f"{name}: JSON을 읽을 수 없어요 ({e})")
            continue
        hasher.update(name.encode("utf-8") + b"\0" + raw + b"\0")
        if kind == "guide":
            guide = "data/guide.json"
            continue
        if kind == "unit":
            n = as_int(doc.get("unit"), as_int(RE_UNIT.match(name).group(1)))
            concepts = doc.get("concepts") or []
            units.append({
                "unit": n,
                "name": doc.get("name") or f"{n}단원",
                "short": doc.get("short") or f"{n}단원",
                "pages": doc.get("pages") or "",
                "file": f"data/{name}",
                "topics": doc.get("topics") or [],
                "conceptCount": len(concepts),
                "order": as_int(doc.get("order"), n),
            })
            continue
        sid = name[:-5]
        items = doc.get("items") or []
        if not isinstance(items, list):
            errors.append(f"{name}: items가 배열이 아니에요")
            continue
        by_type = {"mc": 0, "short": 0, "essay": 0}
        imgs = []
        ids = set()
        for it in items:
            t = it.get("type")
            if t in by_type:
                by_type[t] += 1
            else:
                warnings.append(f"{name}: {it.get('id')} type '{t}'")
            if it.get("id") in ids:
                warnings.append(f"{name}: 문항 ID 중복 {it.get('id')}")
            ids.add(it.get("id"))
            img = it.get("image")
            if img:
                imgs.append(img)
                if not (ROOT / img).is_file():
                    warnings.append(f"{name}: 이미지 파일 없음 {img}")
        if doc.get("id") and doc.get("id") != sid:
            warnings.append(f"{name}: 파일 이름과 id가 달라요 ({doc.get('id')}) — 파일 이름 기준 {sid}로 씀")
        imgs_sorted = sorted(set(imgs))
        all_images.update(imgs_sorted)
        unit = doc.get("unit")
        if kind == "round":
            m = RE_ROUND.match(name)
            unit = as_int(unit, as_int(m.group(1)))
            rnd = as_int(doc.get("round"), as_int(m.group(2)))
        else:
            unit = as_int(unit)
            rnd = None
        units_list = doc.get("units")
        if not isinstance(units_list, list) or not units_list:
            units_list = sorted({as_int(it.get("unit")) for it in items if as_int(it.get("unit")) is not None}) or ([unit] if unit is not None else [])
        default_order = {"round": (unit or 0) * 10 + (rnd or 0), "mock": 900, "boost": 950}[kind]
        sets.append({
            "id": sid,
            "kind": doc.get("kind") or kind,
            "unit": unit,
            "units": units_list,
            "round": rnd,
            "title": doc.get("title") or sid,
            "subtitle": doc.get("subtitle") or "",
            "order": as_int(doc.get("order"), default_order),
            "file": f"data/{name}",
            "count": len(items),
            "byType": by_type,
            "timeLimitMin": doc.get("timeLimitMin") if doc.get("timeLimitMin") is not None else (50 if kind == "mock" else None),
            "images": imgs_sorted,
        })
    if errors:
        print("manifest를 만들지 않았어요:", file=sys.stderr)
        for e in errors:
            print("  -", e, file=sys.stderr)
        return 1
    units.sort(key=lambda u: (u["order"], u["unit"]))
    sets.sort(key=lambda s: (s["order"], s["id"]))
    manifest = {
        "app": "통합사회2 중간대비",
        "version": hasher.hexdigest()[:10],
        "generatedAt": datetime.datetime.now(KST).replace(microsecond=0).isoformat(),
        "units": units,
        "sets": sets,
        "images": sorted(all_images),
        "guide": guide,
    }
    for w in warnings:
        print("주의:", w, file=sys.stderr)
    summary = f"version {manifest['version']} · 단원 {len(units)} · 세트 {len(sets)} · 문항 {sum(s['count'] for s in sets)} · 이미지 {len(all_images)}"
    if check_only:
        print("(검사만) " + summary)
        return 0
    tmp = OUT.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(OUT)
    print("data/manifest.json 작성: " + summary)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
