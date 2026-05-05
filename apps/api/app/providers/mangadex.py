from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
import logging
import re
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from app.logging_utils import get_mangadex_logger

if TYPE_CHECKING:
    import httpx

MANGADEX_API_BASE = "https://api.mangadex.org"
TITLE_ID_PATTERN = re.compile(r"/title/([0-9a-fA-F-]{36})")
UUID_PATTERN = re.compile(r"^[0-9a-fA-F-]{36}$")
HEADER_ARG_PATTERN = re.compile(r"""(?:^|\s)(?:-H|--header)\s+(['"])(.*?)\1""", re.DOTALL)
ALLOWED_HEADER_NAMES = {"authorization", "referer", "user-agent", "origin"}
logger = logging.getLogger(__name__)
trace_logger = get_mangadex_logger()


class MangaDexError(Exception):
    pass


@dataclass(slots=True)
class MangaDexChapterCandidate:
    chapter_id: str
    chapter: str
    volume: str | None
    title: str | None
    translated_language: str
    publish_at: str | None
    group_ids: list[str] | None = None
    group_names: list[str] | None = None
    pages: int | None = None
    is_unavailable: bool = False


@dataclass(slots=True)
class MangaDexMangaMetadata:
    manga_id: str
    title: str
    description: str | None
    language_priority: list[str]
    available_languages: list[str]
    links: dict[str, str] | None
    tags: list[str]
    original_language: str | None


def sanitize_mangadex_input(value: str | None) -> str:
    text = (value or "").strip()
    while len(text) >= 2 and text[0] == text[-1] and text[0] in {"`", "'", '"'}:
        text = text[1:-1].strip()
    return text


def mask_header_value(name: str, value: str) -> str:
    if name.strip().lower() == "authorization":
        compact = value.strip()
        if len(compact) <= 18:
            return "***"
        return f"{compact[:12]}...{compact[-6:]}"
    return value


def summarize_request_headers(request_headers: dict[str, str] | None) -> dict[str, str]:
    return {key: mask_header_value(key, value) for key, value in (request_headers or {}).items()}


def parse_mangadex_title_url(url_or_id: str) -> str:
    text = sanitize_mangadex_input(url_or_id)
    if UUID_PATTERN.match(text):
        return text
    if "/title/" not in text:
        raise MangaDexError("请输入 MangaDex 作品链接或合法的 manga UUID")
    parsed = urlparse(text)
    match = TITLE_ID_PATTERN.search(parsed.path)
    if not match:
        raise MangaDexError("无法从链接解析 MangaDex manga UUID")
    return match.group(1)


def _canonical_header_name(name: str) -> str:
    lowered = name.strip().lower()
    mapping = {
        "authorization": "Authorization",
        "referer": "Referer",
        "user-agent": "User-Agent",
        "origin": "Origin",
    }
    return mapping.get(lowered, name.strip())


def extract_headers_from_curl(curl_text: str | None) -> dict[str, str]:
    normalized_curl = sanitize_mangadex_input(curl_text)
    if not normalized_curl:
        return {}
    headers: dict[str, str] = {}
    for _, header_text in HEADER_ARG_PATTERN.findall(normalized_curl.replace("\\\n", " ")):
        if ":" not in header_text:
            continue
        raw_name, raw_value = header_text.split(":", 1)
        normalized_name = raw_name.strip().lower()
        if normalized_name not in ALLOWED_HEADER_NAMES:
            continue
        value = sanitize_mangadex_input(raw_value)
        if value:
            headers[_canonical_header_name(normalized_name)] = value
    logger.info("MangaDex curl headers parsed: %s", summarize_request_headers(headers))
    trace_logger.info("curl headers parsed=%s", summarize_request_headers(headers))
    return headers


