import pytest
from app.analyze import analyze_repo, extract_routes, build_graph, python_imports
from app.chunk import chunk_files
from app.ingest import parse_repo_url


def test_fastapi_routes():
    code = '@app.get("/users")\nasync def list_users():\n    pass\n\n@router.post("/users")\ndef create():\n    pass\n'
    r = extract_routes("app/api.py", code)
    assert [(x["method"], x["path"], x["handler"]) for x in r] == [("GET", "/users", "list_users"), ("POST", "/users", "create")]


def test_flask_methods():
    r = extract_routes("a.py", '@app.route("/login", methods=["POST", "GET"])\ndef login():\n    pass\n')
    assert r[0]["method"] == "POST/GET" and r[0]["path"] == "/login"


def test_express_and_spring():
    assert extract_routes("s.js", "router.delete('/items/:id', handler)")[0]["method"] == "DELETE"
    j = extract_routes("C.java", '@GetMapping("/orders")\npublic List<Order> all() {}')
    assert j[0]["path"] == "/orders"


def test_python_client_calls_not_routes():
    assert extract_routes("x.py", "requests.get('http://x')\napi.get('/not-a-route')") == []


def test_import_graph():
    files = [("api/routes.py", "from services.users import get\nimport db.models"),
             ("services/users.py", "import db.models"),
             ("db/models.py", "x = 1")]
    g = build_graph(files)
    pairs = {(e["from"], e["to"]) for e in g["edges"]}
    assert pairs == {("api", "services"), ("api", "db"), ("services", "db")}


def test_js_relative_imports():
    files = [("src/routes/a.js", "import x from '../services/b'"), ("src/services/b.js", "export const x = 1")]
    g = build_graph(files)
    assert {(e["from"], e["to"]) for e in g["edges"]} == {("src/routes", "src/services")}


def test_chunking_and_analyze():
    files = [("app/m.py", "def f():\n    return 1\n\nclass A:\n    pass\n"), ("README.md", "# hi")]
    chunks = chunk_files(files)
    assert len(chunks) == 2 and all(c["component"] == "app" for c in chunks)
    assert analyze_repo(files)["readme"] == "# hi"


def test_bad_python_does_not_crash():
    assert python_imports("def (:") == []


@pytest.mark.parametrize("url", ["http://github.com/a/b", "https://evil.com/a/b", "https://github.com/a", "file:///etc/passwd",
                                 "https://github.com/a/b/../../c", "https://github.com.evil.com/a/b"])
def test_bad_urls_rejected(url):
    with pytest.raises(ValueError):
        parse_repo_url(url)


def test_good_urls():
    assert parse_repo_url("https://github.com/tiangolo/fastapi.git/")[2] == "https://github.com/tiangolo/fastapi"


def test_layer_classification():
    from app.analyze import classify_layer
    assert classify_layer("app/api", True) == "api"
    assert classify_layer("models", False) == "data"
    assert classify_layer("app/auth", True) == "auth"
    assert classify_layer("tests", False) == "support"
    assert classify_layer("services", False) == "logic"
    assert classify_layer("frontend", False) == "client"
    assert classify_layer("controllers", False) == "api"


def test_component_details_and_symbols():
    from app.analyze import component_details, extract_symbols
    py = "class User:\n    pass\n\ndef make():\n    pass\n\ndef _hidden():\n    pass\n"
    assert [(s["kind"], s["name"]) for s in extract_symbols("m/a.py", py)] == [("class", "User"), ("function", "make")]
    assert extract_symbols("s/a.js", "export class Foo {}\nexport async function bar() {}")[1]["name"] == "bar"
    info = component_details([("m/a.py", py), ("m/b.py", "x=1")], [])
    assert info["m"]["loc"] > 0 and info["m"]["languages"] == {"Python": 2}
