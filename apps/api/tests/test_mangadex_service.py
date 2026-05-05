import asyncio
from decimal import Decimal
import sys
import types

import pytest

import app.providers.mangadex as mangadex_provider
from app.providers.mangadex import (
    MangaDexChapterCandidate,
    build_page_request_headers,
    build_language_priority,
    choose_preferred_text,
    extract_chapter_ids_from_read_response,
    extract_chapters_from_aggregate_response,
    extract_headers_from_curl,
    merge_chapter_candidates,
    merge_request_headers,
    normalize_requested_languages,
    parse_mangadex_title_url,
    parse_sort_number,
    sanitize_mangadex_input,
)


def test_parse_mangadex_title_url_extracts_uuid() -> None:
    url = "https://mangadex.org/title/d8f1d7da-8bb1-407b-8be3-10ac2894d3c6/isekai-ojisan?tab=chapters"

    assert parse_mangadex_title_url(url) == "d8f1d7da-8bb1-407b-8be3-10ac2894d3c6"


def test_build_language_priority_prefers_zh_en_ja() -> None:
    available = ["fr", "en", "ja", "zh-hk", "zh", "pt-br"]

    assert build_language_priority(available) == ["zh", "en", "ja", "zh-hk"]


def test_choose_preferred_text_uses_priority_order() -> None:
    values = {
        "ja": "異世界おじさん",
        "en": "Uncle from Another World",
        "zh": "异世界舅舅",
    }

    assert choose_preferred_text(values, ["zh", "en", "ja"]) == "异世界舅舅"
    assert choose_preferred_text(values, ["fr", "en", "ja"]) == "Uncle from Another World"


def test_merge_chapter_candidates_prefers_higher_priority_language() -> None:
    candidates = [
        MangaDexChapterCandidate(
            chapter_id="en-ch-1",
            chapter="1",
            volume="1",
            title="Chapter One",
            translated_language="en",
            publish_at="2024-01-01T00:00:00+00:00",
        ),
        MangaDexChapterCandidate(
            chapter_id="zh-ch-1",
            chapter="1",
            volume="1",
            title="第一话",
            translated_language="zh",
            publish_at="2024-01-02T00:00:00+00:00",
        ),
        MangaDexChapterCandidate(
            chapter_id="ja-ch-2",
            chapter="2",
            volume="1",
            title="第二話",
            translated_language="ja",
            publish_at="2024-01-03T00:00:00+00:00",
        ),
    ]

    merged = merge_chapter_candidates(candidates, ["zh", "en", "ja"])

    assert [item.chapter for item in merged] == ["1", "2"]
    assert merged[0].chapter_id == "zh-ch-1"
    assert merged[0].translated_language == "zh"


def test_parse_sort_number_supports_decimal_and_special_labels() -> None:
    assert parse_sort_number("12.5", 3) == Decimal("12.50")
    assert parse_sort_number("001", 3) == Decimal("1.00")
    assert parse_sort_number("番外1", 3) == Decimal("10003.00")


def test_extract_headers_from_curl_extracts_authorization() -> None:
    curl_text = """curl 'https://api.mangadex.org/manga/read?ids[]=abc' \\
      -H 'authorization: Bearer test-token' \\
      -H 'referer: https://mangadex.org/' \\
      -H 'user-agent: Mozilla/5.0'"""
    headers = extract_headers_from_curl(curl_text)
    assert headers["Authorization"] == "Bearer test-token"
    assert headers["Referer"] == "https://mangadex.org/"
    assert headers["User-Agent"] == "Mozilla/5.0"


def test_merge_request_headers_prefers_explicit_authorization() -> None:
    merged = merge_request_headers(
        headers_from_curl={"Authorization": "Bearer old", "User-Agent": "UA-A"},
        authorization="Bearer new",
        referer="https://mangadex.org/",
    )
    assert merged["Authorization"] == "Bearer new"
    assert merged["Referer"] == "https://mangadex.org/"
    assert merged["User-Agent"] == "UA-A"


