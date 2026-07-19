import os

_SPA = os.path.join(
    os.path.dirname(__file__), "..", "..", "pikaraoke", "static", "spa-navigation.js"
)


def _read():
    with open(_SPA, encoding="utf-8") as f:
        return f.read()


def test_execute_scripts_skips_module_and_importmap():
    """P2-7: executeScripts re-runs a fetched page's inline scripts as classic scripts on every
    SPA navigation. base.html's <script type="module"> bootstrap and <script type="importmap">
    would then throw an uncaught SyntaxError ('import statement outside a module' / invalid
    importmap-as-JS). Those run once at initial page load; executeScripts must skip them."""
    js = _read()
    idx = js.index("function executeScripts")
    body = js[idx : idx + 800]
    assert "module" in body and "importmap" in body
    assert "!== 'module'" in body or '!== "module"' in body
    assert "!== 'importmap'" in body or '!== "importmap"' in body
