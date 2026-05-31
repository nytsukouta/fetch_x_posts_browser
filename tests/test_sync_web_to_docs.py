from pathlib import Path

import sync_web_to_docs


def test_sync_rewrites_app_js_data_url(tmp_path):
    source = tmp_path / "web"
    dest = tmp_path / "docs"
    source.mkdir()
    (source / "app.js").write_text(
        'const DATA_URL = "../data/output/schedule_list.json";\n'
        'console.log("HTTP サーバー経由で開いているか確認してください。");\n',
        encoding="utf-8",
    )
    (source / "index.html").write_text("<html></html>", encoding="utf-8")
    (source / "styles.css").write_text("body{}", encoding="utf-8")

    sync_web_to_docs.sync_static_assets(source, dest)

    app_js = (dest / "app.js").read_text(encoding="utf-8")
    assert 'const DATA_URL = "./data/schedule_list.json";' in app_js
    assert "../data/output/schedule_list.json" not in app_js
    assert "schedule_list.json が生成されているか確認してください。" in app_js
    assert (dest / "index.html").read_text(encoding="utf-8") == "<html></html>"
    assert (dest / "styles.css").read_text(encoding="utf-8") == "body{}"


def test_sync_skips_dotfiles_and_dirs(tmp_path):
    source = tmp_path / "web"
    dest = tmp_path / "docs"
    source.mkdir()
    (source / ".hidden").write_text("x", encoding="utf-8")
    (source / "data").mkdir()
    (source / "index.html").write_text("<html></html>", encoding="utf-8")

    synced = sync_web_to_docs.sync_static_assets(source, dest)
    names = {Path(p).name for p in synced}
    assert names == {"index.html"}
    assert not (dest / ".hidden").exists()
    assert not (dest / "data").exists()