def test_build_page_request_headers_only_keeps_referer() -> None:
    headers = build_page_request_headers(
        {
            "Authorization": "Bearer secret-token",
            "Referer": "https://mangadex.org/",
            "User-Agent": "Mozilla/5.0",
        }
    )
    assert headers == {"Referer": "https://mangadex.org/"}


def test_extract_chapter_ids_from_read_response_supports_wrapped_and_plain_shapes() -> None:
    plain = {
        "manga-1": ["ch-1", "ch-2"],
    }
    wrapped = {
        "result": "ok",
        "data": {
            "manga-1": ["ch-1", "ch-2"],
        },
    }
    assert extract_chapter_ids_from_read_response(plain, "manga-1") == ["ch-1", "ch-2"]
    assert extract_chapter_ids_from_read_response(wrapped, "manga-1") == ["ch-1", "ch-2"]


def test_extract_chapters_from_aggregate_response_flattens_volumes() -> None:
    payload = {
        "result": "ok",
        "volumes": {
            "1": {
                "chapters": {
                    "1": {"chapter": "1", "id": "ch-1", "others": ["ch-1b"]},
                    "2": {"chapter": "2", "id": "ch-2"},
                }
            }
        },
    }
    flattened = extract_chapters_from_aggregate_response(payload)
    assert flattened == [
        {"chapter": "1", "chapter_id": "ch-1", "volume": "1", "is_unavailable": False},
        {"chapter": "1", "chapter_id": "ch-1b", "volume": "1", "is_unavailable": False},
        {"chapter": "2", "chapter_id": "ch-2", "volume": "1", "is_unavailable": False},
    ]


def test_normalize_requested_languages_falls_back_to_available_languages() -> None:
    assert normalize_requested_languages(["zh", "en", "ja"], ["en", "fr"]) == ["en"]


def test_sanitize_mangadex_input_removes_wrapping_backticks_and_spaces() -> None:
    assert sanitize_mangadex_input(" `https://mangadex.org/title/abc` ") == "https://mangadex.org/title/abc"


def test_fetch_chapter_candidates_uses_aggregate_after_read_seed_groups(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[str, dict | None]] = []

    class FakeAsyncClient:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return None

    async def fake_request_json(client, url, params=None, request_headers=None):  # type: ignore[no-untyped-def]
        calls.append((url, params))
        if url.endswith("/manga/manga-1"):
            return {
                "result": "ok",
                "data": {
                    "attributes": {
                        "title": {"en": "Test Manga"},
                        "description": {"en": "Desc"},
                        "availableTranslatedLanguages": ["en"],
                        "tags": [],
                        "links": {},
                        "originalLanguage": "ja",
                    }
                },
            }
        if url.endswith("/manga/read"):
            return {"result": "ok", "data": {"manga-1": ["seed-1", "seed-2"]}}
        if url.endswith("/chapter/seed-1"):
            return {
                "result": "ok",
                "data": {
                    "id": "seed-1",
                    "attributes": {"chapter": "1", "translatedLanguage": "en", "title": "", "pages": 10},
                    "relationships": [{"id": "group-a", "type": "scanlation_group", "attributes": {"name": "A"}}],
                },
            }
        if url.endswith("/chapter/seed-2"):
            return {
                "result": "ok",
                "data": {
                    "id": "seed-2",
                    "attributes": {"chapter": "1", "translatedLanguage": "en", "title": "", "pages": 10},
                    "relationships": [{"id": "group-b", "type": "scanlation_group", "attributes": {"name": "B"}}],
                },
            }
        if url.endswith("/manga/manga-1/aggregate"):
            assert params == {"translatedLanguage[]": ["en"], "groups[]": ["group-a", "group-b"]}
            return {
                "result": "ok",
                "volumes": {
                    "1": {
                        "chapters": {
                            "1": {"chapter": "1", "id": "chapter-1", "others": ["chapter-1b"], "count": 2},
                            "2": {"chapter": "2", "id": "chapter-2"},
                        }
                    }
                },
            }
        if "/chapter/chapter-" in url:
            raise AssertionError("discover should not fetch chapter detail for aggregate items")
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(mangadex_provider, "_request_json", fake_request_json)
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=FakeAsyncClient))

    candidates = asyncio.run(mangadex_provider.fetch_chapter_candidates("manga-1", language_priority=["zh", "en"]))

    assert [item.chapter_id for item in candidates] == ["chapter-1", "chapter-2"]
    assert [item.chapter for item in candidates] == ["1", "2"]
    assert candidates[0].group_ids == []
    assert candidates[0].pages is None
    assert any(url.endswith("/manga/manga-1/aggregate") for url, _ in calls)