def merge_request_headers(
    headers_from_curl: dict[str, str] | None,
    authorization: str | None = None,
    referer: str | None = "https://mangadex.org/",
) -> dict[str, str]:
    merged: dict[str, str] = {}
    for key, value in (headers_from_curl or {}).items():
        canonical_name = _canonical_header_name(key)
        if canonical_name.lower() in ALLOWED_HEADER_NAMES and value:
            merged[canonical_name] = value
    if referer:
        merged["Referer"] = referer
    if authorization:
        merged["Authorization"] = sanitize_mangadex_input(authorization)
    logger.info("MangaDex request headers merged: %s", summarize_request_headers(merged))
    trace_logger.info("request headers merged=%s", summarize_request_headers(merged))
    return merged


def build_page_request_headers(request_headers: dict[str, str] | None) -> dict[str, str]:
    referer = (request_headers or {}).get("Referer") or (request_headers or {}).get("referer")
    return {"Referer": referer or "https://mangadex.org/"}


def extract_chapter_ids_from_read_response(payload: dict[str, Any], manga_id: str) -> list[str]:
    candidates: list[str] = []
    sources: list[Any] = [payload]
    data = payload.get("data")
    if isinstance(data, dict):
        sources.append(data)

    for source in sources:
        if not isinstance(source, dict):
            continue
        value = source.get(manga_id)
        if isinstance(value, list):
            candidates.extend(str(item) for item in value if item)
        elif isinstance(value, dict):
            for nested in value.values():
                if isinstance(nested, list):
                    candidates.extend(str(item) for item in nested if item)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        if item not in seen:
            deduped.append(item)
            seen.add(item)
    logger.info("MangaDex read response extracted %s chapter ids for manga=%s", len(deduped), manga_id)
    trace_logger.info("read response manga=%s chapter_ids=%s", manga_id, deduped)
    return deduped


def extract_chapters_from_aggregate_response(payload: dict[str, Any]) -> list[dict[str, Any]]:
    volumes = payload.get("volumes") or {}
    flattened: list[dict[str, Any]] = []
    for volume_key, volume_data in volumes.items():
        volume_label = (volume_data or {}).get("volume")
        if volume_label is None and volume_key not in {"", "none", "null"}:
            volume_label = volume_key
        chapters = (volume_data or {}).get("chapters") or {}
        for chapter_data in chapters.values():
            primary_id = (chapter_data or {}).get("id")
            is_unavailable = bool((chapter_data or {}).get("isUnavailable"))
            if is_unavailable:
                continue
            chapter_label = (chapter_data or {}).get("chapter")
            if primary_id:
                normalized_label = str(chapter_label) if chapter_label is not None else f"id:{primary_id}"
                flattened.append(
                    {
                        "chapter": normalized_label,
                        "chapter_id": str(primary_id),
                        "volume": str(volume_label) if volume_label is not None else None,
                        "is_unavailable": is_unavailable,
                    }
                )
            for extra_id in (chapter_data or {}).get("others") or []:
                if extra_id:
                    normalized_label = str(chapter_label) if chapter_label is not None else f"id:{extra_id}"
                    flattened.append(
                        {
                            "chapter": normalized_label,
                            "chapter_id": str(extra_id),
                            "volume": str(volume_label) if volume_label is not None else None,
                            "is_unavailable": is_unavailable,
                        }
                    )
    logger.info("MangaDex aggregate response extracted %s chapter mappings", len(flattened))
    trace_logger.info("aggregate chapter mappings=%s", flattened)
    return flattened


def summarize_values_for_log(values: list[str] | None, limit: int = 20) -> dict[str, Any]:
    normalized = [str(value) for value in (values or []) if value]
    return {
        "count": len(normalized),
        "sample": normalized[:limit],
        "truncated": len(normalized) > limit,
    }


