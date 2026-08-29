from app.transform import resource_url, rewrite_css_urls, transform_article_html


def test_article_transform_matches_upstream_scheme_contract():
    raw = """
    <html><head><link rel="stylesheet" href="Dict.CSS"><script src="dict.js"></script></head>
    <body style="background:url(images/BG.PNG)">
      <a id="entry" href="entry://Ice%20Cream">entry</a>
      <a id="sound" href="sound://audio/Hello.MP3">sound</a>
      <a id="external" href="//example.test/page">external</a>
      <img src="images/Picture.PNG" srcset="small.png 1x, large.png 2x">
      <video src="media/clip.mp4" poster="images/poster.jpg"></video>
      <object data="movie/demo.mp4"></object>
      <style>.icon { background: url('icons/a.svg') }</style>
    </body></html>
    """

    rendered = transform_article_html(raw, "abc123")

    assert "<gd-section-html>" in rendered
    assert "<gd-section-head>" in rendered
    assert "<gd-section-body" in rendered
    assert 'href="/api/v1/dictionaries/abc123/resources/dict.css"' in rendered
    assert 'src="/api/v1/dictionaries/abc123/resources/dict.js"' in rendered
    assert 'data-gd-action="lookup"' in rendered
    assert 'data-gd-word="Ice Cream"' in rendered
    assert 'data-gd-dictionary="abc123"' in rendered
    assert 'href="#gdlookup=Ice%20Cream"' in rendered
    assert 'data-gd-action="audio"' in rendered
    assert 'data-gd-audio="/api/v1/dictionaries/abc123/resources/audio/hello.mp3"' in rendered
    assert 'href="https://example.test/page"' in rendered
    assert "/resources/images/picture.png" in rendered
    assert "/resources/small.png 1x, /api/v1/dictionaries/abc123/resources/large.png 2x" in rendered
    assert "/resources/media/clip.mp4" in rendered
    assert "/resources/images/poster.jpg" in rendered
    assert "/resources/movie/demo.mp4" in rendered
    assert "/resources/icons/a.svg" in rendered


def test_css_rewrite_resolves_relative_to_the_css_resource():
    css = "@import '../base.css'; .x{src:url(../fonts/A.WOFF2)} .y{background:url(data:image/png;base64,AA)}"

    rendered = rewrite_css_urls(css, "dict", resource_path="styles/theme/main.css")

    assert "/api/v1/dictionaries/dict/resources/styles/base.css" in rendered
    assert "/api/v1/dictionaries/dict/resources/styles/theme/../fonts/a.woff2" not in rendered
    assert "/api/v1/dictionaries/dict/resources/styles/fonts/a.woff2" in rendered
    assert "data:image/png;base64,AA" in rendered


def test_resource_url_decodes_percent_encoding_once_and_rejects_traversal():
    assert resource_url("dict", "images/A%20B.PNG") == "/api/v1/dictionaries/dict/resources/images/a%20b.png"
    rendered = transform_article_html('<img src="%2e%2e/secret.txt">', "dict")
    assert 'src="about:blank"' in rendered


def test_native_resource_url_can_preserve_filesystem_case():
    assert resource_url(
        "dict",
        "scripts/Dictionary-UI.js",
        fold_case=False,
    ) == "/api/v1/dictionaries/dict/resources/scripts/Dictionary-UI.js"


def test_scoped_golden_dict_resource_authority_is_not_part_of_the_path():
    assert resource_url(
        "dict",
        "bres://dict/Fonts/A.WOFF2",
        relative_to="styles/nested/theme.css",
        fold_case=False,
    ) == "/api/v1/dictionaries/dict/resources/Fonts/A.WOFF2"
