"""Continuity Graph & Custody Checklist engine (Round 3, Improvement C).

- Deterministic, evidence-backed graph of people, modules, tasks, documents, and services.
- Never invents edges: every edge carries claim_ids and evidence_refs.
- Strict backend secret rejection on all custody checklist free-text fields.
- Clearance-aware filtering across nodes, edges, risks, impact, and custody items.
"""

from __future__ import annotations

import json
import math
import re
from collections import defaultdict, deque
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from sqlalchemy.orm import Session

from app.engine.clearance import APPROVED_CLAIM_STATUSES, ViewerContext, effective_claim_clearance
from app.engine.types import max_clearance
from app.models import (
    Chunk,
    Claim,
    ClaimEvidence,
    CustodyEvent,
    CustodyItem,
    GraphEdge,
    GraphNode,
    Source,
    User,
)

VALID_CUSTODY_KINDS = {
    "repository",
    "hosting",
    "database",
    "domain",
    "CI/CD",
    "cloud account",
    "third-party API",
    "email/SaaS",
    "other",
}
VALID_CUSTODY_STATUSES = {"confirmed", "unconfirmed", "unknown", "transferred"}

# ── Secret rejection & redaction (backend-enforced) ──────────────────────────

SECRET_ERROR_MSG = "Do not store credentials; record who holds access instead."

_SECRET_PATTERNS: List[Tuple[str, re.Pattern[str]]] = [
    ("private key block", re.compile(r"-----BEGIN\s+(?:[A-Z0-9 ]+\s+)?PRIVATE KEY-----", re.IGNORECASE)),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[0-9A-Z]{16,}\b")),
    ("GitHub token", re.compile(r"\b(?:ghp|gho|ghu|ghs)_[A-Za-z0-9]{20,}\b|\bgithub_pat_[A-Za-z0-9_]{20,}\b")),
    ("API secret key prefix", re.compile(r"\b(?:sk-[A-Za-z0-9_\-]{16,}|xox[baprs]-[A-Za-z0-9\-]{10,}|AIza[0-9A-Za-z\-_]{20,})\b")),
    ("Bearer token", re.compile(r"\bBearer\s+[A-Za-z0-9._\-]{16,}\b", re.IGNORECASE)),
    (
        "credential assignment",
        re.compile(r"\b(?:password|passwd|pwd|secret|api_key|apikey|access_token|auth_token)\s*[:=]\s*\S+", re.IGNORECASE),
    ),
    (
        "credentialed connection string",
        re.compile(r"\b(?:postgres(?:ql)?|mysql|mongodb(?:\+srv)?|redis|amqp|https?)://[^/\s:@]+:[^/\s@]+@", re.IGNORECASE),
    ),
]
_TOKEN_CANDIDATE_RE = re.compile(r"[A-Za-z0-9+/_=\-]{28,}")


class SecretRejectedError(ValueError):
    """Raised when a custody checklist field contains secret-like material."""


def _shannon_entropy(s: str) -> float:
    if not s:
        return 0.0
    counts: Dict[str, int] = defaultdict(int)
    for ch in s:
        counts[ch] += 1
    n = len(s)
    return -sum((c / n) * math.log2(c / n) for c in counts.values())


def _is_high_entropy_secret(token: str) -> bool:
    if "/" in token and token.startswith(("http", "github", "src/", "app/")):
        return False
    classes = sum([
        any(c.islower() for c in token),
        any(c.isupper() for c in token),
        any(c.isdigit() for c in token),
        any(c in "+/_=-" for c in token),
    ])
    if classes < 3:
        return False
    return _shannon_entropy(token) >= 3.8


def contains_secret(value: Optional[str]) -> Optional[str]:
    """Return a short reason if value looks like a secret, else None."""
    if not value:
        return None
    for label, pat in _SECRET_PATTERNS:
        if pat.search(value):
            return label
    for tok in _TOKEN_CANDIDATE_RE.findall(value):
        if _is_high_entropy_secret(tok):
            return "high-entropy token"
    return None


def validate_no_secrets(fields: Dict[str, Optional[str]]) -> None:
    for fname, val in fields.items():
        if not val:
            continue
        hit = contains_secret(val)
        if hit:
            raise SecretRejectedError(f"{SECRET_ERROR_MSG} (detected {hit} in '{fname}').")