def dedupe_preserve_order(values: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values or []:
        if not value or value in seen:
            continue
        deduped.append(value)
        seen.add(value)
    return deduped


def build_language_priority(available_languages: list[str] | None) -> list[str]:
    available = [lang.lower() for lang in (available_languages or [])]
    priority: list[str] = []
    for preferred in ["zh", "en", "ja"]:
        if preferred in available:
            priority.append(preferred)
    for lang in available:
        if lang.startswith("zh-") and lang not in priority:
            priority.append(lang)
    return priority or ["zh", "en", "ja"]


def normalize_requested_languages(
    requested_languages: list[str] | None, available_languages: list[str] | None
) -> list[str]:
    available = [lang.lower() for lang in (available_languages or [])]
    if not available:
        return requested_languages or ["zh", "en", "ja"]
    if not requested_languages:
        return build_language_priority(available)

    normalized_requested = [lang.lower() for lang in requested_languages]
    resolved: list[str] = []
    for lang in normalized_requested:
        if lang in available and lang not in resolved:
            resolved.append(lang)
        elif lang == "zh":
            for available_lang in available:
                if available_lang.startswith("zh") and available_lang not in resolved:
                    resolved.append(available_lang)
    if resolved:
        return resolved
    return build_language_priority(available)


def choose_preferred_text(values: dict[str, str] | None, language_priority: list[str]) -> str | None:
    if not values:
        return None
    normalized = {k.lower(): v for k, v in values.items() if isinstance(v, str) and v.strip()}
    for lang in language_priority:
        if lang in normalized:
            return normalized[lang]
    for fallback in ["en", "ja", "zh"]:
        if fallback in normalized:
            return normalized[fallback]
    return next(iter(normalized.values()), None)


def parse_sort_number(chapter_label: str | None, fallback_index: int) -> Decimal:
    raw = (chapter_label or "").strip()
    if raw:
        lowered = raw.lower()
        if any(marker in lowered for marker in ["番外", "extra", "special", "omake"]):
            return Decimal(10000 + fallback_index).quantize(Decimal("0.01"))
        number_match = re.search(r"\d+(?:\.\d+)?", raw)
        if number_match:
            try:
                return Decimal(number_match.group(0)).quantize(Decimal("0.01"))
            except InvalidOperation:
                pass
    return Decimal(10000 + fallback_index).quantize(Decimal("0.01"))


def merge_chapter_candidates(
    candidates: list[MangaDexChapterCandidate], language_priority: list[str]
) -> list[MangaDexChapterCandidate]:
    lang_rank = {lang: idx for idx, lang in enumerate(language_priority)}

    def _candidate_rank(item: MangaDexChapterCandidate) -> tuple[int, int]:
        rank = lang_rank.get(item.translated_language.lower(), len(language_priority) + 10)
        group_rank = 0 if item.group_ids else 1
        return (rank, group_rank)

    grouped: dict[str, MangaDexChapterCandidate] = {}
    for item in candidates:
        chapter_key = (item.chapter or "").strip() or f"id:{item.chapter_id}"
        existing = grouped.get(chapter_key)
        if existing is None or _candidate_rank(item) < _candidate_rank(existing):
            grouped[chapter_key] = item

    merged = list(grouped.values())
    merged.sort(key=lambda item: parse_sort_number(item.chapter, 999999))
    return merged


def _extract_group_ids(relationships: list[dict[str, Any]] | None) -> list[str]:
    if not relationships:
        return []
    return [rel.get("id") for rel in relationships if rel.get("type") == "scanlation_group" and rel.get("id")]


async def _request_json(
    client: "httpx.AsyncClient",
    url: str,
    params: dict[str, Any] | None = None,
    request_headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    logger.info(
        "MangaDex request start url=%s params=%s headers=%s",
        url,
        params,
        summarize_request_headers(request_headers),
    )
    trace_logger.info(
        "request start url=%s params=%s headers=%s",
        url,
        params,
        summarize_request_headers(request_headers),
    )
    response = await client.get(url, params=params, headers=request_headers, timeout=30.0)
    response.raise_for_status()
    data = response.json()
    if not isinstance(data, dict):
        raise MangaDexError("MangaDex 响应格式异常")
    logger.info(
        "MangaDex request ok url=%s keys=%s",
        url,
        sorted(list(data.keys()))[:20],
    )
    trace_logger.info(
        "request ok url=%s keys=%s",
        url,
        sorted(list(data.keys()))[:20],
    )
    return data


async def fetch_manga_metadata(
    manga_id: str,
    language_priority: list[str] | None = None,
    request_headers: dict[str, str] | None = None,
) -> MangaDexMangaMetadata:
    import httpx

    async with httpx.AsyncClient() as client:
        payload = await _request_json(client, f"{MANGADEX_API_BASE}/manga/{manga_id}", request_headers=request_headers)
    data = payload.get("data") or {}
    attrs = data.get("attributes") or {}
    available_languages = attrs.get("availableTranslatedLanguages") or []
    preferred_languages = normalize_requested_languages(language_priority, available_languages)

    title = choose_preferred_text(attrs.get("title"), preferred_languages) or manga_id
    description = choose_preferred_text(attrs.get("description"), preferred_languages)
    tags = []
    for tag in attrs.get("tags") or []:
        name = ((tag.get("attributes") or {}).get("name") or {}).get("en")
        if isinstance(name, str) and name:
            tags.append(name)

    return MangaDexMangaMetadata(
        manga_id=manga_id,
        title=title,
        description=description,
        language_priority=preferred_languages,
        available_languages=available_languages,
        links=attrs.get("links") or {},
        tags=tags,
        original_language=attrs.get("originalLanguage"),
    )


async def fetch_chapter_candidates(
    manga_id: str,
    language_priority: list[str] | None = None,
    groups: list[str] | None = None,
    request_headers: dict[str, str] | None = None,
    metadata: MangaDexMangaMetadata | None = None,
) -> list[MangaDexChapterCandidate]:
    import httpx

    async with httpx.AsyncClient() as client:
        metadata = metadata or await fetch_manga_metadata(
            manga_id, language_priority=language_priority, request_headers=request_headers
        )
        explicit_groups = dedupe_preserve_order(groups)
        seed_chapter_ids: list[str] = []
        seed_group_ids: list[str] = []
        if not explicit_groups:
            read_payload = await _request_json(
                client,
                f"{MANGADEX_API_BASE}/manga/read",
                params={"ids[]": manga_id, "grouped": "true"},
                request_headers=request_headers,
            )
            seed_chapter_ids = extract_chapter_ids_from_read_response(read_payload, manga_id)
            for seed_chapter_id in seed_chapter_ids:
                seed_payload = await _request_json(
                    client,
                    f"{MANGADEX_API_BASE}/chapter/{seed_chapter_id}",
                    params={"includes[]": ["scanlation_group", "manga", "user"]},
                    request_headers=request_headers,
                )
                seed_relationships = (seed_payload.get("data") or {}).get("relationships") or []
                seed_group_ids.extend(_extract_group_ids(seed_relationships))

        inferred_groups = dedupe_preserve_order(seed_group_ids)
        resolved_groups = explicit_groups or inferred_groups
        logger.info(
            "MangaDex discover seed groups manga=%s seed_chapter_count=%s inferred_group_count=%s explicit_group_count=%s resolved_group_count=%s",
            manga_id,
            len(seed_chapter_ids),
            len(inferred_groups),
            len(explicit_groups),
            len(resolved_groups),
        )
        trace_logger.info(
            "discover seed groups manga=%s seed_chapter_ids=%s inferred_groups=%s explicit_groups=%s resolved_groups=%s",
            manga_id,
            summarize_values_for_log(seed_chapter_ids),
            summarize_values_for_log(inferred_groups),
            summarize_values_for_log(explicit_groups),
            summarize_values_for_log(resolved_groups),
        )

        discover_languages = metadata.language_priority[:1] or ["en"]
        aggregate_params: dict[str, Any] = {"translatedLanguage[]": discover_languages}
        if resolved_groups:
            aggregate_params["groups[]"] = resolved_groups
        aggregate_payload = await _request_json(
            client,
            f"{MANGADEX_API_BASE}/manga/{manga_id}/aggregate",
            params=aggregate_params,
            request_headers=request_headers,
        )
        aggregate_chapters = extract_chapters_from_aggregate_response(aggregate_payload)

        if not aggregate_chapters and resolved_groups and not groups:
            logger.warning(
                "MangaDex aggregate returned no chapters for manga=%s with inferred groups=%s, retry without groups",
                manga_id,
                resolved_groups,
            )
            trace_logger.warning(
                "aggregate empty for manga=%s with inferred groups=%s, retry without groups",
                manga_id,
                resolved_groups,
            )
            aggregate_payload = await _request_json(
                client,
                f"{MANGADEX_API_BASE}/manga/{manga_id}/aggregate",
                params={"translatedLanguage[]": discover_languages},
                request_headers=request_headers,
            )
            aggregate_chapters = extract_chapters_from_aggregate_response(aggregate_payload)
            resolved_groups = []

        chapter_ids = [item["chapter_id"] for item in aggregate_chapters]
        logger.info(
            "MangaDex aggregate chapters manga=%s aggregate_count=%s resolved_groups=%s",
            manga_id,
            len(aggregate_chapters),
            len(resolved_groups),
        )
        trace_logger.info(
            "aggregate chapters manga=%s aggregate_count=%s resolved_groups=%s chapter_ids=%s",
            manga_id,
            len(aggregate_chapters),
            summarize_values_for_log(resolved_groups),
            summarize_values_for_log(chapter_ids),
        )
        logger.info(
            "MangaDex discover candidate inputs manga=%s languages=%s groups=%s chapter_ids=%s",
            manga_id,
            metadata.language_priority,
            len(resolved_groups),
            len(chapter_ids),
        )
        trace_logger.info(
            "discover candidate inputs manga=%s languages=%s groups=%s chapter_ids=%s",
            manga_id,
            metadata.language_priority,
            summarize_values_for_log(resolved_groups),
            summarize_values_for_log(chapter_ids),
        )

        discover_language = discover_languages[0] if discover_languages else "unknown"
        candidates = [
            MangaDexChapterCandidate(
                chapter_id=str(item["chapter_id"]),
                chapter=str(item["chapter"]),
                volume=item.get("volume"),
                title=None,
                translated_language=discover_language,
                publish_at=None,
                group_ids=[],
                group_names=[],
                pages=None,
                is_unavailable=bool(item.get("is_unavailable")),
            )
            for item in aggregate_chapters
            if item.get("chapter_id") and item.get("chapter")
        ]
    logger.info("MangaDex discover produced %s candidate chapters for manga=%s", len(candidates), manga_id)
    trace_logger.info(
        "discover produced manga=%s candidate_count=%s candidates=%s",
        manga_id,
        len(candidates),
        {
            "count": len(candidates),
            "sample": [
                {
                    "chapter_id": item.chapter_id,
                    "chapter": item.chapter,
                    "language": item.translated_language,
                    "group_ids": item.group_ids,
                }
                for item in candidates[:20]
            ],
            "truncated": len(candidates) > 20,
        },
    )
    return merge_chapter_candidates(candidates, metadata.language_priority)


async def fetch_chapter_image_urls(
    chapter_id: str,
    use_data_saver: bool = True,
    request_headers: dict[str, str] | None = None,
) -> list[str]:
    import httpx

    async with httpx.AsyncClient() as client:
        payload = await _request_json(
            client, f"{MANGADEX_API_BASE}/at-home/server/{chapter_id}", request_headers=request_headers
        )
    base_url = payload.get("baseUrl")
    chapter_data = payload.get("chapter") or {}
    hash_value = chapter_data.get("hash")
    file_names = chapter_data.get("dataSaver") if use_data_saver else chapter_data.get("data")
    if not base_url or not hash_value or not isinstance(file_names, list):
        raise MangaDexError(f"章节 {chapter_id} 图片资源返回异常")
    segment = "data-saver" if use_data_saver else "data"
    return [f"{base_url}/{segment}/{hash_value}/{name}" for name in file_names]
