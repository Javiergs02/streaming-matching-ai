"""Discovery and rendering helpers for dynamically added Streamlit and HTML dashboards."""

from pathlib import Path
from typing import Callable, Dict, List, Optional
import os
import re


def get_custom_dashboards_dir() -> Path:
    """Returns the folder scanned for hot-loaded `.py` and `.html` dashboards."""
    configured = os.getenv("CUSTOM_DASHBOARDS_DIR")
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parent.parent / "custom_pages"


def _format_title(slug: str) -> str:
    clean = re.sub(r"[_-]+", " ", slug).strip()
    return clean.title() if clean else "Custom Dashboard"


def _safe_url_slug(raw: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "_", raw).strip("_").lower()
    return slug or "custom"


def discover_custom_dashboards(base_dir: Optional[Path] = None) -> List[Dict[str, object]]:
    """Discovers `.py`, `.html`/`.htm`, and `<slug>/index.html` entries in `base_dir`."""
    target_dir = Path(base_dir) if base_dir is not None else get_custom_dashboards_dir()
    if not target_dir.exists() or not target_dir.is_dir():
        return []

    discovered: List[Dict[str, object]] = []
    seen_urls: set[str] = set()

    for entry in sorted(target_dir.iterdir(), key=lambda p: p.name.lower()):
        if entry.name.startswith(".") or entry.name.startswith("_"):
            continue

        if entry.is_file() and entry.suffix.lower() == ".py":
            slug = _safe_url_slug(entry.stem)
            url_path = f"custom_{slug}"
            if url_path in seen_urls:
                continue
            seen_urls.add(url_path)
            discovered.append({
                "kind": "py",
                "slug": slug,
                "url_path": url_path,
                "title": _format_title(entry.stem),
                "icon": "🧩",
                "path": entry,
            })
        elif entry.is_file() and entry.suffix.lower() in (".html", ".htm"):
            slug = _safe_url_slug(entry.stem)
            url_path = f"custom_{slug}"
            if url_path in seen_urls:
                continue
            seen_urls.add(url_path)
            discovered.append({
                "kind": "html",
                "slug": slug,
                "url_path": url_path,
                "title": _format_title(entry.stem),
                "icon": "📄",
                "path": entry,
            })
        elif entry.is_dir():
            index_file = entry / "index.html"
            if index_file.exists() and index_file.is_file():
                slug = _safe_url_slug(entry.name)
                url_path = f"custom_{slug}"
                if url_path in seen_urls:
                    continue
                seen_urls.add(url_path)
                discovered.append({
                    "kind": "html",
                    "slug": slug,
                    "url_path": url_path,
                    "title": _format_title(entry.name),
                    "icon": "📄",
                    "path": index_file,
                })

    return discovered


def make_html_page_renderer(html_path: Path, title: str, slug: str) -> Callable[[], None]:
    """Creates a named Streamlit callable that renders a standalone HTML file."""
    def _render_html_dashboard() -> None:
        import streamlit as st
        import streamlit.components.v1 as components
        from utils.styling import apply_portal_style

        st.set_page_config(page_title=title, layout="wide", page_icon="📄")
        apply_portal_style()
        html_content = Path(html_path).read_text(encoding="utf-8", errors="replace")
        components.html(html_content, height=900, scrolling=True)

    _render_html_dashboard.__name__ = f"custom_html_{slug}"
    return _render_html_dashboard