def redact_secrets(text: Optional[str]) -> str:
    if not text:
        return ""
    out = text
    for _label, pat in _SECRET_PATTERNS:
        out = pat.sub("[REDACTED]", out)
    for tok in _TOKEN_CANDIDATE_RE.findall(out):
        if _is_high_entropy_secret(tok):
            out = out.replace(tok, "[REDACTED]")
    return out


# ── Service pattern registry (deterministic custody suggestions) ─────────────

_SERVICE_PATTERNS: List[Tuple[str, str, re.Pattern[str]]] = [
    ("GitHub", "repository", re.compile(r"\bgithub\b", re.IGNORECASE)),
    ("Render", "hosting", re.compile(r"\brender(?:\.com|\.yaml)?\b", re.IGNORECASE)),
    ("Vercel", "hosting", re.compile(r"\bvercel\b", re.IGNORECASE)),
    ("Railway", "hosting", re.compile(r"\brailway\b", re.IGNORECASE)),
    ("Neon PostgreSQL", "database", re.compile(r"\bneon\b", re.IGNORECASE)),
    ("PostgreSQL", "database", re.compile(r"\bpostgres(?:ql)?\b", re.IGNORECASE)),
    ("Redis", "database", re.compile(r"\bredis\b", re.IGNORECASE)),
    ("AWS", "cloud account", re.compile(r"\b(?:aws|s3|kms|ec2|iam)\b", re.IGNORECASE)),
    ("Cloudflare", "domain", re.compile(r"\bcloudflare\b", re.IGNORECASE)),
    ("Stripe", "third-party API", re.compile(r"\bstripe\b", re.IGNORECASE)),
    ("Adyen", "third-party API", re.compile(r"\badyen\b", re.IGNORECASE)),
    ("SendGrid", "email/SaaS", re.compile(r"\bsendgrid\b", re.IGNORECASE)),
    ("Slack", "email/SaaS", re.compile(r"\bslack\b", re.IGNORECASE)),
    ("Auth0", "third-party API", re.compile(r"\bauth0\b", re.IGNORECASE)),
    ("Sentry", "CI/CD", re.compile(r"\bsentry\b", re.IGNORECASE)),
    ("GitHub Actions", "CI/CD", re.compile(r"\bgithub actions\b", re.IGNORECASE)),
]


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _json_list(raw: Any) -> List[Any]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            return val if isinstance(val, list) else []
        except Exception:
            return []
    return []


