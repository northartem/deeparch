"""Раздача главной страницы: статика версионируется ?v=<mtime> (кэш браузера не держит старый код)."""
import re


def test_index_versions_static(client):
    r = client.get("/")
    assert r.status_code == 200
    for name in ("app.js", "styles.css", "vendor/mermaid.min.js"):
        m = re.search(re.escape(f"/static/{name}") + r"\?v=(\d+)", r.text)
        assert m, f"{name} без ?v="
        assert int(m.group(1)) > 0
    # версия совпадает с фактическим mtime файла
    import os

    import app.main as m
    js = os.path.join(m._static, "app.js")
    assert int(re.search(r"/static/app\.js\?v=(\d+)", r.text).group(1)) == int(os.stat(js).st_mtime)
