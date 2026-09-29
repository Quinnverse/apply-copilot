#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""网申助手 · 公司名规范化与同主体匹配（共用模块）

从 server.py 抽出，供 server.py 与 refresh_queue.py 共用，避免循环 import。

匹配原则（刻意保守）：
  * 规范化（NFKC + 去首尾空格）后精确相等；或
  * 同属 COMPANY_ALIAS 里显式登记的别名分组。
  * 刻意不做子串包含兜底 —— 否则"腾讯"会误配"腾讯音乐娱乐"。
    同主体的不同写法必须显式登记到 COMPANY_ALIAS 才生效。
"""
import unicodedata


def norm_company(s):
    """规范化公司名：去首尾空格、统一全角/半角（NFKC）。"""
    s = (s or "").strip()
    try:
        s = unicodedata.normalize("NFKC", s)
    except Exception:
        pass
    return s


# 同主体不同写法的显式白名单：只有登记在这里的才算同一家公司。
# 登记原则：仅收"确实是同一法人主体的常见简称/全称/英文名"；
# 不同上市主体（如 腾讯音乐娱乐 / 字节跳动旗下独立品牌）不得并进同一组。
COMPANY_ALIAS = {
    "字节跳动": ["字节", "字节跳动", "字节跳动 ByteDance", "ByteDance", "ByeDance"],
    "腾讯科技": ["腾讯", "腾讯科技", "Tencent", "深圳市腾讯计算机系统有限公司"],
    "阿里巴巴": ["阿里", "阿里巴巴", "阿里巴巴集团", "Alibaba"],
    "百度": ["百度", "百度在线", "Baidu"],
    "美团": ["美团", "美团点评", "Meituan"],
    "京东": ["京东", "京东集团", "JD"],
    "网易": ["网易", "NetEase"],
    "小米": ["小米", "小米科技", "Xiaomi"],
    "华为": ["华为", "华为技术", "Huawei"],
    "商汤科技": ["商汤", "商汤科技", "SenseTime"],
    "银河通用": ["银河通用", "银河通用 Galbot", "Galbot"],
    # 以下为真实数据里已出现的"已记录简称 vs seed 全称"同主体对（不登记会导致
    # 已投递过的公司被误判成未投递）。新增公司时按需补登记。
    "天演资本": ["天演", "天演资本"],
    "宽德投资": ["宽德", "宽德投资"],
    "明汯投资": ["明汯", "明汯投资"],
}


def alias_groups(name):
    """返回公司名所属的别名分组名集合（规范化后比较），未登记则为空集。"""
    n = norm_company(name)
    if not n:
        return set()
    groups = set()
    for group, members in COMPANY_ALIAS.items():
        if n in {norm_company(m) for m in members}:
            groups.add(group)
    return groups


def company_matches(a, b):
    """公司名匹配：① 规范化后精确相等；② 同属一个 COMPANY_ALIAS 显式分组。"""
    a2, b2 = norm_company(a), norm_company(b)
    if not a2 or not b2:
        return False
    if a2 == b2:
        return True
    return bool(alias_groups(a2) & alias_groups(b2))


def company_tokens(name):
    """从公司名（含别名）里提取可用于 host 模糊反查的 ascii 词元（len>=3）。

    例："银河通用 Galbot" → {"galbot"}。用于「页面上只有域名可参考」的场景，
    判断 host（如 talent.galbot.com）是否包含公司词元。仅 ascii 词元参与，
    避免中文误命中；且要求 len>=3 减少误报（如 "jd" 不参与 host 反查）。
    """
    tokens = set()
    for m in [name] + [x for ms in COMPANY_ALIAS.values() for x in ms
                       if norm_company(name) == norm_company(x)]:
        for tok in re_split_ascii(m):
            if len(tok) >= 3:
                tokens.add(tok.lower())
    return tokens


def re_split_ascii(s):
    """按非 ascii 字母/数字切分，返回纯 ascii 词元列表。"""
    import re
    return [t for t in re.split(r"[^A-Za-z0-9]+", s or "") if t]


# 兼容旧名（server.py 历史内部名）
_norm_company = norm_company
_alias_groups = alias_groups