def _json_obj(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            val = json.loads(raw)
            return val if isinstance(val, dict) else {}
        except Exception:
            return {}
    return {}


def _norm_key(prefix: str, name: str) -> str:
    slug = re.sub(r"[^a-z0-9_.\-]+", "-", (name or "").strip().lower()).strip("-")
    return f"{prefix}:{slug or 'unknown'}"[:250]


# ── Deterministic Graph Build ────────────────────────────────────────────────

def _ev_refs_for(
    ev_rows: Sequence[ClaimEvidence],
    sources_by_id: Dict[str, Source],
) -> List[Dict[str, Any]]:
    refs: List[Dict[str, Any]] = []
    for ev in ev_rows[:5]:
        src = sources_by_id.get(ev.source_id) if ev.source_id else None
        ch = getattr(ev, "chunk", None)
        refs.append({
            "evidence_id": ev.id,
            "source_id": ev.source_id,
            "source_name": src.filename if src else ("interview" if ev.evidence_type == "interview_answer" else None),
            "locator": ch.locator if ch else None,
            "excerpt": redact_secrets((ev.excerpt or "")[:200]),
        })
    return refs


def rebuild_continuity_graph(db: Session, project_id: str) -> Dict[str, int]:
    """Idempotently rebuild GraphNode & GraphEdge rows from non-rejected claims with valid evidence."""
    db.query(GraphEdge).filter(GraphEdge.project_id == project_id).delete()
    db.query(GraphNode).filter(GraphNode.project_id == project_id).delete()
    db.flush()

    claims = (
        db.query(Claim)
        .filter(Claim.project_id == project_id, Claim.review_status != "rejected")
        .order_by(Claim.id.asc())
        .all()
    )
    sources_by_id = {s.id: s for s in db.query(Source).filter(Source.project_id == project_id).all()}
    ev_by_claim: Dict[str, List[ClaimEvidence]] = defaultdict(list)
    if claims:
        for ev in db.query(ClaimEvidence).filter(ClaimEvidence.claim_id.in_([c.id for c in claims])).all():
            ev_by_claim[ev.claim_id].append(ev)

    nodes_by_key: Dict[str, GraphNode] = {}

    def _get_node(
        key: str,
        ntype: str,
        label: str,
        clearance: str,
        review_status: str,
        meta: Optional[Dict[str, Any]] = None,
    ) -> GraphNode:
        n = nodes_by_key.get(key)
        if n is None:
            n = GraphNode(
                project_id=project_id,
                node_key=key,
                node_type=ntype,
                label=label[:255],
                clearance_level=clearance,
                review_status=review_status,
                metadata_json=json.dumps(meta or {}),
            )
            db.add(n)
            db.flush()
            nodes_by_key[key] = n
        else:
            # Upgrade review_status if any supporting claim is approved; tighten clearance only when all are restricted
            if review_status in APPROVED_CLAIM_STATUSES and n.review_status not in APPROVED_CLAIM_STATUSES:
                n.review_status = review_status
            if n.clearance_level == "restricted" and clearance != "restricted":
                n.clearance_level = clearance
        return n

    edges_acc: Dict[Tuple[str, str, str], Dict[str, Any]] = {}

    def _add_edge(
        src: GraphNode,
        dst: GraphNode,
        etype: str,
        claim: Claim,
        ev_refs: List[Dict[str, Any]],
        inferred: bool,
        clearance: str,
    ) -> None:
        if src.id == dst.id or not ev_refs:
            return
        k = (src.id, dst.id, etype)
        entry = edges_acc.get(k)
        if entry is None:
            edges_acc[k] = {
                "src": src.id,
                "dst": dst.id,
                "etype": etype,
                "inferred": inferred,
                "claim_ids": [claim.id],
                "ev_refs": list(ev_refs),
                "clearance": clearance,
                "review_status": claim.review_status,
            }
        else:
            if claim.id not in entry["claim_ids"]:
                entry["claim_ids"].append(claim.id)
            if claim.review_status in APPROVED_CLAIM_STATUSES:
                entry["review_status"] = claim.review_status
            if not inferred:
                entry["inferred"] = False
            entry["clearance"] = max_clearance([entry["clearance"], clearance])

    for c in claims:
        ev_rows = ev_by_claim.get(c.id, [])
        if not ev_rows:
            continue  # Never invent edges without evidence
        ev_refs = _ev_refs_for(ev_rows, sources_by_id)
        cl_clear = effective_claim_clearance(db, c)
        is_inf = c.verification_status == "inferred"
        mod_name = (c.module or "general").strip()
        mod_node = _get_node(_norm_key("module", mod_name), "module", mod_name, cl_clear, c.review_status)

        attrs = _json_obj(c.attrs_json)
        person_name = (c.owner_name or c.author or "").strip()
        if person_name and person_name.lower() not in ("unassigned", "none", "unknown"):
            p_node = _get_node(_norm_key("person", person_name), "person", person_name, cl_clear, c.review_status)
            if c.claim_type == "ownership":
                _add_edge(p_node, mod_node, "owns", c, ev_refs, is_inf, cl_clear)
            elif c.claim_type == "decision":
                _add_edge(p_node, mod_node, "decided", c, ev_refs, is_inf, cl_clear)
            elif c.claim_type == "contribution":
                _add_edge(p_node, mod_node, "contributed_to", c, ev_refs, is_inf, cl_clear)
            elif c.owner_name:
                _add_edge(p_node, mod_node, "owns", c, ev_refs, True, cl_clear)

        # Task nodes & dependency/blocker edges
        if c.claim_type in ("task_status", "dependency", "blocker"):
            t_label = (c.title or c.text[:80]).strip()
            t_key_str = c.task_key or t_label
            t_node = _get_node(
                _norm_key("task", t_key_str),
                "task",
                t_label,
                cl_clear,
                c.review_status,
                {"module": mod_name, "claim_type": c.claim_type},
            )
            _add_edge(t_node, mod_node, "contributed_to", c, ev_refs, True, cl_clear)
            dep_raw = attrs.get("depends_on") or attrs.get("blocked_by")
            deps = dep_raw if isinstance(dep_raw, list) else ([dep_raw] if isinstance(dep_raw, str) and dep_raw.strip() else [])
            for d in deps:
                d_label = str(d).strip()
                if not d_label:
                    continue
                d_node = _get_node(_norm_key("task", d_label), "task", d_label, cl_clear, c.review_status, {"module": mod_name})
                edge_t = "blocks" if c.claim_type == "blocker" else "depends_on"
                _add_edge(t_node, d_node, edge_t, c, ev_refs, is_inf, cl_clear)

        # Document edges from supporting sources
        for ev in ev_rows:
            if not ev.source_id or ev.source_id not in sources_by_id:
                continue
            src = sources_by_id[ev.source_id]
            doc_clear = src.clearance_level or cl_clear
            doc_node = _get_node(
                _norm_key("document", src.id),
                "document",
                src.filename,
                doc_clear,
                c.review_status,
                {"source_id": src.id, "source_type": src.type},
            )
            _add_edge(doc_node, mod_node, "documents", c, ev_refs, is_inf, max_clearance([cl_clear, doc_clear]))

        # Service nodes detected from claim text
        for svc_name, svc_kind, pat in _SERVICE_PATTERNS:
            if pat.search(c.text or ""):
                s_node = _get_node(
                    _norm_key("service", svc_name),
                    "service",
                    svc_name,
                    cl_clear,
                    c.review_status,
                    {"kind": svc_kind},
                )
                _add_edge(mod_node, s_node, "depends_on", c, ev_refs, True, cl_clear)

    for e in edges_acc.values():
        db.add(
            GraphEdge(
                project_id=project_id,
                source_node_id=e["src"],
                target_node_id=e["dst"],
                edge_type=e["etype"],
                inferred=e["inferred"],
                claim_ids_json=json.dumps(e["claim_ids"]),
                evidence_refs_json=json.dumps(e["ev_refs"]),
                clearance_level=e["clearance"],
                review_status=e["review_status"],
            )
        )
    db.flush()
    suggest_custody_items(db, project_id, claims=claims, sources_by_id=sources_by_id)
    db.commit()
    return {"nodes": len(nodes_by_key), "edges": len(edges_acc)}


def suggest_custody_items(
    db: Session,
    project_id: str,
    *,
    claims: Optional[List[Claim]] = None,
    sources_by_id: Optional[Dict[str, Source]] = None,
) -> int:
    """Deterministically suggest unconfirmed CustodyItems from claims/chunks (with secret redaction)."""
    if claims is None:
        claims = (
            db.query(Claim)
            .filter(Claim.project_id == project_id, Claim.review_status != "rejected")
            .all()
        )
    existing_names = {
        (ci.name or "").strip().lower()
        for ci in db.query(CustodyItem).filter(CustodyItem.project_id == project_id).all()
    }
    created = 0
    for svc_name, svc_kind, pat in _SERVICE_PATTERNS:
        if svc_name.lower() in existing_names:
            continue
        matched_claims = [c for c in claims if pat.search(c.text or "")]
        if not matched_claims:
            continue
        cl_clear = max_clearance(effective_claim_clearance(db, c) for c in matched_claims)
        owner = next((c.owner_name for c in matched_claims if c.owner_name), None)
        item = CustodyItem(
            project_id=project_id,
            kind=svc_kind,
            name=svc_name,
            owner_person=redact_secrets(owner) if owner else None,
            status="unconfirmed",
            where_to_request_access=redact_secrets(f"Suggested from project records mentioning {svc_name}. Confirm who holds admin access."),
            evidence_claim_ids_json=json.dumps([c.id for c in matched_claims[:5]]),
            clearance_level=cl_clear,
            suggested=True,
        )
        db.add(item)
        db.flush()
        db.add(
            CustodyEvent(
                custody_item_id=item.id,
                action="suggested",
                detail_json=json.dumps({"claim_ids": [c.id for c in matched_claims[:5]]}),
            )
        )
        existing_names.add(svc_name.lower())
        created += 1
    return created


# ── Clearance-Filtered Graph Queries & Risks ─────────────────────────────────

def _edge_visible(edge: GraphEdge, viewer: ViewerContext) -> bool:
    if viewer.profile == "team_lead":
        return True
    if edge.clearance_level == "restricted":
        return False
    if viewer.profile == "incoming":
        return edge.review_status in APPROVED_CLAIM_STATUSES
    return True


def _node_visible(node: GraphNode, viewer: ViewerContext) -> bool:
    if viewer.profile == "team_lead":
        return True
    if node.clearance_level == "restricted":
        return False
    if viewer.profile == "incoming":
        return node.review_status in APPROVED_CLAIM_STATUSES
    return True


def get_filtered_graph(
    db: Session,
    project_id: str,
    viewer: ViewerContext,
    node_type: Optional[str] = None,
) -> Dict[str, Any]:
    all_nodes = db.query(GraphNode).filter(GraphNode.project_id == project_id).all()
    all_edges = db.query(GraphEdge).filter(GraphEdge.project_id == project_id).all()

    vis_nodes = {n.id: n for n in all_nodes if _node_visible(n, viewer)}
    vis_edges = [
        e for e in all_edges
        if _edge_visible(e, viewer) and e.source_node_id in vis_nodes and e.target_node_id in vis_nodes
    ]
    if node_type:
        keep_ids = {n.id for n in vis_nodes.values() if n.node_type == node_type}
        vis_edges = [e for e in vis_edges if e.source_node_id in keep_ids or e.target_node_id in keep_ids]
        connected = {e.source_node_id for e in vis_edges} | {e.target_node_id for e in vis_edges} | keep_ids
        node_list = [n for n in vis_nodes.values() if n.id in connected]
    else:
        node_list = list(vis_nodes.values())

    return {
        "project_id": project_id,
        "nodes": [
            {
                "id": n.id,
                "node_key": n.node_key,
                "node_type": n.node_type,
                "label": n.label,
                "clearance_level": n.clearance_level,
                "review_status": n.review_status,
                "metadata": _json_obj(n.metadata_json),
            }
            for n in sorted(node_list, key=lambda x: (x.node_type, x.label.lower()))
        ],
        "edges": [
            {
                "id": e.id,
                "source_node_id": e.source_node_id,
                "target_node_id": e.target_node_id,
                "source_label": vis_nodes[e.source_node_id].label,
                "target_label": vis_nodes[e.target_node_id].label,
                "edge_type": e.edge_type,
                "inferred": bool(e.inferred),
                "claim_ids": _json_list(e.claim_ids_json),
                "evidence_refs": _json_list(e.evidence_refs_json),
                "clearance_level": e.clearance_level,
                "review_status": e.review_status,
            }
            for e in vis_edges
        ],
    }


def _find_cycles(edges: Sequence[Dict[str, Any]], node_labels: Dict[str, str]) -> List[List[str]]:
    adj: Dict[str, List[str]] = defaultdict(list)
    for e in edges:
        if e["edge_type"] in ("depends_on", "blocks"):
            adj[e["source_node_id"]].append(e["target_node_id"])

    state: Dict[str, int] = {}  # 0=unvisited, 1=visiting, 2=done
    stack: List[str] = []
    cycles: List[List[str]] = []
    seen_sigs: Set[Tuple[str, ...]] = set()

    def dfs(u: str) -> None:
        state[u] = 1
        stack.append(u)
        for v in adj.get(u, []):
            if state.get(v, 0) == 0:
                dfs(v)
            elif state.get(v) == 1:
                idx = stack.index(v)
                cyc = [node_labels.get(x, x) for x in stack[idx:]] + [node_labels.get(v, v)]
                sig = tuple(sorted(stack[idx:]))
                if sig not in seen_sigs:
                    seen_sigs.add(sig)
                    cycles.append(cyc)
        stack.pop()
        state[u] = 2

    for nid in list(adj.keys()):
        if state.get(nid, 0) == 0:
            dfs(nid)
    return cycles


def analyze_graph_risks(db: Session, project_id: str, viewer: ViewerContext) -> Dict[str, Any]:
    g = get_filtered_graph(db, project_id, viewer)
    nodes_by_id = {n["id"]: n for n in g["nodes"]}
    labels = {n["id"]: n["label"] for n in g["nodes"]}
    modules = [n for n in g["nodes"] if n["node_type"] == "module"]

    owners_by_mod: Dict[str, Set[str]] = defaultdict(set)
    docs_by_mod: Dict[str, int] = defaultdict(int)
    for e in g["edges"]:
        src = nodes_by_id.get(e["source_node_id"])
        dst = nodes_by_id.get(e["target_node_id"])
        if not src or not dst:
            continue
        if dst["node_type"] == "module" and src["node_type"] == "person" and e["edge_type"] in ("owns", "contributed_to", "decided"):
            owners_by_mod[dst["id"]].add(src["label"])
        if dst["node_type"] == "module" and e["edge_type"] == "documents":
            docs_by_mod[dst["id"]] += 1

    spof = []
    orphaned = []
    undocumented = []
    for m in modules:
        owners = sorted(owners_by_mod.get(m["id"], set()))
        if len(owners) == 1:
            spof.append({"module_id": m["id"], "module": m["label"], "sole_owner": owners[0]})
        elif len(owners) == 0:
            orphaned.append({"module_id": m["id"], "module": m["label"]})
        if docs_by_mod.get(m["id"], 0) == 0:
            undocumented.append({"module_id": m["id"], "module": m["label"]})

    cycles = _find_cycles(g["edges"], labels)
    return {
        "project_id": project_id,
        "single_points_of_failure": spof,
        "unowned_modules": orphaned,
        "undocumented_modules": undocumented,
        "circular_dependencies": cycles,
    }


def what_if_leaves(db: Session, project_id: str, person_query: str, viewer: ViewerContext) -> Dict[str, Any]:
    g = get_filtered_graph(db, project_id, viewer)
    nodes_by_id = {n["id"]: n for n in g["nodes"]}
    people = [n for n in g["nodes"] if n["node_type"] == "person"]

    q_low = (person_query or "").strip().lower()
    target = next(
        (p for p in people if p["id"] == person_query or p["node_key"] == person_query or p["label"].lower() == q_low),
        None,
    )
    if target is None and q_low:
        target = next((p for p in people if q_low in p["label"].lower()), None)
    if target is None:
        return {"person": None, "people": [{"id": p["id"], "label": p["label"]} for p in people], "impacted": []}

    # Build reverse dependency adjacency: prereq_id -> set of dependent node ids
    rev_dep: Dict[str, Set[str]] = defaultdict(set)
    for e in g["edges"]:
        if e["edge_type"] in ("depends_on", "blocks"):
            rev_dep[e["target_node_id"]].add(e["source_node_id"])

    def _downstream_count(start_id: str) -> int:
        visited: Set[str] = set()
        dq = deque(rev_dep.get(start_id, ()))
        while dq:
            cur = dq.popleft()
            if cur in visited or cur == start_id:
                continue
            visited.add(cur)
            for nxt in rev_dep.get(cur, ()):
                if nxt not in visited:
                    dq.append(nxt)
        return len(visited)

    impacted: List[Dict[str, Any]] = []
    seen_targets: Set[str] = set()
    for e in g["edges"]:
        if e["source_node_id"] == target["id"] and e["edge_type"] in ("owns", "contributed_to", "decided"):
            tid = e["target_node_id"]
            if tid in seen_targets:
                continue
            seen_targets.add(tid)
            tn = nodes_by_id[tid]
            ds = _downstream_count(tid)
            impacted.append({
                "node_id": tid,
                "node_type": tn["node_type"],
                "label": tn["label"],
                "relationship": e["edge_type"],
                "downstream_dependents": ds,
                "claim_ids": e["claim_ids"],
            })

    impacted.sort(key=lambda x: (-x["downstream_dependents"], x["label"].lower()))
    return {
        "person": {"id": target["id"], "label": target["label"]},
        "people": [{"id": p["id"], "label": p["label"]} for p in people],
        "impacted": impacted,
    }


# ── Custody Checklist CRUD + Audit ───────────────────────────────────────────

def serialize_custody(db: Session, item: CustodyItem) -> Dict[str, Any]:
    conf_user = db.get(User, item.confirmed_by) if item.confirmed_by else None
    return {
        "id": item.id,
        "project_id": item.project_id,
        "kind": item.kind,
        "name": item.name,
        "owner_person": item.owner_person,
        "backup_owner": item.backup_owner,
        "status": item.status,
        "where_to_request_access": item.where_to_request_access,
        "notes": item.notes,
        "evidence_claim_ids": _json_list(item.evidence_claim_ids_json),
        "clearance_level": item.clearance_level,
        "suggested": bool(item.suggested),
        "confirmed_by": item.confirmed_by,
        "confirmed_by_name": conf_user.name if conf_user else None,
        "confirmed_at": item.confirmed_at.isoformat() if item.confirmed_at else None,
        "created_at": item.created_at.isoformat() if item.created_at else None,
        "updated_at": item.updated_at.isoformat() if item.updated_at else None,
    }


def list_custody_for_viewer(db: Session, project_id: str, viewer: ViewerContext) -> List[Dict[str, Any]]:
    rows = db.query(CustodyItem).filter(CustodyItem.project_id == project_id).order_by(CustodyItem.name.asc()).all()
    out: List[Dict[str, Any]] = []
    for r in rows:
        if viewer.profile != "team_lead" and r.clearance_level == "restricted":
            continue
        if viewer.profile == "incoming" and r.status not in ("confirmed", "transferred"):
            continue
        out.append(serialize_custody(db, r))
    return out


def create_custody_item(
    db: Session,
    project_id: str,
    actor: User,
    data: Dict[str, Any],
) -> CustodyItem:
    kind = (data.get("kind") or "other").strip()
    if kind not in VALID_CUSTODY_KINDS:
        raise ValueError(f"Invalid custody kind '{kind}'.")
    status = (data.get("status") or "unconfirmed").strip()
    if status not in VALID_CUSTODY_STATUSES:
        raise ValueError(f"Invalid custody status '{status}'.")
    clearance = (data.get("clearance_level") or "team").strip()
    if clearance not in ("public", "team", "restricted"):
        raise ValueError("Invalid clearance_level.")

    name = (data.get("name") or "").strip()
    if not name:
        raise ValueError("Name is required.")

    validate_no_secrets({
        "name": name,
        "owner_person": data.get("owner_person"),
        "backup_owner": data.get("backup_owner"),
        "where_to_request_access": data.get("where_to_request_access"),
        "notes": data.get("notes"),
    })

    now = _utcnow()
    item = CustodyItem(
        project_id=project_id,
        kind=kind,
        name=name[:255],
        owner_person=(data.get("owner_person") or "").strip() or None,
        backup_owner=(data.get("backup_owner") or "").strip() or None,
        status=status,
        where_to_request_access=(data.get("where_to_request_access") or "").strip() or None,
        notes=(data.get("notes") or "").strip() or None,
        evidence_claim_ids_json=json.dumps(data.get("evidence_claim_ids") or []),
        clearance_level=clearance,
        suggested=False,
        confirmed_by=actor.id if status in ("confirmed", "transferred") else None,
        confirmed_at=now if status in ("confirmed", "transferred") else None,
        updated_at=now,
    )
    db.add(item)
    db.flush()
    db.add(CustodyEvent(custody_item_id=item.id, actor_id=actor.id, action="created", detail_json=json.dumps({"status": status})))
    db.commit()
    db.refresh(item)
    return item


def update_custody_item(
    db: Session,
    item: CustodyItem,
    actor: User,
    data: Dict[str, Any],
) -> CustodyItem:
    validate_no_secrets({
        "name": data.get("name"),
        "owner_person": data.get("owner_person"),
        "backup_owner": data.get("backup_owner"),
        "where_to_request_access": data.get("where_to_request_access"),
        "notes": data.get("notes"),
    })
    changed: Dict[str, Any] = {}
    if "kind" in data and data["kind"] is not None:
        if data["kind"] not in VALID_CUSTODY_KINDS:
            raise ValueError("Invalid custody kind.")
        item.kind = data["kind"]
        changed["kind"] = data["kind"]
    for field in ("name", "owner_person", "backup_owner", "where_to_request_access", "notes"):
        if field in data and data[field] is not None:
            val = str(data[field]).strip()
            if field == "name" and not val:
                raise ValueError("Name cannot be blank.")
            setattr(item, field, val or None)
            changed[field] = val
    if "status" in data and data["status"] is not None:
        if data["status"] not in VALID_CUSTODY_STATUSES:
            raise ValueError("Invalid custody status.")
        item.status = data["status"]
        changed["status"] = data["status"]
    item.updated_at = _utcnow()
    db.add(CustodyEvent(custody_item_id=item.id, actor_id=actor.id, action="updated", detail_json=json.dumps(changed)))
    db.commit()
    db.refresh(item)
    return item


def confirm_custody_item(
    db: Session,
    item: CustodyItem,
    actor: User,
    *,
    target_status: str = "confirmed",
    note: Optional[str] = None,
) -> CustodyItem:
    if target_status not in ("confirmed", "transferred"):
        raise ValueError("Confirmation status must be 'confirmed' or 'transferred'.")
    if note:
        validate_no_secrets({"note": note})
    now = _utcnow()
    item.status = target_status
    item.confirmed_by = actor.id
    item.confirmed_at = now
    item.updated_at = now
    db.add(
        CustodyEvent(
            custody_item_id=item.id,
            actor_id=actor.id,
            action=target_status,
            detail_json=json.dumps({"note": note} if note else {}),
        )
    )
    db.commit()
    db.refresh(item)
    return item
