"""감지기 여러 대의 설정 묶음을 만든다.

    python3 tools/make_units.py

학교별 값(와이파이 암호, 감지기 목록 등)은 tools/school.json 에 둔다. 이 파일은 저장소에 올리지 않는다.
없으면 tools/school.example.json 의 값을 쓴다. dist/ 아래에 감지기마다 zip 하나가 생기고,
zip 안의 파일 4개를 그대로 피코에 올리면 된다.
"""
import json
import os
import re
import shutil
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
SRC = os.path.join(ROOT, "firmware")
DIST = os.path.join(ROOT, "dist")


def load_school():
    for name in ("school.json", "school.example.json"):
        path = os.path.join(HERE, name)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                print("설정:", name)
                return json.load(f)
    raise SystemExit("tools/school.example.json 이 없습니다.")


def set_value(cfg, key, value):
    """config.py 안의 `KEY = 값` 한 줄을 바꾼다. 뒤의 주석은 남긴다."""
    text = json.dumps(value, ensure_ascii=False) if isinstance(value, str) else repr(value)
    new, n = re.subn(r"^(%s = )(\"[^\"]*\"|\S+)" % re.escape(key), lambda m: m.group(1) + text, cfg, flags=re.M)
    assert n == 1, "config.py에서 %s 줄을 찾지 못했습니다" % key
    return new


def main():
    school = load_school()
    if os.path.isdir(DIST):
        shutil.rmtree(DIST)
    os.makedirs(DIST)
    base = open(os.path.join(SRC, "config.py"), encoding="utf-8").read()
    for key, value in school.get("common", {}).items():
        base = set_value(base, key, value)
    for unit in school["units"]:
        cfg = base
        for key, value in unit.items():
            cfg = set_value(cfg, key, value)
        name = "%d학년_%s반" % (unit["GRADE"], unit["CLASSES"])
        with zipfile.ZipFile(os.path.join(DIST, name + ".zip"), "w", zipfile.ZIP_DEFLATED) as z:
            z.writestr("config.py", cfg)
            for f in ("main.py", "detect.py", "page.html"):
                z.write(os.path.join(SRC, f), f)
        print(" ", name + ".zip")


if __name__ == "__main__":
    main()
