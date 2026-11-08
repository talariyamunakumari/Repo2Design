"""Static analysis: facts extracted with code, NOT with the LLM (so they are reliable)."""
import ast
import json
import posixpath
import re
from collections import Counter

LANG_BY_EXT = {".py": "Python", ".js": "JavaScript", ".jsx": "JavaScript", ".ts": "TypeScript",
               ".tsx": "TypeScript", ".java": "Java", ".kt": "Kotlin", ".go": "Go", ".rb": "Ruby",
               ".rs": "Rust", ".php": "PHP", ".cs": "C#", ".cpp": "C++", ".c": "C"}
SOURCE_EXT = set(LANG_BY_EXT)
PY, JS, JVM = {".py"}, {".js", ".jsx", ".ts", ".tsx"}, {".java", ".kt"}
ROOT_PARENTS = {"src", "app", "lib", "backend", "server", "packages"}

# (regex, fixed_method or None, file extensions it applies to)
ROUTE_PATTERNS = [
    (re.compile(r'@\w+(?:\.\w+)*\.(get|post|put|delete|patch)\(\s*[\'"]([^\'"]*)'), None, PY),
    (re.compile(r'@\w+(?:\.\w+)*\.route\(\s*[\'"]([^\'"]*)'), "ANY", PY),
    (re.compile(r'\b(?:app|router|server|api)\.(get|post|put|delete|patch)\(\s*[\'"`]([^\'"`]*)'), None, JS),
    (re.compile(r'@(Get|Post|Put|Delete|Patch)Mapping\(\s*(?:value\s*=\s*|path\s*=\s*)?"([^"]*)'), None, JVM),
    (re.compile(r'@RequestMapping\(\s*(?:value\s*=\s*|path\s*=\s*)?"([^"]*)'), "ANY", JVM),
]
STACK_KEYWORDS = {
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django", "sqlalchemy": "SQLAlchemy",
    "celery": "Celery", "redis": "Redis", "psycopg": "PostgreSQL", "pymongo": "MongoDB",
    "kafka": "Kafka", "express": "Express", "react": "React", "next": "Next.js",
    "vue": "Vue", "mongoose": "MongoDB", "sequelize": "Sequelize", "prisma": "Prisma",
    "spring-boot": "Spring Boot", "hibernate": "Hibernate", "gin-gonic": "Gin",
    "torch": "PyTorch", "tensorflow": "TensorFlow", "langchain": "LangChain", "openai": "OpenAI API",
}
CONFIG_FILES = {"requirements.txt": "Python", "pyproject.toml": "Python", "package.json": "Node.js",
                "pom.xml": "Java/Maven", "build.gradle": "Java/Gradle", "go.mod": "Go",
                "Dockerfile": "Docker", "docker-compose.yml": "Docker Compose",
                "docker-compose.yaml": "Docker Compose", "Cargo.toml": "Rust"}


def ext_of(path: str) -> str:
    return posixpath.splitext(path)[1].lower()


def component_of(path: str) -> str:
    """Map a file path to a 'component' (top-level folder, or src/<x> style)."""
    parts = path.split("/")
    if len(parts) == 1:
        return "root"
    if parts[0] in ROOT_PARENTS and len(parts) > 2:
        return f"{parts[0]}/{parts[1]}"
    return parts[0]


def extract_routes(path: str, text: str):
    ext = ext_of(path)
    lines = text.splitlines()
    seen, routes = set(), []
    for i, line in enumerate(lines):
        for rx, fixed, exts in ROUTE_PATTERNS:
            if ext not in exts:
                continue
            m = rx.search(line)
            if not m:
                continue
            g = m.groups()
            method, route = (fixed, g[0]) if fixed else (g[0].upper(), g[1])
            if fixed == "ANY" and ext in PY:  # Flask: methods=["POST", ...]
                mm = re.search(r'methods\s*=\s*\[([^\]]*)\]', line)
                if mm:
                    method = "/".join(re.findall(r'[A-Za-z]+', mm.group(1))).upper()
            handler = None
            for nxt in lines[i:i + 6]:
                h = re.search(r'(?:async\s+)?def\s+(\w+)|function\s+(\w+)', nxt)
                if h:
                    handler = h.group(1) or h.group(2)
                    break
            key = (method, route, path, i + 1)
            if key in seen:
                continue
            seen.add(key)
            routes.append({"method": method, "path": route or "/", "file": path, "line": i + 1,
                           "handler": handler, "snippet": "\n".join(lines[i:i + 6])[:300]})
    return routes


