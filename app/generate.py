"""Multi-stage generation. Facts come from static analysis; the LLM only explains them."""
import re

from . import config, llm
from .analyze import classify_layer, component_of
from .schemas import Architecture, EndpointDescList, QAList


def fmt_chunks(chunks, limit=800):
    return "\n\n".join(f"### {c['path']}:{c['start']}-{c['end']}\n{c['text'][:limit]}" for c in chunks)


def overview(a, job_id=None):
    prompt = (f"Repository facts:\nLanguages: {a['languages']}\nDetected stack: {a['stack']}\n"
              f"Folder tree:\n{a['tree']}\n\nREADME (truncated):\n{a['readme'] or 'none'}\n\n"
              "In 4-6 sentences: what does this project do, who is it for, and what is its tech stack?")
    return llm.ask(prompt, stage="overview", job_id=job_id)


def summarize_components(a, ridx, job_id=None, progress=None):
    names = [n for n in a["component_files"]][:config.MAX_COMPONENTS]
    out = {}
    for i, name in enumerate(names):
        chunks = ridx.search(f"main purpose and responsibilities of the {name} module", k=6, component=name)
        if not chunks:
            continue
        out[name] = llm.ask(
            f"Component: {name}\nCode excerpts:\n{fmt_chunks(chunks)}\n\n"
            "Summarize what this component does in 2-3 sentences.",
            stage="component_summary", job_id=job_id)
        if progress:
            progress(i + 1, len(names))
    return out


def architecture(a, overview_text, summaries, job_id=None):
    comp_text = "\n".join(f"- {n}: {s}" for n, s in summaries.items())
    edges = "\n".join(f"- {e['from']} -> {e['to']} ({e['weight']} imports)" for e in a["graph"]["edges"]) or "none found"
    prompt = (f"Project overview:\n{overview_text}\n\nComponent summaries:\n{comp_text}\n\n"
              f"Verified import dependencies:\n{edges}\n\n"
              f"Use EXACTLY these component names: {list(summaries)}.\n"
              "Return: summary (architecture in 3-4 sentences), data_flow (how a request/data moves "
              "through the components, 3-4 sentences), and components (name + one-sentence responsibility).")
    arch = llm.ask(prompt, schema=Architecture, stage="architecture", job_id=job_id)
    resp = {c.name: c.responsibility for c in arch.components}
    # Facts are merged deterministically: LLM wording + verified dependencies.
    route_comps = {component_of(r["file"]) for r in a["routes"]}
    components = []
    for name, summ in summaries.items():
        components.append({
            "name": name,
            "responsibility": resp.get(name) or summ,
            "depends_on": [e["to"] for e in a["graph"]["edges"] if e["from"] == name and e["to"] in summaries],
            "has_routes": name in route_comps,
            "files": a["component_files"].get(name, 0),
            "layer": classify_layer(name, name in route_comps),
            "loc": a["component_info"].get(name, {}).get("loc", 0),
            "files_list": a["component_info"].get(name, {}).get("files", []),
            "symbols": a["component_info"].get(name, {}).get("symbols", []),
            "languages": a["component_info"].get(name, {}).get("languages", {})})
    edges = [e for e in a["graph"]["edges"] if e["from"] in summaries and e["to"] in summaries]
    return {"summary": arch.summary, "data_flow": arch.data_flow, "components": components, "edges": edges}


def to_mermaid(arch):
    """Built in plain Python so the syntax is always valid."""
    ids = {c["name"]: f"c{i}" for i, c in enumerate(arch["components"])}
    clean = lambda s: re.sub(r'["\[\]()<>{}]', "'", s)
    lines = ["graph TD"]
    if any(c["has_routes"] for c in arch["components"]):
        lines.append('  client(("Client"))')
    for c in arch["components"]:
        lines.append(f'  {ids[c["name"]]}["{clean(c["name"])}<br/>{c["files"]} files"]')
    for c in arch["components"]:
        if c["has_routes"]:
            lines.append(f'  client --> {ids[c["name"]]}')
        for d in c["depends_on"]:
            lines.append(f'  {ids[c["name"]]} --> {ids[d]}')
    return "\n".join(lines)


def describe_endpoints(routes, job_id=None, limit=60, batch=10):
    routes = routes[:limit]
    result = [{k: v for k, v in r.items() if k != "snippet"} | {"description": "", "component": component_of(r["file"])} for r in routes]
    for s in range(0, len(routes), batch):
        part = routes[s:s + batch]
        listing = "\n\n".join(f"[{s + i}] {r['method']} {r['path']}\n{r['snippet']}" for i, r in enumerate(part))
        try:
            res = llm.ask(f"Endpoints with code:\n{listing}\n\nFor each endpoint index, write a one-line "
                          "description of what it does.", schema=EndpointDescList,
                          stage="endpoint_descriptions", job_id=job_id)
            for item in res.items:
                if 0 <= item.index < len(result):
                    result[item.index]["description"] = item.description
        except RuntimeError:
            pass    # endpoints are still listed, just without descriptions
    return result


QA_QUERIES = ["data flow and request handling", "database and storage", "authentication and security",
              "configuration, scaling and performance"]


def interview_qa(a, ridx, overview_text, arch, job_id=None):
    seen, chunks = set(), []
    for q in QA_QUERIES:
        for c in ridx.search(q, k=3):
            if (c["path"], c["start"]) not in seen:
                seen.add((c["path"], c["start"]))
                chunks.append(c)
    prompt = (f"Project overview:\n{overview_text}\n\nArchitecture:\n{arch['summary']}\n{arch['data_flow']}\n\n"
              f"Code excerpts:\n{fmt_chunks(chunks, 700)}\n\n"
              "Write 8 system-design interview questions a candidate could be asked about THIS codebase "
              "(data flow, scalability, bottlenecks, trade-offs, failure handling, security). "
              "Give a concise model answer for each, grounded in the code above.")
    return [q.model_dump() for q in llm.ask(prompt, schema=QAList, stage="interview_qa", job_id=job_id).items]
