from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Dict, List, Optional


@dataclass
class Anchor:
    href: str
    text: str
    title: str = ""
    image_url: str = ""


@dataclass
class Metadata:
    title: str = ""
    description: str = ""
    og_title: str = ""
    og_description: str = ""
    og_image: str = ""
    canonical_url: str = ""


class AnchorCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.anchors: List[Anchor] = []
        self._current_href: Optional[str] = None
        self._current_title: str = ""
        self._current_text_parts: List[str] = []
        self._current_img_src: str = ""

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        if tag == "a":
            if self._current_href is not None:
                return  # ignore nested <a> — keep the outer anchor intact
            attr_map = dict(attrs)
            href = attr_map.get("href", "").strip()
            if not href:
                return
            self._current_href = href
            self._current_title = attr_map.get("title", "").strip()
            self._current_text_parts = []
            self._current_img_src = ""
        elif tag == "img" and self._current_href is not None and not self._current_img_src:
            attr_map = dict(attrs)
            src = attr_map.get("src", "").strip()
            if src and not src.startswith("data:"):
                self._current_img_src = src
            else:
                data_src = attr_map.get("data-src", "").strip()
                if data_src and not data_src.startswith("data:"):
                    self._current_img_src = data_src

    def handle_data(self, data: str) -> None:
        if self._current_href is not None:
            self._current_text_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or self._current_href is None:
            return
        text = " ".join(part.strip() for part in self._current_text_parts if part.strip()).strip()
        self.anchors.append(
            Anchor(href=self._current_href, text=text, title=self._current_title, image_url=self._current_img_src)
        )
        self._current_href = None
        self._current_title = ""
        self._current_text_parts = []
        self._current_img_src = ""


class MetadataCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.metadata = Metadata()
        self._in_title = False
        self._title_parts: List[str] = []

    def handle_starttag(self, tag: str, attrs: List[tuple]) -> None:
        attr_map: Dict[str, str] = dict(attrs)
        if tag == "title":
            self._in_title = True
            self._title_parts = []
            return
        if tag == "meta":
            name = attr_map.get("name", "").lower().strip()
            prop = attr_map.get("property", "").lower().strip()
            content = attr_map.get("content", "").strip()
            if name == "description" and content:
                self.metadata.description = content
            if prop == "og:title" and content:
                self.metadata.og_title = content
            if prop == "og:description" and content:
                self.metadata.og_description = content
            if prop == "og:image" and content:
                self.metadata.og_image = content
            return
        if tag == "link":
            rel = attr_map.get("rel", "").lower().strip()
            href = attr_map.get("href", "").strip()
            if rel == "canonical" and href:
                self.metadata.canonical_url = href

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "title":
            return
        self._in_title = False
        title = " ".join(part.strip() for part in self._title_parts if part.strip()).strip()
        if title:
            self.metadata.title = title


def extract_anchors(html: str) -> List[Anchor]:
    parser = AnchorCollector()
    parser.feed(html)
    parser.close()
    return parser.anchors


def extract_metadata(html: str) -> Metadata:
    parser = MetadataCollector()
    parser.feed(html)
    parser.close()
    return parser.metadata
