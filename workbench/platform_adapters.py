#!/usr/bin/env python3
"""N-07：平台适配器——把「探测/列题/详情/提交」的平台知识收敛到注册表。

competition.json 的 platform 段新增可选字段 `adapter`（"ctfd" | "buuctf"）：
- 声明后，适配器的缺省配置（列题端点/详情端点/提交形态）会填进 platform 段，
  显式配置优先、不被覆盖——即使探测失败，抓题与附件下载仍可开箱工作。
- 未声明时沿用既有的纯配置驱动流程，完全向后兼容。
零第三方依赖；新增平台 = 新增一个 Adapter 子类 + 注册进 ADAPTERS。
"""
from __future__ import annotations


class PlatformAdapter:
    name = ""
    #: 该平台的合理缺省：challenges / challenge_detail / submit 等配置段
    defaults: dict = {}

    def apply_defaults(self, platform: dict) -> dict:
        """把缺省配置合并进 platform 段（已存在的显式配置一律不覆盖）。"""
        out = dict(platform)
        for key, value in self.defaults.items():
            if not out.get(key):
                out[key] = value
        return out


class CTFdAdapter(PlatformAdapter):
    """CTFd 标准形态：token 直连 /api/v1/challenges。"""

    name = "ctfd"
    defaults = {
        "challenges": {"method": "GET", "path": "/api/v1/challenges", "items_field": "data",
                       "map": {"id": "id", "name": "name", "category": "category",
                               "points": "value"}},
        "challenge_detail": {"path": "/api/v1/challenges/{id}", "files_field": "data.files"},
        "submit": {"method": "POST",
                   "path": "/api/v1/challenges/{challenge_id}/attempt",
                   "content_type": "application/json",
                   "body_template": '{"challenge_id": "{challenge_id}", "submission": "{flag}"}',
                   "success": {"field": "data.status", "equals": "correct"}},
    }


class BUUCTFAdapter(CTFdAdapter):
    """BUUCTF（buuoj.cn）：列表走 .cache 会话形态，提交/详情沿用 CTFd 端点。"""

    name = "buuctf"
    defaults = {
        **CTFdAdapter.defaults,
        "challenges": {"method": "GET", "path": "/api/v1/challenges.cache", "items_field": "data",
                       "map": {"id": "id", "name": "name", "category": "category",
                               "points": "value"}},
    }


ADAPTERS: dict[str, PlatformAdapter] = {a.name: a for a in (CTFdAdapter(), BUUCTFAdapter())}


def get_adapter(platform: dict) -> PlatformAdapter | None:
    """按 platform.adapter 取适配器；未声明/未知返回 None（保持旧行为）。"""
    name = str((platform or {}).get("adapter") or "").strip().lower()
    return ADAPTERS.get(name)
