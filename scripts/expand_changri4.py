import re
from pathlib import Path
P = Path("bookmadebook-output/讲书稿_长日将尽.txt")
t = P.read_text(encoding="utf-8")
t = re.sub(r"(他这一辈子，最擅长的就是把话咽回去。\n)+", r"\1", t)
if "庄园里没有人提起他父亲" not in t:
    m = re.search(r"(他下楼，继续招待客人。)", t)
    if m:
        t = t[:m.end()] + "\n那天夜里之后，他还照常上工。\n庄园里没有人提起他父亲。\n他也不提。\n那种地方待人接物，就是这样。" + t[m.end():]
if "第一次有人让他为自己做点什么" not in t:
    m = re.search(r"(史蒂文斯答应了。)", t)
    if m:
        t = t[:m.end()] + "\n这是很多年来，第一次有人让他为自己做点什么。" + t[m.end():]
P.write_text(t, encoding="utf-8")
body = re.sub(r"【[^】]*】", "", t)
print("正文净字", len(re.sub(r"\s", "", body)), "| 总", len(t))
