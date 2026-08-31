from app.transform import resource_url, rewrite_css_urls


def test_css_rewrite_resolves_relative_to_the_css_resource():
    css = "@import '../base.css'; .x{src:url(../fonts/A.WOFF2)} .y{background:url(data:image/png;base64,AA)}"

    rendered = rewrite_css_urls(css, "dict", resource_path="styles/theme/main.css")

    assert "/api/v1/dictionaries/dict/resources/styles/base.css" in rendered
    assert "/api/v1/dictionaries/dict/resources/styles/theme/../fonts/a.woff2" not in rendered
    assert "/api/v1/dictionaries/dict/resources/styles/fonts/a.woff2" in rendered
    assert "data:image/png;base64,AA" in rendered


def test_resource_url_decodes_percent_encoding_once_and_rejects_traversal():
    assert resource_url("dict", "images/A%20B.PNG") == "/api/v1/dictionaries/dict/resources/images/a%20b.png"
    try:
        resource_url("dict", "%2e%2e/secret.txt")
    except ValueError:
        pass
    else:
        raise AssertionError("resource traversal was accepted")


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
