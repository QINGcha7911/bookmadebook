#!/usr/bin/env python3
"""bookmadebook 内容安全过滤器

两种模式：
- kids_mode: 儿童/青少年（严格过滤：暴力、死亡、恐怖、成人内容）
- adult_mode: 成人（宽松过滤，仅拦截违法内容）

用法：
    from content_filter import ContentFilter
    cf = ContentFilter("kids")
    result = cf.check("这里有一段内容...")
    # result = {"safe": True/False, "hits": ["暴力", ...], "reason": "..."}
"""

import re

class ContentFilter:
    def __init__(self, mode="kids"):
        """
        mode: "kids" 儿童青少年严格模式 | "adult" 成人宽松模式
        """
        self.mode = mode
        
        # 严格模式关键词（儿童青少年禁用）
        self.kids_blocked = {
            "暴力": ["杀人", "杀死", "谋杀", "屠杀", "凶杀", "肢解", "碎尸", "虐杀", "暴力", "殴打", "虐待"],
            "死亡": ["死亡", "死了", "自杀", "自尽", "上吊", "跳楼", "割腕", "轻生", "去世", "尸体", "遗骸"],
            "恐怖": ["鬼", "幽灵", "恶魔", "地狱", "恐怖", "惊悚", "吓人", "阴森", "诅咒", "血腥"],
            "成人": ["色情", "性爱", "做爱", "上床", "裸体", "色情片", "嫖娼", "卖淫", "强奸", "性侵"],
            "毒品": ["毒品", "吸毒", "海洛因", "冰毒", "大麻", "摇头丸", "贩毒"],
            "犯罪": ["犯罪", "抢劫", "绑架", "诈骗", "走私", "盗窃", "越狱", "杀人犯"],
            "敏感政治": ["颠覆", "政变", "暴动", "叛乱", "分裂国家"],
        }
        
        # 宽松模式关键词（成人仅拦截违法内容）
        self.adult_blocked = {
            "违法": ["贩毒", "制毒", "买卖枪支", "制造炸弹", "恐怖袭击", "刺杀"],
        }
        
        # 亲子模式额外提示
        self.parent_warning_keywords = ["爱情", "恋爱", "分手", "结婚", "离婚", "怀孕", "欺骗", "背叛"]
    
    def check(self, text: str) -> dict:
        """
        检查内容安全性。
        返回: {"safe": bool, "mode": str, "hits": [分类:词], "reason": str}
        """
        if not text:
            return {"safe": True, "mode": self.mode, "hits": [], "reason": "内容为空"}
        
        blocked = self.kids_blocked if self.mode == "kids" else self.adult_blocked
        hits = []
        
        for category, keywords in blocked.items():
            for kw in keywords:
                if kw in text:
                    hits.append(f"{category}:{kw}")
        
        if hits:
            return {
                "safe": False,
                "mode": self.mode,
                "hits": hits[:10],
                "reason": f"检测到不适内容：{', '.join(hits[:5])}",
            }
        
        # 亲子模式额外提醒（不阻断，仅提示家长）
        warnings = []
        if self.mode == "kids":
            for kw in self.parent_warning_keywords:
                if kw in text:
                    warnings.append(kw)
        
        if warnings:
            return {
                "safe": True,
                "mode": self.mode,
                "hits": [],
                "warnings": warnings,
                "reason": f"含需家长注意的内容词：{', '.join(warnings)}（已放行，建议家长陪听）",
            }
        
        return {"safe": True, "mode": self.mode, "hits": [], "reason": "内容安全"}


if __name__ == "__main__":
    # 自测
    print("=== 儿童模式测试 ===")
    cf = ContentFilter("kids")
    
    test_cases = [
        "今天天气很好，我们去公园玩。",
        "这个童话讲的是公主和王子幸福地生活在一起。",
        "恐怖故事：深夜里，一只鬼出现在走廊里。",
        "这本书讲了战争中的杀人事件。",
        "小说里描写了主角的恋爱故事。",
        "这是一本关于毒品危害的科普书。",
    ]
    
    for t in test_cases:
        r = cf.check(t)
        status = "✅ 安全" if r["safe"] else "🚫 拦截"
        print(f"  {status} | {r['reason']} | {t[:20]}...")
    
    print("\n=== 成人模式测试 ===")
    cf2 = ContentFilter("adult")
    for t in test_cases:
        r = cf2.check(t)
        status = "✅ 安全" if r["safe"] else "🚫 拦截"
        print(f"  {status} | {r['reason']} | {t[:20]}...")