def python_imports(text: str):
    try:
        tree = ast.parse(text)
    except (SyntaxError, ValueError):
        return []
    mods = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            mods += [a.name for a in n.names]
        elif isinstance(n, ast.ImportFrom) and n.module and n.level == 0:
            mods.append(n.module)
    return mods


JS_IMPORT_RE = re.compile(r'''(?:import\s+(?:[^'"]*?\s+from\s+)?|export\s+[^'"]*?\s+from\s+|require\(\s*)['"]([^'"]+)['"]''')


def js_imports(text: str):
    return JS_IMPORT_RE.findall(text)


def build_graph(files):
    """files: [(path, text)] -> component graph from internal imports."""
    src_files = [(p, t) for p, t in files if ext_of(p) in SOURCE_EXT]
    components = {component_of(p) for p, _ in src_files}
    root_modules = {posixpath.splitext(p)[0] for p, _ in src_files if "/" not in p}
    edges = Counter()

    def resolve_py(mod):
        parts = mod.split(".")
        for n in range(len(parts), 0, -1):
            cand = "/".join(parts[:n])
            for prefix in ("", "src/"):
                if prefix + cand in components:
                    return prefix + cand
        return "root" if parts[0] in root_modules else None

    for path, text in src_files:
        src, ext = component_of(path), ext_of(path)
        targets = []
        if ext in PY:
            targets = [resolve_py(m) for m in python_imports(text)]
        elif ext in JS:
            for spec in js_imports(text):
                if spec.startswith("."):
                    tgt = posixpath.normpath(posixpath.join(posixpath.dirname(path), spec))
                    if not tgt.startswith(".."):
                        targets.append(component_of(tgt + ext))
        for t in targets:
            if t and t != src and t in components:
                edges[(src, t)] += 1
    return {"components": sorted(components),
            "edges": [{"from": a, "to": b, "weight": w} for (a, b), w in sorted(edges.items())]}


def detect_stack(files):
    blob, found = "", []
    for path, text in files:
        name = posixpath.basename(path)
        if name in CONFIG_FILES and CONFIG_FILES[name] not in found:
            found.append(CONFIG_FILES[name])
        if name in ("requirements.txt", "pyproject.toml", "package.json", "pom.xml", "build.gradle", "go.mod"):
            blob += text.lower() + "\n"
    for key, label in STACK_KEYWORDS.items():
        if key in blob and label not in found:
            found.append(label)
    return found


def tree_summary(paths, max_lines=60):
    """Depth-2 folder summary with file counts."""
    counts = Counter()
    for p in paths:
        parts = p.split("/")
        counts["/".join(parts[:2]) if len(parts) > 2 else (parts[0] + "/" if len(parts) > 1 else parts[0])] += 1
    lines = [f"{k}  ({v} files)" if k.endswith("/") or "/" in k else k for k, v in sorted(counts.items())]
    return "\n".join(lines[:max_lines])


SUPPORT_TOK = {"test", "tests", "spec", "specs", "e2e", "docs", "doc", "scripts", "script", "tools", "tooling", "ci",
               "deploy", "infra", "config", "configs", "settings", "examples", "example", "benchmarks", "docker", "k8s", "build"}
CLIENT_TOK = {"frontend", "client", "web", "ui", "static", "templates", "template", "views", "public", "components",
              "pages", "assets", "styles", "css"}
AUTH_TOK = {"auth", "security", "oauth", "jwt", "login", "permissions", "session", "sessions"}
DATA_TOK = {"db", "database", "models", "model", "entities", "entity", "repository", "repositories", "repo", "dao",
            "orm", "schemas", "schema", "migrations", "migration", "store", "storage", "persistence", "data"}
API_TOK = {"api", "apis", "routes", "route", "routers", "router", "controllers", "controller", "handlers", "handler",
           "endpoints", "rest", "server", "resolvers", "graphql", "main"}


