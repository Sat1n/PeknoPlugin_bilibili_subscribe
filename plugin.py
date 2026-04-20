import hashlib
import html
import re
import xml.etree.ElementTree as ET
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import httpx

from shared.plugins.base import BasePlugin, PluginContext


SOURCE_TYPE = "bilibili_video"
ROUTE_TEMPLATE = "/bilibili/followings/video/{uid}"


class BilibiliSubscribePlugin(BasePlugin):
    def __init__(self):
        super().__init__()
        self._manifest = {
            "id": "bilibili_subscribe",
            "name": "Bilibili Subscribe",
            "source_type": SOURCE_TYPE,
            "description": "Sync latest videos from the Bilibili accounts you follow via RSSHub.",
            "version": "0.1.0",
            "required_credentials": ["bilibili"],
            "auto_sync_supported": True,
            "framework_defaults": {
                "retention_hours": 24,
                "auto_short_summary": False,
                "auto_sync": True,
                "auto_sync_interval": 5,
                "sync_limit": 50,
            },
            "settings_schema": {},
        }

    async def fetch_data(self, ctx: PluginContext) -> list[dict[str, Any]]:
        uid = self._required_config(ctx, "uid")
        rsshub_base_url = self._required_config(ctx, "rsshub_base_url").rstrip("/")
        limit = int(ctx.config.get("sync_limit") or 50)
        feed_url = f"{rsshub_base_url}{ROUTE_TEMPLATE.format(uid=uid)}"

        ctx.log.info(f"[BilibiliSubscribe] Fetching RSSHub feed: {feed_url} (limit: {limit})")
        response = await ctx.http.get(feed_url, headers=self._headers(ctx), follow_redirects=True)
        response.raise_for_status()

        items = self._parse_feed(response.content, feed_url)
        return items[:limit]

    def normalize_item(self, raw_data: dict[str, Any]) -> dict[str, Any]:
        link = raw_data.get("link") or ""
        bvid = raw_data.get("bvid") or self._extract_bvid(link)
        item_id = (
            f"bilibili_video_{bvid}"
            if bvid
            else self._fallback_item_id(link or raw_data.get("guid") or raw_data.get("title") or "")
        )

        author = raw_data.get("author") or ""
        tags = ["bilibili", "video"]
        if author:
            tags.append(author)

        metadata_extra = {
            "platform": "bilibili",
            "author": author,
            "bvid": bvid,
            "aid": raw_data.get("aid"),
            "guid": raw_data.get("guid"),
            "published_at": raw_data.get("published_at"),
            "feed_title": raw_data.get("feed_title"),
            "rsshub_url": raw_data.get("rsshub_url"),
        }
        metadata_extra = {key: value for key, value in metadata_extra.items() if value not in (None, "")}

        cover_url = raw_data.get("cover_url")
        if cover_url:
            metadata_extra["cover_url"] = cover_url

        iframe_url = raw_data.get("iframe_url")
        if iframe_url:
            metadata_extra["iframe_url"] = iframe_url

        return {
            "id": item_id,
            "title": raw_data.get("title") or link or "Bilibili video",
            "source_type": SOURCE_TYPE,
            "raw_link": link,
            "content_text": raw_data.get("content_text") or "",
            "intent": "video",
            "tags": tags,
            "metadata_extra": metadata_extra,
        }

    async def extract_text_for_ai(self, ctx: PluginContext, raw_data: dict[str, Any]) -> str:
        parts = [
            raw_data.get("title") or "",
            f"UP: {raw_data.get('author')}" if raw_data.get("author") else "",
            raw_data.get("content_text") or "",
        ]
        return "\n\n".join(part for part in parts if part).strip()

    async def parse_single_item(self, url: str, ctx: PluginContext | None = None) -> dict[str, Any]:
        if "bilibili.com/video/" not in url and not self._extract_bvid(url):
            raise ValueError("请提供有效的 Bilibili 视频链接")

        bvid = self._extract_bvid(url)
        raw = {
            "title": bvid or url,
            "link": url,
            "guid": url,
            "bvid": bvid,
            "content_text": "",
        }
        normalized = self.normalize_item(raw)
        normalized["_pipeline_raw_data"] = raw
        return normalized

    def _parse_feed(self, content: bytes, feed_url: str) -> list[dict[str, Any]]:
        root = ET.fromstring(content)
        channel = root.find("channel")
        if channel is None:
            raise ValueError("RSSHub did not return an RSS channel")

        feed_title = self._child_text(channel, "title")
        parsed_items = []
        for item in channel.findall("item"):
            description_html = self._child_text(item, "description")
            link = self._child_text(item, "link")
            guid = self._child_text(item, "guid")
            parsed_description = self._parse_description(description_html)
            bvid = (
                self._extract_bvid(link)
                or self._extract_bvid(parsed_description.get("iframe_url") or "")
                or self._extract_bvid(guid)
            )

            parsed_items.append(
                {
                    "title": self._child_text(item, "title"),
                    "link": link,
                    "guid": guid,
                    "author": self._child_text(item, "author"),
                    "pub_date": self._child_text(item, "pubDate"),
                    "published_at": self._parse_pub_date(self._child_text(item, "pubDate")),
                    "feed_title": feed_title,
                    "rsshub_url": feed_url,
                    "bvid": bvid,
                    **parsed_description,
                }
            )
        return parsed_items

    def _parse_description(self, description_html: str) -> dict[str, str | None]:
        decoded = html.unescape(description_html or "")
        cover_url = self._first_match(r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']", decoded)
        iframe_url = self._first_match(r"<iframe\b[^>]*\bsrc=[\"']([^\"']+)[\"']", decoded)
        aid = self._first_match(r"[?&]aid=([^&#]+)", iframe_url or "")

        text = re.sub(r"<(iframe|img)\b[^>]*>.*?</\1>", "", decoded, flags=re.IGNORECASE | re.DOTALL)
        text = re.sub(r"<(iframe|img)\b[^>]*>", "", text, flags=re.IGNORECASE)
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)
        text = re.sub(r"<[^>]+>", "", text)
        text = html.unescape(text).replace("\xa0", " ")
        text = re.sub(r"[ \t]+\n", "\n", text)
        text = re.sub(r"\n{3,}", "\n\n", text)
        text = re.sub(r"[ \t]{2,}", " ", text).strip()

        return {
            "content_text": text,
            "cover_url": cover_url,
            "iframe_url": iframe_url,
            "aid": aid,
        }

    def _headers(self, ctx: PluginContext) -> dict[str, str]:
        headers = {
            "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8",
            "User-Agent": "Iris-Hub-Bilibili-Subscribe/0.1",
        }
        sessdata = (ctx.config.get("cookie") or ctx.credentials.get("bilibili") or "").strip()
        if sessdata:
            headers["Cookie"] = sessdata if "=" in sessdata else f"SESSDATA={sessdata}"
        return headers

    def _required_config(self, ctx: PluginContext, key: str) -> str:
        value = str(ctx.config.get(key) or "").strip()
        if not value:
            raise ValueError(f"[bilibili_subscribe] Missing required config: {key}")
        return value

    def _child_text(self, element: ET.Element, tag: str) -> str:
        child = element.find(tag)
        return (child.text or "").strip() if child is not None else ""

    def _extract_bvid(self, value: str | None) -> str | None:
        if not value:
            return None
        match = re.search(r"(BV[0-9A-Za-z]+)", value)
        return match.group(1) if match else None

    def _first_match(self, pattern: str, value: str) -> str | None:
        match = re.search(pattern, value or "", flags=re.IGNORECASE | re.DOTALL)
        return html.unescape(match.group(1)).strip() if match else None

    def _parse_pub_date(self, value: str) -> str | None:
        if not value:
            return None
        try:
            return parsedate_to_datetime(value).isoformat()
        except (TypeError, ValueError):
            return value

    def _fallback_item_id(self, seed: str) -> str:
        digest = hashlib.sha256(seed.encode("utf-8")).hexdigest()[:16]
        return f"bilibili_video_{digest}"

    async def get_hover_blocks(self, item_url: str, user_config: dict) -> list[dict]:
        video_id = self._extract_video_id(item_url)
        if not video_id:
            return []

        headers = self._bilibili_headers(item_url, user_config)
        try:
            async with httpx.AsyncClient(timeout=10.0, headers=headers) as client:
                video_info = await self._fetch_video_info(client, video_id)
                aid = str(video_info.get("aid") or video_id.get("aid") or "")
                bvid = video_info.get("bvid") or video_id.get("bvid")
                title = video_info.get("title") or bvid or f"av{aid}"

                if not aid:
                    return []

                comments = await self._fetch_hot_comments(client, aid)
        except (httpx.HTTPError, ValueError):
            return [{"block_type": "markdown", "text": "评论加载失败"}]

        if not comments:
            return [{"block_type": "markdown", "text": "暂无热门评论"}]

        sorted_comments = sorted(
            comments,
            key=lambda item: int(item.get("like") or 0),
            reverse=True,
        )[:5]

        blocks: list[dict] = [
            {
                "block_type": "markdown",
                "text": f"{title}\n热门评论",
            }
        ]
        for comment in sorted_comments:
            member = comment.get("member") or {}
            content = comment.get("content") or {}
            message = self._clean_comment_text(content.get("message") or "")
            like_count = int(comment.get("like") or 0)
            if not message:
                continue
            blocks.append(
                {
                    "block_type": "quote",
                    "author": self._comment_author(member, like_count),
                    "avatar_url": member.get("avatar") or "",
                    "content": message,
                    "date": self._format_comment_time(comment.get("ctime")),
                }
            )
        return blocks

    def _extract_video_id(self, url: str) -> dict[str, str] | None:
        bvid = self._extract_bvid(url)
        if bvid:
            return {"bvid": bvid}
        av_match = re.search(r"(?:/video/av|[?&]aid=|[?&]oid=)(\d+)", url or "", flags=re.IGNORECASE)
        if av_match:
            return {"aid": av_match.group(1)}
        return None

    async def _fetch_video_info(self, client: httpx.AsyncClient, video_id: dict[str, str]) -> dict[str, Any]:
        params = {"bvid": video_id["bvid"]} if video_id.get("bvid") else {"aid": video_id["aid"]}
        response = await client.get("https://api.bilibili.com/x/web-interface/view", params=params)
        response.raise_for_status()
        payload = response.json()
        if payload.get("code") != 0:
            raise ValueError(f"Bilibili video info API failed: {payload.get('message') or payload.get('code')}")
        return payload.get("data") or {}

    async def _fetch_hot_comments(self, client: httpx.AsyncClient, aid: str) -> list[dict[str, Any]]:
        for sort in (2, 0):
            response = await client.get(
                "https://api.bilibili.com/x/v2/reply",
                params={
                    "type": 1,
                    "oid": aid,
                    "sort": sort,
                    "ps": 20,
                },
            )
            response.raise_for_status()
            payload = response.json()
            if payload.get("code") != 0:
                raise ValueError(f"Bilibili reply API failed: {payload.get('message') or payload.get('code')}")
            data = payload.get("data") or {}
            replies = data.get("replies") or []
            if isinstance(replies, list) and replies:
                return replies
        return []

    def _bilibili_headers(self, item_url: str, user_config: dict) -> dict[str, str]:
        headers = {
            "Accept": "application/json, text/plain, */*",
            "Referer": item_url or "https://www.bilibili.com/",
            "User-Agent": (
                "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
        }
        sessdata = str(user_config.get("cookie") or user_config.get("bilibili") or "").strip()
        if sessdata:
            headers["Cookie"] = sessdata if "=" in sessdata else f"SESSDATA={sessdata}"
        return headers

    def _comment_author(self, member: dict[str, Any], like_count: int) -> str:
        name = member.get("uname") or "Bilibili 用户"
        return f"{name} · {like_count}赞" if like_count else name

    def _clean_comment_text(self, value: str) -> str:
        text = html.unescape(value or "").replace("\r\n", "\n").replace("\r", "\n")
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    def _format_comment_time(self, value: Any) -> str | None:
        try:
            timestamp = int(value)
        except (TypeError, ValueError):
            return None
        return datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d")
