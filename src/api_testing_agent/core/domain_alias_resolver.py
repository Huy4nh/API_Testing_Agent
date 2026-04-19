from __future__ import annotations

import re
from dataclasses import dataclass, field

from api_testing_agent.core.models import HttpMethod


@dataclass(frozen=True)
class DomainAliasRule:
    name: str
    patterns: list[str]
    tags: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    methods: list[HttpMethod] = field(default_factory=list)
    extra_tokens: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ResolvedDomainIntent:
    tags: list[str] = field(default_factory=list)
    paths: list[str] = field(default_factory=list)
    methods: list[HttpMethod] = field(default_factory=list)
    extra_tokens: list[str] = field(default_factory=list)


class DomainAliasResolver:
    def __init__(self, rules: list[DomainAliasRule] | None = None) -> None:
        self._rules = rules if rules is not None else self._default_rules()

    @classmethod
    def empty(cls) -> "DomainAliasResolver":
        return cls(rules=[])

    def resolve(self, searchable_text: str) -> ResolvedDomainIntent:
        tags: list[str] = []
        paths: list[str] = []
        methods: list[HttpMethod] = []
        extra_tokens: list[str] = []

        for rule in self._rules:
            if self._matches_any(rule.patterns, searchable_text):
                tags.extend(rule.tags)
                paths.extend(rule.paths)
                methods.extend(rule.methods)
                extra_tokens.extend(rule.extra_tokens)

        return ResolvedDomainIntent(
            tags=self._unique_preserve_order(tags),
            paths=self._unique_preserve_order(paths),
            methods=self._unique_preserve_order(methods),
            extra_tokens=self._unique_preserve_order(extra_tokens),
        )

    def _matches_any(self, patterns: list[str], searchable_text: str) -> bool:
        for pattern in patterns:
            if re.search(pattern, searchable_text, flags=re.IGNORECASE):
                return True
        return False

    def _unique_preserve_order(self, values: list) -> list:
        return list(dict.fromkeys(values))

    def _default_rules(self) -> list[DomainAliasRule]:
        return [
            # ===== Generic CMS-like aliases =====
            DomainAliasRule(
                name="cms_posts",
                patterns=[
                    r"\bbai viet\b",
                    r"\bphan bai viet\b",
                    r"\bposts?\b",
                    r"\barticles?\b",
                    r"\btin tuc\b",
                    r"\bnews\b",
                ],
                tags=["posts"],
            ),
            DomainAliasRule(
                name="cms_auth",
                patterns=[
                    r"\bdang nhap\b",
                    r"\blogin\b",
                    r"\bauth\b",
                    r"\bxac thuc\b",
                    r"\bdang xuat\b",
                    r"\blogout\b",
                ],
                tags=["auth"],
            ),
            DomainAliasRule(
                name="cms_users",
                patterns=[
                    r"\bnguoi dung\b",
                    r"\btai khoan\b",
                    r"\busers?\b",
                    r"\baccounts?\b",
                    r"\buser\b",
                ],
                tags=["users"],
            ),

            # ===== Social / utility API aliases =====
            DomainAliasRule(
                name="social_img",
                patterns=[
                    r"\bimg\b",
                    r"\bimage\b",
                    r"\banh\b",
                    r"\btao anh\b",
                    r"\bsinh anh\b",
                    r"\bgenerate image\b",
                ],
                paths=["/img"],
                methods=[HttpMethod.POST],
            ),
            DomainAliasRule(
                name="social_fb",
                patterns=[
                    r"\bfacebook\b",
                    r"\bfb\b",
                    r"\blay noi dung facebook\b",
                    r"\bfacebook content\b",
                ],
                paths=["/FB"],
                methods=[HttpMethod.POST],
            ),
            DomainAliasRule(
                name="social_yt",
                patterns=[
                    r"\byoutube\b",
                    r"\byt\b",
                    r"\blay noi dung youtube\b",
                    r"\byoutube content\b",
                ],
                paths=["/YT"],
                methods=[HttpMethod.POST],
            ),
            DomainAliasRule(
                name="social_x_content",
                patterns=[
                    r"\bx content\b",
                    r"\btwitter content\b",
                    r"\bnoi dung x\b",
                    r"\bnoi dung twitter\b",
                ],
                paths=["/X/content"],
                methods=[HttpMethod.POST],
            ),
            DomainAliasRule(
                name="social_x_post",
                patterns=[
                    r"\bx post\b",
                    r"\bpost x\b",
                    r"\bdang x\b",
                    r"\bdang bai len x\b",
                    r"\bdang twitter\b",
                    r"\bpost twitter\b",
                ],
                paths=["/post/x"],
                methods=[HttpMethod.POST],
            ),
            DomainAliasRule(
                name="social_x",
                patterns=[
                    r"\btwitter\b",
                    r"\blay noi dung x\b",
                    r"\blay noi dung twitter\b",
                    r"\bapi x\b",
                ],
                paths=["/X"],
                methods=[HttpMethod.POST],
            ),
        ]