def classify_layer(name: str, has_routes: bool) -> str:
    """Heuristic architectural layer: client | api | logic | auth | data | support."""
    toks = set(re.split(r"[/_\-.\s]+", name.lower()))
    if toks & SUPPORT_TOK:
        return "support"
    if toks & AUTH_TOK:
        return "auth"
    if toks & DATA_TOK:
        return "data"
    if toks & API_TOK or has_routes:
        return "api"
    if toks & CLIENT_TOK:
        return "client"
    return "logic"


_JS_SYM = [(re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:abstract\s+)?class\s+(\w+)"), "class"),
           (re.compile(r"^\s*(?:export\s+)?(?:default\s+)?(?:async\s+)?function\s*\*?\s*(\w+)"), "function"),
           (re.compile(r"^\s*export\s+const\s+(\w+)\s*=\s*(?:async\s*)?(?:\(|function)"), "function")]
_JVM_SYM = [(re.compile(r"^\s*(?:public\s+|protected\s+|private\s+|abstract\s+|final\s+|static\s+|data\s+|sealed\s+|open\s+)*"
                        r"(?:class|interface|enum|record|object)\s+(\w+)"), "class")]
_GO_SYM = [(re.compile(r"^type\s+(\w+)\s+(?:struct|interface)"), "class"),
           (re.compile(r"^func\s+(?:\([^)]*\)\s*)?(\w+)"), "function")]


def extract_symbols(path: str, text: str, per_file: int = 15):
    ext, out = ext_of(path), []
    if ext in PY:
        try:
            tree = ast.parse(text)
        except (SyntaxError, ValueError):
            return []
        for n in tree.body:
            if isinstance(n, ast.ClassDef):
                out.append({"kind": "class", "name": n.name, "file": path, "line": n.lineno})
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith("_"):
                out.append({"kind": "function", "name": n.name, "file": path, "line": n.lineno})
        return out[:per_file]
    pats = _JS_SYM if ext in JS else _JVM_SYM if ext in JVM else _GO_SYM if ext == ".go" else []
    for i, line in enumerate(text.splitlines(), 1):
        for rx, kind in pats:
            m = rx.match(line)
            if m:
                out.append({"kind": kind, "name": m.group(1), "file": path, "line": i})
                break
        if len(out) >= per_file:
            break
    return out


def component_details(files, routes):
    """Per component: key files, symbols, languages, lines of code (used by the detail panel)."""
    info, route_files = {}, {r["file"] for r in routes}
    for path, text in files:
        if ext_of(path) not in SOURCE_EXT:
            continue
        d = info.setdefault(component_of(path), {"files": [], "symbols": [], "languages": Counter(), "loc": 0})
        n = text.count("\n") + 1
        d["files"].append({"path": path, "lines": n})
        d["loc"] += n
        d["languages"][LANG_BY_EXT[ext_of(path)]] += 1
        d["symbols"] += extract_symbols(path, text)
    for d in info.values():
        d["files"].sort(key=lambda f: (f["path"] not in route_files, -f["lines"]))
        d["files"] = d["files"][:12]
        classes = [x for x in d["symbols"] if x["kind"] == "class"][:8]
        funcs = [x for x in d["symbols"] if x["kind"] == "function"][:8]
        d["symbols"] = classes + funcs
        d["languages"] = dict(d["languages"].most_common())
    return info


def analyze_repo(files):
    paths = [p for p, _ in files]
    langs = Counter(LANG_BY_EXT[ext_of(p)] for p in paths if ext_of(p) in SOURCE_EXT)
    routes = []
    for p, t in files:
        if ext_of(p) in SOURCE_EXT:
            routes += extract_routes(p, t)
    readme = next((t for p, t in files if p.lower().startswith("readme") and "/" not in p), "")
    comp_files = Counter(component_of(p) for p in paths if ext_of(p) in SOURCE_EXT)
    return {"languages": dict(langs.most_common()), "stack": detect_stack(files),
            "routes": routes, "graph": build_graph(files), "tree": tree_summary(paths),
            "readme": readme[:3000], "component_files": dict(comp_files.most_common()),
            "component_info": component_details(files, routes),
            "file_count": len(paths)}


if __name__ == "__main__":  # quick manual check: python -m app.analyze <folder>
    import sys
    from . import ingest
    a = analyze_repo(ingest.load_files(sys.argv[1]))
    a.pop("readme")
    print(json.dumps(a, indent=2)[:6000])
