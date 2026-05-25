from __future__ import annotations

import math
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

try:
    import networkx as nx
    NETWORKX_AVAILABLE = True
except ImportError:
    nx = None  # type: ignore[assignment]
    NETWORKX_AVAILABLE = False

import database

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

EDGE_GROUP = "group"
EDGE_SITE = "site"
EDGE_BOTH = "group+site"

# Sites where shared membership is a strong identity signal
TRUST_SITES: set[str] = {
    "github", "gitlab", "linkedin", "stackoverflow",
    "kaggle", "behance", "habr", "dribbble", "huggingface",
    "artstation", "hackerone", "hackthebox", "tryhackme",
}

# Max group size to create edges from (huge groups are noise)
MAX_GROUP_SIZE_FOR_EDGES = 120

# Username patterns typical for auto-generated / bot accounts
_BOT_PATTERNS = [
    re.compile(r"^[a-z]{2,6}\d{4,10}$"),       # name + 4-10 digits
    re.compile(r"^[a-z]+_\d{4,}$"),             # name_digits
    re.compile(r"^\d{6,15}$"),                  # all digits
    re.compile(r"^[a-z]{1,3}\d{3,}[a-z]{0,2}$"),  # short + digits + optional tail
    re.compile(r"^user\d+$"),                    # user12345
]

# Node colors for matplotlib rendering
RISK_COLORS = {
    "high": "#e74c3c",
    "medium": "#f39c12",
    "analyst": "#3498db",
    "low": "#2ecc71",
    "unknown": "#95a5a6",
}