def test_fetch_chapter_candidates_reuses_prefetched_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[str] = []

    class FakeAsyncClient:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return None

    prefetched = mangadex_provider.MangaDexMangaMetadata(
        manga_id="manga-1",
        title="Test Manga",
        description="Desc",
        language_priority=["en"],
        available_languages=["en"],
        links={},
        tags=[],
        original_language="ja",
    )

    async def fake_request_json(client, url, params=None, request_headers=None):  # type: ignore[no-untyped-def]
        calls.append(url)
        if url.endswith("/manga/read"):
            return {"result": "ok", "data": {"manga-1": []}}
        if url.endswith("/manga/manga-1/aggregate"):
            return {"result": "ok", "volumes": {}}
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(mangadex_provider, "_request_json", fake_request_json)
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=FakeAsyncClient))

    asyncio.run(mangadex_provider.fetch_chapter_candidates("manga-1", metadata=prefetched))

    assert not any(url.endswith("/manga/manga-1") for url in calls)


def test_fetch_chapter_candidates_skips_seed_lookup_when_explicit_groups_provided(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, dict | None]] = []

    class FakeAsyncClient:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return None

    async def fake_request_json(client, url, params=None, request_headers=None):  # type: ignore[no-untyped-def]
        calls.append((url, params))
        if url.endswith("/manga/manga-1"):
            return {
                "result": "ok",
                "data": {
                    "attributes": {
                        "title": {"en": "Test Manga"},
                        "description": {"en": "Desc"},
                        "availableTranslatedLanguages": ["en"],
                        "tags": [],
                        "links": {},
                        "originalLanguage": "ja",
                    }
                },
            }
        if url.endswith("/manga/read") or url.endswith("/chapter/seed-1"):
            raise AssertionError("seed lookup should be skipped when explicit groups are provided")
        if url.endswith("/manga/manga-1/aggregate"):
            assert params == {"translatedLanguage[]": ["en"], "groups[]": ["group-explicit"]}
            return {
                "result": "ok",
                "volumes": {
                    "1": {
                        "chapters": {
                            "1": {"chapter": "1", "id": "chapter-1"},
                        }
                    }
                },
            }
        if "/chapter/chapter-" in url:
            raise AssertionError("discover should not fetch chapter detail for aggregate items")
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(mangadex_provider, "_request_json", fake_request_json)
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=FakeAsyncClient))

    candidates = asyncio.run(
        mangadex_provider.fetch_chapter_candidates(
            "manga-1",
            language_priority=["en"],
            groups=["group-explicit"],
        )
    )

    assert [item.chapter_id for item in candidates] == ["chapter-1"]
    assert not any(url.endswith("/manga/read") for url, _ in calls)


