#!/usr/bin/env python3
"""讲书稿 v4：最后一轮扩写补到 2600+ 字（锚点用正则容错）"""
import re
from pathlib import Path

P = Path("bookmadebook-output/讲书稿_长日将尽.txt")
t = P.read_text(encoding="utf-8")

ADD = [
 (r"(这是把自己活成了一台机器。)", 
  "\n他给自己的解释是：一位管家，无论何时何地，都应该能坚守他的职业生命。\n这句话，他信了一辈子。\n也是这句话，替他挡住了所有他不愿意看见的东西。"),
 (r"(更重要的是，史蒂文斯自己也不想有。|史蒂文斯自己也不想有。)",
  "\n其实两个人都清楚，那不是没有。\n只是谁都不肯先说出来。"),
 (r"(他这一辈子，最擅长的就是把话咽回去。|他此刻最擅长的)",
  "\n他这一辈子，最擅长的就是把话咽回去。"),
 (r"(想了几十年，还是不知道该怎么说。|想了几十年)",
  "\n他这一辈子，最擅长的就是把话咽回去。\n车窗外是英国最好的季节。\n可他心里翻来覆去，全是三十年前那些没说出口的句子。"),
 (r"(那一刻，史蒂文斯的心，碎了。|这一刻，史蒂文斯的心，碎了。)",
  "\n她说这句话的时候，很平静。\n反倒比他更勇敢。\n三十年前，他没敢回答她。\n三十年后，她替他回答了。"),
]
for pat, add in ADD:
    m = re.search(pat, t)
    if not m:
        print("⚠️ 未匹配:", pat[:30]); continue
    if add.strip("\n").split("\n")[0] in t:
        continue
    t = t[:m.end()] + add + t[m.end():]

P.write_text(t, encoding="utf-8")
body = re.sub(r"【[^】]*】", "", t)
print("长度", len(t), "| 正文净字", len(re.sub(r"\s", "", body)))
