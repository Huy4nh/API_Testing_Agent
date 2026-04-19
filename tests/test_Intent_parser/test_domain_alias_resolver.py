from api_testing_agent.core.domain_alias_resolver import DomainAliasResolver
from api_testing_agent.core.models import HttpMethod


def test_resolver_maps_cms_posts_alias():
    resolver = DomainAliasResolver()

    resolved = resolver.resolve("test bai viet tren local")

    assert resolved.tags == ["posts"]
    assert resolved.paths == []
    assert resolved.methods == []


def test_resolver_maps_social_facebook_alias():
    resolver = DomainAliasResolver()

    resolved = resolver.resolve("lay noi dung facebook")

    assert resolved.tags == []
    assert resolved.paths == ["/FB"]
    assert resolved.methods == [HttpMethod.POST]


def test_resolver_maps_x_post_alias():
    resolver = DomainAliasResolver()

    resolved = resolver.resolve("dang bai len x")

    assert resolved.paths == ["/post/x"]
    assert resolved.methods == [HttpMethod.POST]


def test_empty_resolver_returns_nothing():
    resolver = DomainAliasResolver.empty()

    resolved = resolver.resolve("bai viet facebook local")

    assert resolved.tags == []
    assert resolved.paths == []
    assert resolved.methods == []
    assert resolved.extra_tokens == []