def test_fetch_chapter_candidates_retries_aggregate_without_inferred_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aggregate_params: list[dict | None] = []

    class FakeAsyncClient:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return None

    async def fake_request_json(client, url, params=None, request_headers=None):  # type: ignore[no-untyped-def]
        if url.endswith("/manga/manga-1"):
            return {
                "result": "ok",
                "data": {
                    "attributes": {
                        "title": {"en": "Test Manga"},
                        "description": {"en": "Desc"},
                        "availableTranslatedLanguages": ["en"],
                        "tags": [],
                        "links": {},
                        "originalLanguage": "ja",
                    }
                },
            }
        if url.endswith("/manga/read"):
            return {"result": "ok", "data": {"manga-1": ["seed-1"]}}
        if url.endswith("/chapter/seed-1"):
            return {
                "result": "ok",
                "data": {
                    "id": "seed-1",
                    "attributes": {"chapter": "1", "translatedLanguage": "en", "title": "", "pages": 10},
                    "relationships": [{"id": "group-a", "type": "scanlation_group", "attributes": {"name": "A"}}],
                },
            }
        if url.endswith("/manga/manga-1/aggregate"):
            aggregate_params.append(params)
            if params == {"translatedLanguage[]": ["en"], "groups[]": ["group-a"]}:
                return {"result": "ok", "volumes": {}}
            if params == {"translatedLanguage[]": ["en"]}:
                return {
                    "result": "ok",
                    "volumes": {
                        "1": {
                            "chapters": {
                                "1": {"chapter": "1", "id": "chapter-1"},
                            }
                        }
                    },
                }
            raise AssertionError(f"Unexpected aggregate params: {params}")
        if "/chapter/chapter-" in url:
            raise AssertionError("discover should not fetch chapter detail for aggregate items")
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(mangadex_provider, "_request_json", fake_request_json)
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=FakeAsyncClient))

    candidates = asyncio.run(mangadex_provider.fetch_chapter_candidates("manga-1", language_priority=["en"]))

    assert [item.chapter_id for item in candidates] == ["chapter-1"]
    assert aggregate_params == [
        {"translatedLanguage[]": ["en"], "groups[]": ["group-a"]},
        {"translatedLanguage[]": ["en"]},
    ]


def test_fetch_chapter_candidates_uses_only_first_preferred_language_for_discover(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    aggregate_params: list[dict | None] = []

    class FakeAsyncClient:
        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, exc_type, exc, tb):  # type: ignore[no-untyped-def]
            return None

    async def fake_request_json(client, url, params=None, request_headers=None):  # type: ignore[no-untyped-def]
        if url.endswith("/manga/manga-1"):
            return {
                "result": "ok",
                "data": {
                    "attributes": {
                        "title": {"ja": "Test Manga"},
                        "description": {"en": "Desc"},
                        "availableTranslatedLanguages": ["zh", "en", "ja"],
                        "tags": [],
                        "links": {},
                        "originalLanguage": "ja",
                    }
                },
            }
        if url.endswith("/manga/read"):
            return {"result": "ok", "data": {"manga-1": []}}
        if url.endswith("/manga/manga-1/aggregate"):
            aggregate_params.append(params)
            return {
                "result": "ok",
                "volumes": {
                    "1": {
                        "chapters": {
                            "1": {"chapter": "1", "id": "chapter-1"},
                        }
                    }
                },
            }
        raise AssertionError(f"Unexpected request: {url}")

    monkeypatch.setattr(mangadex_provider, "_request_json", fake_request_json)
    monkeypatch.setitem(sys.modules, "httpx", types.SimpleNamespace(AsyncClient=FakeAsyncClient))

    candidates = asyncio.run(mangadex_provider.fetch_chapter_candidates("manga-1", language_priority=["zh", "en", "ja"]))

    assert aggregate_params == [{"translatedLanguage[]": ["zh"]}]
    assert candidates[0].translated_language == "zh"


def test_extract_chapters_from_aggregate_response_keeps_entries_without_chapter_label() -> None:
    payload = {
        "result": "ok",
        "volumes": {
            "0": {
                "chapters": {
                    "none": {"chapter": None, "id": "special-1"},
                }
            }
        },
    }

    flattened = extract_chapters_from_aggregate_response(payload)

    assert flattened == [
        {"chapter": "id:special-1", "chapter_id": "special-1", "volume": "0", "is_unavailable": False}
    ]
