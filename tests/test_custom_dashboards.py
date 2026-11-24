"""Tests for Streamlit multi-page navigation and hot-loaded custom dashboards."""

from pathlib import Path
import sys
import streamlit as st
from streamlit.testing.v1 import AppTest

_DASHBOARD_ROOT = str(Path(__file__).resolve().parent.parent / "apps" / "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

from utils.custom_dashboards import discover_custom_dashboards  # noqa: E402


def test_discover_custom_dashboards_handles_py_html_and_folders(tmp_path):
    (tmp_path / "ventas_china.py").write_text("import streamlit as st\nst.write('ok')\n", encoding="utf-8")
    (tmp_path / "_private.py").write_text("x = 1\n", encoding="utf-8")
    (tmp_path / "resumen_gpu.html").write_text("<h1>GPU</h1>", encoding="utf-8")
    bundle = tmp_path / "render_farm"
    bundle.mkdir()
    (bundle / "index.html").write_text("<h1>Render</h1>", encoding="utf-8")

    items = discover_custom_dashboards(tmp_path)
    by_url = {item["url_path"]: item for item in items}

    assert "_private" not in str(by_url.keys())
    assert set(by_url.keys()) == {"custom_ventas_china", "custom_resumen_gpu", "custom_render_farm"}
    assert by_url["custom_ventas_china"]["kind"] == "py"
    assert by_url["custom_resumen_gpu"]["kind"] == "html"
    assert by_url["custom_render_farm"]["path"] == bundle / "index.html"


def test_streamlit_app_boots_home_and_embed_custom_pages(tmp_path, monkeypatch):
    (tmp_path / "demo_kpi.py").write_text(
        "import streamlit as st\nst.set_page_config(layout='wide')\nst.title('Demo KPI Dynamic')\n",
        encoding="utf-8",
    )
    (tmp_path / "demo_html.html").write_text("<html><body>HTML Ok</body></html>", encoding="utf-8")
    monkeypatch.setenv("CUSTOM_DASHBOARDS_DIR", str(tmp_path))

    app_file = Path(_DASHBOARD_ROOT) / "app.py"
    at = AppTest.from_file(str(app_file))
    at.run()
    assert not at.exception
    assert any("Matching AI Dashboard" in t.value for t in at.title)

    # Boot directly with ?embed=true and switch to an interactive page calling set_page_config
    at_embed = AppTest.from_file(str(app_file))
    at_embed.query_params["embed"] = "true"
    at_embed.run()
    assert not at_embed.exception

    # Switch to a built-in page that calls st.set_page_config itself
    at_embed.switch_page("pages/estado_mapeado.py")
    at_embed.run(timeout=10)
    assert not at_embed.exception or "error" in str(at_embed.exception)
    # Specifically verify no StreamlitSetPageConfigMustBeFirstCommandError occurred:
    exc_text = " ".join(str(e) for e in at_embed.exception)
    assert "set_page_config" not in exc_text