EDGE_COLORS = {
    EDGE_GROUP: "#7f8c8d",
    EDGE_SITE: "#c0392b",
    EDGE_BOTH: "#8e44ad",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _looks_like_bot(username: str) -> bool:
    u = (username or "").lower().strip("@")
    if not u or len(u) < 3:
        return False
    return any(p.match(u) for p in _BOT_PATTERNS)


def _node_label(uid: int, username: str, first_name: str) -> str:
    if username:
        return f"@{username}"
    if first_name:
        return first_name[:12]
    return f"id{uid}"


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_link_graph(
    profiles: list[dict[str, Any]],
    group_rows: list[dict[str, Any]],
    account_rows: list[dict[str, Any]],
) -> Any:
    """Build an undirected weighted graph from profile data.

    Edges:
      - group edge (weight 1.0): two profiles share a Telegram group
      - site edge (weight 2.0): two profiles both found on a trusted platform

    Returns None when networkx is not installed.
    """
    if not NETWORKX_AVAILABLE:
        return None

    G = nx.Graph()

    # --- Nodes ---
    profile_map: dict[int, dict] = {}
    for p in profiles:
        uid = int(p["user_id"])
        profile_map[uid] = p
        G.add_node(
            uid,
            username=p.get("username") or "",
            first_name=p.get("first_name") or "",
            label=_node_label(uid, p.get("username") or "", p.get("first_name") or ""),
            is_bot=_looks_like_bot(p.get("username") or ""),
            osint_score=int(p.get("osint_score") or 0),
        )

    # --- Group membership index ---
    group_members: dict[str, set[int]] = defaultdict(set)
    for row in group_rows:
        uid = int(row["user_id"])
        if uid in profile_map:
            group_members[row["group_name"]].add(uid)

    # --- Group edges ---
    for group_name, members in group_members.items():
        member_list = sorted(members)
        if len(member_list) > MAX_GROUP_SIZE_FOR_EDGES:
            continue
        for i in range(len(member_list)):
            for j in range(i + 1, len(member_list)):
                u, v = member_list[i], member_list[j]
                if G.has_edge(u, v):
                    d = G[u][v]
                    d["groups"].append(group_name)
                    d["weight"] += 1.0
                else:
                    G.add_edge(u, v,
                               groups=[group_name],
                               sites=[],
                               weight=1.0,
                               edge_type=EDGE_GROUP)

    # --- Site membership index (trust sites only) ---
    site_members: dict[str, set[int]] = defaultdict(set)
    for row in account_rows:
        uid = int(row["user_id"])
        site = (row.get("site_name") or "").strip().lower()
        if uid in profile_map and site in TRUST_SITES:
            site_members[site].add(uid)

    # --- Site edges ---
    for site, members in site_members.items():
        if len(members) < 2:
            continue
        member_list = sorted(members)
        for i in range(len(member_list)):
            for j in range(i + 1, len(member_list)):
                u, v = member_list[i], member_list[j]
                if G.has_edge(u, v):
                    d = G[u][v]
                    d["sites"].append(site)
                    d["weight"] += 2.0
                    d["edge_type"] = EDGE_BOTH
                else:
                    G.add_edge(u, v,
                               groups=[],
                               sites=[site],
                               weight=2.0,
                               edge_type=EDGE_SITE)

    return G


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def compute_graph_metrics(G: Any) -> dict[str, Any]:
    """Compute centrality, connected components, bridges."""
    if G is None or not NETWORKX_AVAILABLE or G.number_of_nodes() == 0:
        return {
            "nodes": 0, "edges": 0, "components": 0,
            "largest_component": 0, "isolated_count": 0,
            "top_central": [], "clusters": [], "bridge_nodes": [],
        }

    components = sorted(nx.connected_components(G), key=len, reverse=True)

    degree_centrality = nx.degree_centrality(G)
    if G.number_of_nodes() <= 400:
        betweenness = nx.betweenness_centrality(G, normalized=True)
    else:
        betweenness = {n: 0.0 for n in G.nodes()}

    top_central = sorted(
        [(n, degree_centrality[n], betweenness.get(n, 0.0)) for n in G.nodes()],
        key=lambda x: x[1] + x[2],
        reverse=True,
    )[:10]

    bridge_nodes = [
        n for n in G.nodes()
        if betweenness.get(n, 0.0) >= 0.05 and G.degree(n) >= 2
    ]

    clusters: list[dict[str, Any]] = []
    for idx, comp in enumerate(components[:15]):
        sg = G.subgraph(comp)
        bot_count = sum(1 for n in comp if G.nodes[n].get("is_bot"))
        all_groups: set[str] = set()
        all_sites: set[str] = set()
        for _u, _v, data in sg.edges(data=True):
            all_groups.update(data.get("groups", []))
            all_sites.update(data.get("sites", []))

        size = len(comp)
        density = round(nx.density(sg), 3)
        bot_ratio = round(bot_count / max(size, 1), 2)
        suspicious = bot_ratio > 0.35 or (size > 4 and density > 0.75)

        clusters.append({
            "cluster_id": idx,
            "size": size,
            "edges": sg.number_of_edges(),
            "density": density,
            "bot_count": bot_count,
            "bot_ratio": bot_ratio,
            "groups": sorted(all_groups),
            "sites": sorted(all_sites),
            "member_ids": sorted(comp),
            "suspicious": suspicious,
        })

    return {
        "nodes": G.number_of_nodes(),
        "edges": G.number_of_edges(),
        "components": len(components),
        "largest_component": len(components[0]) if components else 0,
        "isolated_count": sum(1 for n in G.nodes() if G.degree(n) == 0),
        "top_central": [
            {
                "user_id": n,
                "label": G.nodes[n].get("label", str(n)),
                "degree_centrality": round(dc, 4),
                "betweenness": round(bc, 4),
            }
            for n, dc, bc in top_central
        ],
        "bridge_nodes": [G.nodes[n].get("label", str(n)) for n in bridge_nodes[:10]],
        "clusters": clusters,
    }


# ---------------------------------------------------------------------------
# Bot network detection
# ---------------------------------------------------------------------------

def detect_bot_networks(G: Any, metrics: dict[str, Any]) -> list[dict[str, Any]]:
    """Find clusters with suspicious automated account patterns."""
    if not NETWORKX_AVAILABLE or G is None or not metrics:
        return []

    networks: list[dict[str, Any]] = []
    for cluster in metrics.get("clusters", []):
        if cluster["bot_ratio"] < 0.30 or cluster["size"] < 3:
            continue
        sample_bots = [
            G.nodes[n].get("label", str(n))
            for n in cluster["member_ids"]
            if G.nodes[n].get("is_bot")
        ][:6]
        verdict = (
            "высокая вероятность бот-сети"
            if cluster["bot_ratio"] > 0.60
            else "подозрительный кластер — возможная координированная активность"
        )
        networks.append({
            "cluster_id": cluster["cluster_id"],
            "size": cluster["size"],
            "bot_count": cluster["bot_count"],
            "bot_ratio": cluster["bot_ratio"],
            "density": cluster["density"],
            "groups": cluster["groups"],
            "sites": cluster["sites"],
            "sample_bots": sample_bots,
            "verdict": verdict,
        })

    return sorted(networks, key=lambda x: x["bot_ratio"], reverse=True)


# ---------------------------------------------------------------------------
# Visualization
# ---------------------------------------------------------------------------

def draw_link_graph(
    G: Any,
    ax: Any,
    max_nodes: int = 80,
    profile_risks: dict[int, str] | None = None,
) -> None:
    """Render graph on a matplotlib axis."""
    if not NETWORKX_AVAILABLE or G is None:
        ax.text(0.5, 0.5, "networkx недоступен", ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return

    if G.number_of_nodes() == 0:
        ax.text(0.5, 0.5, "Граф пуст:\nнет профилей или связей между ними",
                ha="center", va="center", transform=ax.transAxes)
        ax.set_axis_off()
        return

    # Subgraph: most connected nodes
    if G.number_of_nodes() > max_nodes:
        top = sorted(G.degree(), key=lambda x: x[1], reverse=True)[:max_nodes]
        subG: Any = G.subgraph({n for n, _ in top}).copy()
    else:
        subG = G

    # Layout
    n = subG.number_of_nodes()
    k_val = 1.8 / math.sqrt(max(n, 1))
    try:
        pos = nx.spring_layout(subG, seed=42, k=k_val, iterations=60)
    except Exception:
        pos = nx.random_layout(subG, seed=42)

    # Node appearance
    node_colors = [
        RISK_COLORS.get((profile_risks or {}).get(nd, "unknown"), RISK_COLORS["unknown"])
        for nd in subG.nodes()
    ]
    node_sizes = [max(60, min(subG.degree(nd) * 50, 700)) for nd in subG.nodes()]

    # Edge appearance
    edge_color_list = [
        EDGE_COLORS.get(data.get("edge_type", EDGE_GROUP), "#aaaaaa")
        for _, _, data in subG.edges(data=True)
    ]
    edge_widths = [
        min(data.get("weight", 1.0) * 0.5, 3.0)
        for _, _, data in subG.edges(data=True)
    ]

    nx.draw_networkx_edges(subG, pos, ax=ax,
                           edge_color=edge_color_list,
                           width=edge_widths, alpha=0.45)
    nx.draw_networkx_nodes(subG, pos, ax=ax,
                           node_color=node_colors,
                           node_size=node_sizes, alpha=0.88)

    # Labels only for high-degree nodes
    deg_threshold = max(2, n // 12)
    labels = {
        nd: subG.nodes[nd].get("label", str(nd))
        for nd in subG.nodes()
        if subG.degree(nd) >= deg_threshold
    }
    if labels:
        nx.draw_networkx_labels(subG, pos, labels, ax=ax, font_size=7)

    ax.set_title(
        f"Граф связей: {subG.number_of_nodes()} профилей, {subG.number_of_edges()} связей\n"
        "Узел: ● красный=high  ● оранжевый=medium  ● синий=analyst  ● зелёный=low\n"
        "Ребро: ― серый=общая группа  ― красный=общий сайт  ― фиолетовый=оба",
        fontsize=8,
    )
    ax.set_axis_off()


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def get_link_analysis() -> dict[str, Any]:
    """Fetch data from DB and run full graph analysis."""
    database.init_db()
    with database.get_connection() as conn:
        profiles = [dict(r) for r in conn.execute(
            "SELECT user_id, first_name, username, bio FROM profiles"
        ).fetchall()]
        # Enrich with osint_score from summary view
        try:
            enriched = {
                int(r["user_id"]): dict(r)
                for r in conn.execute(
                    "SELECT p.user_id, "
                    "COALESCE(s.site_count, 0) AS site_count, "
                    "COALESCE(s.osint_score, 0) AS osint_score "
                    "FROM profiles p "
                    "LEFT JOIN ("
                    "  SELECT user_id, COUNT(*) AS site_count FROM social_accounts GROUP BY user_id"
                    ") s ON s.user_id = p.user_id"
                ).fetchall()
            }
            for p in profiles:
                uid = int(p["user_id"])
                if uid in enriched:
                    p["osint_score"] = enriched[uid]["osint_score"]
        except Exception:
            pass

        group_rows = [dict(r) for r in conn.execute(
            "SELECT user_id, group_name FROM user_groups"
        ).fetchall()]
        account_rows = [dict(r) for r in conn.execute(
            "SELECT user_id, site_name FROM social_accounts"
        ).fetchall()]

    if not profiles:
        return {
            "available": False,
            "networkx_available": NETWORKX_AVAILABLE,
            "graph": None,
            "metrics": {},
            "bot_networks": [],
        }

    G = build_link_graph(profiles, group_rows, account_rows)
    metrics = compute_graph_metrics(G)
    bot_networks = detect_bot_networks(G, metrics)

    return {
        "available": True,
        "networkx_available": NETWORKX_AVAILABLE,
        "graph": G,
        "metrics": metrics,
        "bot_networks": bot_networks,
    }
