#!/usr/bin/env python3
"""Fetch the phenotype and mechanism layer for an expanded lysosomal panel.

This is the network step for the "names hide mechanisms" demonstration. It
expands the GM1/GM2 seed into a bounded panel of ~20 diseases, then retrieves:

1. MONDO identities, labels, synonyms and is_a parents from a LOCAL Mondo
   release (this repo's or ../data/raw); downloaded only with --download-mondo.
2. HPO disease-phenotype annotations (phenotype.hpoa), HPO gene-disease links
   (genes_to_disease.txt) and the HPO ontology (hp.obo) from one pinned
   GitHub release of the Human Phenotype Ontology.
3. Reviewed human UniProt accessions for every panel gene.
4. Reactome lowest-level pathways for each accession (ContentService API).

Nothing here computes similarity or writes graph files. Run
``compute_disease_similarity.py`` and ``sync_cluster_to_graph.py`` afterwards.
Standard library only.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SCRIPT_VERSION = "0.1.0"
USER_AGENT = "RarePathHackathon/0.1 (cluster expansion pipeline)"

HPO_RELEASE_API = "https://api.github.com/repos/obophenotype/human-phenotype-ontology/releases/latest"
HPO_ASSETS = ["phenotype.hpoa", "genes_to_disease.txt", "hp.obo"]
MONDO_RELEASE_API = "https://api.github.com/repos/monarch-initiative/mondo/releases/latest"
UNIPROT_SEARCH_URL = "https://rest.uniprot.org/uniprotkb/search"
REACTOME_BASE = "https://reactome.org/ContentService"

# The bounded panel: three disease families, each chosen to show one way that disease
# names hide (or fake) shared mechanisms. Each row is resolved through OMIM -> MONDO exact
# match and its label is checked against HPO's disease_name with ``name_check`` ("a|b" =
# either word). A row that fails either check is reported and excluded; it is never guessed.
#
# ``genes`` (optional) records the causal gene named by the OMIM entry. It is used when
# HPO's gene list for the disease is broader than the OMIM entry (for example Noonan
# syndrome 1, where NCBI mim2gene also lists BRAF and MAP2K1). "-" means no single causal
# gene (a chromosomal-region disorder). Every HPO gene link is still written to
# cluster_disease_genes.csv, with ``used_for_scoring`` showing which ones count.
def _lyso(omim: str, check: str, role: str, why: str, genes: str = "") -> dict[str, str]:
    return {"omim": omim, "name_check": check, "role": role, "why": why, "family": "lysosomal storage", "genes": genes}


def _ras(omim: str, check: str, role: str, why: str, genes: str = "") -> dict[str, str]:
    return {"omim": omim, "name_check": check, "role": role, "why": why, "family": "RASopathies", "genes": genes}


def _cilia(omim: str, check: str, role: str, why: str, genes: str = "") -> dict[str, str]:
    return {"omim": omim, "name_check": check, "role": role, "why": why, "family": "ciliopathies", "genes": genes}


PANEL: list[dict[str, str]] = [
    # --- Lysosomal storage: the original GM1/GM2 story -----------------------------------
    _lyso("230500", "gm1", "start", "GM1 gangliosidosis type 1 (infantile)"),
    _lyso("230600", "gm1", "start", "GM1 gangliosidosis type 2 (late-infantile/juvenile)"),
    _lyso("230650", "gm1", "start", "GM1 gangliosidosis type 3 (adult)"),
    _lyso("253010", "mucopolysaccharidosis|morquio", "same_gene_contrast",
          "Same gene as GM1 (GLB1) but a skeletal mucopolysaccharidosis presentation"),
    _lyso("253000", "mucopolysaccharidosis|morquio", "mechanism_neighbor",
          "Morquio A (GALNS): different gene, same keratan-sulfate degradation route as Morquio B"),
    _lyso("256540", "galactosialidosis", "mechanism_neighbor",
          "CTSA protects GLB1 and NEU1 in a lysosomal complex; secondary GLB1 deficiency"),
    _lyso("256550", "sialidosis|neuraminidase", "mechanism_neighbor",
          "NEU1 deficiency; NEU1 belongs to the same lysosomal multienzyme complex"),
    _lyso("272800", "tay-sachs", "positive_neighbor", "GM2 gangliosidosis (HEXA)"),
    _lyso("268800", "sandhoff", "positive_neighbor", "GM2 gangliosidosis (HEXB)"),
    _lyso("272750", "gm2", "positive_neighbor", "GM2 activator deficiency, AB variant (GM2A)"),
    _lyso("230800", "gaucher", "lysosomal_context", "Gaucher type I (GBA1)"),
    _lyso("230900", "gaucher", "resource_counterexample",
          "Gaucher type II: shares a natural-history study with GM1/GM2, but a different enzyme"),
    _lyso("231000", "gaucher", "lysosomal_context", "Gaucher type III (GBA1)"),
    _lyso("257200", "niemann", "lysosomal_context", "Niemann-Pick type A (SMPD1)"),
    _lyso("257220", "niemann", "lysosomal_context", "Niemann-Pick type C1 (NPC1)"),
    _lyso("245200", "krabbe", "lysosomal_context", "Krabbe disease (GALC)"),
    _lyso("250100", "leukodystrophy|metachromatic", "lysosomal_context", "Metachromatic leukodystrophy (ARSA)"),
    _lyso("301500", "fabry", "lysosomal_context", "Fabry disease (GLA)"),
    _lyso("228000", "farber|lipogranulomatosis", "lysosomal_context", "Farber lipogranulomatosis (ASAH1)"),
    _lyso("271900", "canavan", "phenocopy_counterexample",
          "Canavan disease (ASPA): an infantile white-matter disease that is not lysosomal; look-alike for Krabbe"),
    # --- RASopathies: many genes, one signalling pathway ---------------------------------
    _ras("163950", "noonan", "start", "Noonan syndrome 1 (PTPN11), the most common RASopathy", genes="PTPN11"),
    _ras("609942", "noonan", "mechanism_neighbor", "Noonan syndrome 3 (KRAS)"),
    _ras("610733", "noonan", "mechanism_neighbor", "Noonan syndrome 4 (SOS1)"),
    _ras("611553", "noonan", "mechanism_neighbor", "Noonan syndrome 5 (RAF1)"),
    _ras("613706", "noonan", "mechanism_neighbor", "Noonan syndrome 7 (BRAF)"),
    _ras("151100", "leopard", "same_gene_contrast",
         "Noonan syndrome with multiple lentigines (LEOPARD 1): same gene as Noonan 1 (PTPN11), different variants",
         genes="PTPN11"),
    _ras("218040", "costello", "mechanism_neighbor", "Costello syndrome (HRAS)"),
    _ras("615279", "cardiofaciocutaneous", "mechanism_neighbor", "Cardiofaciocutaneous syndrome 3 (MAP2K1)", genes="MAP2K1"),
    _ras("162200", "neurofibromatosis", "mechanism_neighbor", "Neurofibromatosis type 1 (NF1), a RAS regulator"),
    _ras("611431", "legius", "mechanism_neighbor",
         "Legius syndrome (SPRED1): cafe-au-lait spots like NF1, different gene, same pathway"),
    _ras("305400", "aarskog", "phenocopy_counterexample",
         "Aarskog-Scott syndrome (FGD1): short stature and facial features overlap with Noonan, but a different pathway"),
    # --- Ciliopathies: one cell structure, many genes, one gene many syndromes -------------
    _cilia("209900", "bardet", "start", "Bardet-Biedl syndrome 1 (BBS1, part of the BBSome)", genes="BBS1"),
    _cilia("615981", "bardet", "mechanism_neighbor", "Bardet-Biedl syndrome 2 (BBS2, BBSome)"),
    _cilia("615987", "bardet", "mechanism_neighbor", "Bardet-Biedl syndrome 10 (BBS10, chaperonin)"),
    _cilia("213300", "joubert", "mechanism_neighbor", "Joubert syndrome 1 (INPP5E)"),
    _cilia("608091", "joubert", "mechanism_neighbor", "Joubert syndrome 2 (TMEM216)"),
    _cilia("610188", "joubert", "same_gene_contrast", "Joubert syndrome 5 (CEP290)"),
    _cilia("611134", "meckel", "same_gene_contrast", "Meckel syndrome 4 (CEP290): same gene as Joubert 5, lethal presentation"),
    _cilia("610189", "senior-loken|senior loken", "same_gene_contrast", "Senior-Loken syndrome 6 (CEP290): kidney and retina"),
    _cilia("249000", "meckel", "mechanism_neighbor", "Meckel syndrome 1 (MKS1)"),
    _cilia("256100", "nephronophthisis", "mechanism_neighbor", "Nephronophthisis 1 (NPHP1)"),
    _cilia("203800", "alstrom|alström", "mechanism_neighbor", "Alstrom syndrome (ALMS1): obesity and retinal dystrophy like BBS"),
    _cilia("176270", "prader", "phenocopy_counterexample",
           "Prader-Willi syndrome: obesity, low muscle tone and learning disability like BBS, but an imprinting disorder of a chromosome region",
           genes="-"),
]


class FetchError(RuntimeError):
    pass


# Named disease series whose numbered types are filed under one MONDO class. Sharing one of these
# parents counts as a curated mechanism grouping (see compute_disease_similarity.MONDO_GROUP_WEIGHT).
# Deliberately NOT included: family-level classes (RASopathy, ciliopathy, lysosomal storage disease),
# which would link every disease in a family, and "Niemann-Pick disease", which MONDO groups by
# historical name although types A (SMPD1) and C (NPC1) work through different processes.
GROUP_ANCHORS = {
    "MONDO:0018997": "Noonan syndrome",
    "MONDO:0015229": "Bardet-Biedl syndrome",
    "MONDO:0018772": "Joubert syndrome",
    "MONDO:0018921": "Meckel syndrome",
    "MONDO:0019005": "nephronophthisis",
    "MONDO:0017842": "Senior-Loken syndrome",
}
# Mechanism classes: a family-level MONDO class defined by a shared mechanism. Membership is a weak
# mechanism signal (compute_disease_similarity.MONDO_CLASS_WEIGHT): it stops two members from being
# called look-alikes, but it never makes them neighbours on its own.
CLASS_ANCHORS = {
    "MONDO:0002561": "lysosomal storage disease",
    "MONDO:0021060": "RASopathy",
    "MONDO:0005308": "ciliopathy",
}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(now: datetime) -> str:
    return now.isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def request_bytes(url: str, accept: str = "application/json, */*", retries: int = 3) -> tuple[bytes, dict[str, str]]:
    last: Exception | None = None
    for attempt in range(retries):
        try:
            with urlopen(Request(url, headers={"User-Agent": USER_AGENT, "Accept": accept}), timeout=120) as response:
                return response.read(), dict(response.headers.items())
        except HTTPError as error:
            if error.code == 404:
                raise FetchError(f"404 for {url}") from error
            last = error
        except (URLError, TimeoutError) as error:
            last = error
        if attempt < retries - 1:
            time.sleep(2**attempt)
    raise FetchError(f"Could not download {url}: {last}")


def request_json(url: str) -> Any:
    body, _ = request_bytes(url)
    return json.loads(body.decode("utf-8"))


def write_csv(path: Path, rows: list[dict[str, Any]], fields: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


# --------------------------------------------------------------------------- HPO


def write_atomic(path: Path, body: bytes) -> None:
    """Write via a temporary file so an interrupted run never leaves a truncated file behind."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".part")
    tmp.write_bytes(body)
    tmp.replace(path)


def local_hpo(raw_roots: list[Path]) -> tuple[str, dict[str, Path]] | None:
    """Newest local HPO release directory that holds all required assets."""
    found = []
    for root in raw_roots:
        for directory in (root / "hpo").glob("*"):
            if directory.is_dir() and all((directory / name).is_file() and (directory / name).stat().st_size > 0
                                          for name in HPO_ASSETS):
                found.append((directory.name, directory))
    if not found:
        return None
    tag, directory = sorted(found)[-1]
    return tag, {name: directory / name for name in HPO_ASSETS}


def hpo_release(raw_roots: list[Path], refresh: bool = False) -> tuple[str, dict[str, Path], dict[str, str]]:
    """Reuse local HPO files when present; contact GitHub only if they are missing or --refresh-hpo is set."""
    local = None if refresh else local_hpo(raw_roots)
    if local:
        tag, paths = local
        urls = {name: f"https://github.com/obophenotype/human-phenotype-ontology/releases/download/{tag}/{name}"
                for name in HPO_ASSETS}
        print(f"Using local HPO {tag}: {paths['phenotype.hpoa'].parent}", flush=True)
        return tag, paths, urls

    release = request_json(HPO_RELEASE_API)
    tag = str(release.get("tag_name") or "")
    if not tag:
        raise FetchError("HPO latest release has no tag_name")
    assets = {a.get("name"): a.get("browser_download_url") for a in release.get("assets", [])}
    out_dir = raw_roots[0] / "hpo" / tag
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "release.json").write_text(json.dumps(release, indent=2), encoding="utf-8")
    paths: dict[str, Path] = {}
    urls: dict[str, str] = {}
    for name in HPO_ASSETS:
        url = assets.get(name) or (
            f"https://github.com/obophenotype/human-phenotype-ontology/releases/download/{tag}/{name}"
        )
        path = out_dir / name
        if not path.exists():
            print(f"Downloading HPO {tag} {name} ...", flush=True)
            body, _ = request_bytes(url, accept="*/*")
            write_atomic(path, body)
        paths[name] = path
        urls[name] = url
    return tag, paths, urls


def parse_obo(path: Path) -> dict[str, dict[str, Any]]:
    """Minimal OBO parser: id, name, is_a parents, alt_ids, obsolete flag."""
    terms: dict[str, dict[str, Any]] = {}
    current: dict[str, Any] | None = None
    in_term = False
    with path.open("r", encoding="utf-8") as stream:
        for raw in stream:
            line = raw.strip()
            if line.startswith("["):
                if in_term and current and current.get("id"):
                    terms[current["id"]] = current
                in_term = line == "[Term]"
                current = {"id": "", "name": "", "parents": [], "alt_ids": [], "obsolete": False} if in_term else None
                continue
            if not in_term or current is None or ":" not in line:
                continue
            key, _, value = line.partition(":")
            value = value.strip()
            if key == "id":
                current["id"] = value
            elif key == "name":
                current["name"] = value
            elif key == "is_a":
                current["parents"].append(value.split("!")[0].strip().split(" ")[0])
            elif key == "alt_id":
                current["alt_ids"].append(value)
            elif key == "is_obsolete" and value == "true":
                current["obsolete"] = True
    if in_term and current and current.get("id"):
        terms[current["id"]] = current
    return terms


def read_hpo_table(path: Path) -> list[dict[str, str]]:
    """Read an HPO TSV whose metadata lines start with '#'."""
    with path.open("r", encoding="utf-8") as stream:
        lines = [line.rstrip("\n") for line in stream if line.strip() and not line.startswith("#")]
    if not lines:
        return []
    return list(csv.DictReader(lines, delimiter="\t"))


PHENOTYPIC_ABNORMALITY = "HP:0000118"


def term_closure(term_id: str, terms: dict[str, dict[str, Any]], cache: dict[str, frozenset[str]]) -> frozenset[str]:
    """The term plus all is_a ancestors."""
    if term_id in cache:
        return cache[term_id]
    result = {term_id}
    for parent in terms.get(term_id, {}).get("parents", []):
        result |= term_closure(parent, terms, cache)
    cache[term_id] = frozenset(result)
    return cache[term_id]


def information_content(
    hpoa_rows: list[dict[str, str]],
    terms: dict[str, dict[str, Any]],
    alt: dict[str, str],
) -> tuple[dict[str, int], int]:
    """Count, for every HPO term, how many annotated diseases carry it (with propagation).

    The background corpus is every disease in this HPO release with at least one
    positive phenotypic-abnormality annotation. IC(t) = -ln(count(t) / N).
    """
    cache: dict[str, frozenset[str]] = {}
    per_disease: dict[str, set[str]] = {}
    for r in hpoa_rows:
        if r.get("aspect") != "P" or r.get("qualifier", "").upper() == "NOT":
            continue
        term_id = alt.get(r.get("hpo_id", ""), r.get("hpo_id", ""))
        if term_id not in terms or terms[term_id]["obsolete"]:
            continue
        closure = term_closure(term_id, terms, cache)
        if PHENOTYPIC_ABNORMALITY not in closure:
            continue
        per_disease.setdefault(r["database_id"], set()).update(closure)
    counts: dict[str, int] = {}
    for closure in per_disease.values():
        for term_id in closure:
            counts[term_id] = counts.get(term_id, 0) + 1
    return counts, len(per_disease)


def hpoa_metadata(path: Path) -> dict[str, str]:
    meta: dict[str, str] = {}
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.startswith("#"):
                break
            key, _, value = line[1:].partition(":")
            meta[key.strip()] = value.strip()
    return meta


# ------------------------------------------------------------------------- MONDO


def load_mondo(
    raw_roots: list[Path], explicit: Path | None = None, allow_download: bool = False
) -> tuple[dict[str, Any], str, Path]:
    """Load an existing Mondo release. Downloading (~110 MB) needs --download-mondo.

    Search order: --mondo-json, then data/raw/mondo/*/mondo.json under each raw
    root (this repo, then the sibling working copy ../data/raw). A file that is
    not valid JSON (for example an interrupted download) is reported and skipped.
    """
    candidates = [explicit] if explicit else []
    for root in raw_roots:
        candidates += sorted((root / "mondo").glob("*/mondo.json"), reverse=True)
    for path in candidates:
        if not path or not path.is_file():
            continue
        try:
            mondo = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            print(f"Skipping unreadable Mondo file (truncated download?): {path}", file=sys.stderr)
            continue
        print(f"Using local Mondo {path.parent.name}: {path}", flush=True)
        return mondo, path.parent.name, path
    if not allow_download:
        raise FetchError(
            "No usable local mondo.json found in "
            + ", ".join(str(r / "mondo") for r in raw_roots)
            + ". Pass --mondo-json PATH, or --download-mondo to fetch the latest release (~110 MB)."
        )
    from pipelines.fetch_seed_data import find_mondo_asset  # reuse the seed release logic

    release = request_json(MONDO_RELEASE_API)
    tag = str(release.get("tag_name", "unknown-release"))
    path = raw_roots[0] / "mondo" / tag / "mondo.json"
    print(f"Downloading Mondo {tag} (~110 MB) ...", flush=True)
    body, _ = request_bytes(find_mondo_asset(release), accept="*/*")
    write_atomic(path, body)
    return json.loads(body.decode("utf-8")), tag, path


def curie(value: str) -> str:
    for marker in ("http://purl.obolibrary.org/obo/", "https://purl.obolibrary.org/obo/"):
        if value.startswith(marker):
            return value.removeprefix(marker).replace("_", ":", 1)
    return value


def omim_from_match(value: str) -> str | None:
    lowered = value.lower()
    for marker in ("identifiers.org/omim/", "omim.org/entry/", "omim:"):
        if marker in lowered:
            number = lowered.split(marker, 1)[1].strip("/ ")
            if number.isdigit():
                return number
    return None


def index_mondo(mondo: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, list[str]], dict[str, list[str]]]:
    """Return nodes by CURIE, OMIM -> [MONDO] (exact matches first), and is_a parents."""
    nodes: dict[str, dict[str, Any]] = {}
    omim_exact: dict[str, list[str]] = {}
    omim_xref: dict[str, list[str]] = {}
    parents: dict[str, list[str]] = {}
    for graph in mondo.get("graphs", []):
        for node in graph.get("nodes", []):
            node_id = curie(str(node.get("id", "")))
            if not node_id.startswith("MONDO:"):
                continue
            meta = node.get("meta", {}) or {}
            if meta.get("deprecated"):
                continue
            nodes[node_id] = node
            for prop in meta.get("basicPropertyValues", []) or []:
                if str(prop.get("pred", "")).endswith("exactMatch"):
                    number = omim_from_match(str(prop.get("val", "")))
                    if number:
                        omim_exact.setdefault(number, []).append(node_id)
            for xref in meta.get("xrefs", []) or []:
                number = omim_from_match(str(xref.get("val", "")) if isinstance(xref, dict) else str(xref))
                if number:
                    omim_xref.setdefault(number, []).append(node_id)
        for edge in graph.get("edges", []):
            if edge.get("pred") == "is_a":
                child, parent = curie(str(edge.get("sub", ""))), curie(str(edge.get("obj", "")))
                if child.startswith("MONDO:") and parent.startswith("MONDO:"):
                    parents.setdefault(child, []).append(parent)
    mapping = {k: sorted(set(v)) for k, v in omim_exact.items()}
    for number, ids in omim_xref.items():
        mapping.setdefault(number, sorted(set(ids)))
    return nodes, mapping, parents


def mondo_values(node: dict[str, Any], key: str) -> list[str]:
    values = []
    for item in (node.get("meta", {}) or {}).get(key, []) or []:
        values.append(str(item.get("val")) if isinstance(item, dict) else str(item))
    return sorted({v for v in values if v and v != "None"})


def ancestors(node_id: str, parents: dict[str, list[str]]) -> set[str]:
    seen: set[str] = set()
    stack = list(parents.get(node_id, []))
    while stack:
        current = stack.pop()
        if current not in seen:
            seen.add(current)
            stack.extend(parents.get(current, []))
    return seen


# ---------------------------------------------------------- UniProt and Reactome


def cached_bytes(cache: Path | None, url: str, accept: str, refresh: bool) -> tuple[bytes, dict[str, str]]:
    """Reuse a saved API response; otherwise fetch it and save it for the next run."""
    meta = cache.with_name(cache.name + ".headers.json") if cache else None
    if cache and cache.is_file() and not refresh:
        headers = json.loads(meta.read_text(encoding="utf-8")) if meta and meta.is_file() else {}
        return cache.read_bytes(), headers
    body, headers = request_bytes(url, accept=accept)
    if cache:
        write_atomic(cache, body)
        keep = {k: v for k, v in headers.items() if k.lower() in ("x-uniprot-release", "date")}
        meta.write_text(json.dumps(keep), encoding="utf-8")
    return body, headers


def uniprot_accession(symbol: str, cache_dir: Path | None = None, refresh: bool = False) -> tuple[str, str, str]:
    params = {
        "query": f"gene_exact:{symbol} AND organism_id:9606 AND reviewed:true",
        "format": "tsv",
        "fields": "accession,gene_primary,protein_name",
        "size": "10",
    }
    url = f"{UNIPROT_SEARCH_URL}?{urlencode(params)}"
    cache = cache_dir / f"{symbol}.tsv" if cache_dir else None
    body, headers = cached_bytes(cache, url, "text/tab-separated-values", refresh)
    rows = list(csv.DictReader(body.decode("utf-8").splitlines(), delimiter="\t"))
    primary = [r for r in rows if r.get("Gene Names (primary)", "").strip().upper() == symbol.upper()] or rows
    if not primary:
        raise FetchError(f"No reviewed human UniProt entry for {symbol}")
    primary.sort(key=lambda r: r.get("Entry", ""))
    release = next((v for k, v in headers.items() if k.lower() == "x-uniprot-release"), "unknown")
    return primary[0]["Entry"], primary[0].get("Protein names", ""), release


REACTOME_MAPPING_URL = "https://reactome.org/download/current/UniProt2Reactome.txt"


def reactome_pathway_sizes(cache_dir: Path, version: str, refresh: bool = False) -> tuple[dict[str, int], int, str]:
    """Human proteins per lowest-level Reactome pathway, from Reactome's own mapping file.

    The file (UniProt -> lowest-level pathway, all species) is downloaded once per
    Reactome version and cached. Returns (pathway -> number of human UniProt accessions,
    number of human accessions with any pathway, path of the cached file).
    """
    path = cache_dir / f"UniProt2Reactome_v{version or 'unknown'}.txt"
    if refresh or not path.is_file():
        print(f"Downloading Reactome UniProt-to-pathway mapping (one time, version {version}) ...", flush=True)
        body, _ = request_bytes(REACTOME_MAPPING_URL, accept="text/plain")
        write_atomic(path, body)
    members: dict[str, set[str]] = {}
    proteins: set[str] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            parts = line.rstrip("\n").split("\t")
            if len(parts) < 6 or parts[5].strip() != "Homo sapiens":
                continue
            accession = parts[0].split("-")[0]
            members.setdefault(parts[1], set()).add(accession)
            proteins.add(accession)
    return {pid: len(acc) for pid, acc in members.items()}, len(proteins), str(path)


def reactome_pathways(accession: str, cache_dir: Path | None = None, refresh: bool = False) -> list[dict[str, Any]]:
    url = f"{REACTOME_BASE}/data/mapping/UniProt/{accession}/pathways?species=9606"
    cache = cache_dir / f"{accession}.json" if cache_dir else None
    try:
        body, _ = cached_bytes(cache, url, "application/json", refresh)
    except FetchError as error:
        if "404" in str(error):
            if cache:
                write_atomic(cache, b"[]")  # remember "no mapping" too
            return []
        raise
    payload = json.loads(body.decode("utf-8"))
    return payload if isinstance(payload, list) else []


# ----------------------------------------------------------------------- main


def resolve_panel(
    nodes: dict[str, dict[str, Any]],
    omim_to_mondo: dict[str, list[str]],
    hpo_names: dict[str, str],
) -> tuple[list[dict[str, str]], list[str]]:
    resolved, problems = [], []
    for row in PANEL:
        disease_key = f"OMIM:{row['omim']}"
        hpo_name = hpo_names.get(disease_key, "")
        if not hpo_name:
            problems.append(f"{disease_key}: no HPO annotations in this release")
            continue
        if not any(word in hpo_name.lower() for word in row["name_check"].split("|")):
            problems.append(f"{disease_key}: HPO name '{hpo_name}' does not contain '{row['name_check']}'")
            continue
        mondo_ids = omim_to_mondo.get(row["omim"], [])
        if not mondo_ids:
            problems.append(f"{disease_key}: no MONDO exact match/xref")
            continue
        if len(mondo_ids) > 1:
            print(f"Note: {disease_key} maps to {mondo_ids}; using {mondo_ids[0]}", file=sys.stderr)
        node = nodes[mondo_ids[0]]
        resolved.append(
            {
                "disease_id": mondo_ids[0],
                "label": str(node.get("lbl", "")) or hpo_name,
                "hpo_disease_id": disease_key,
                "hpo_disease_name": hpo_name,
                "panel_role": row["role"],
                "panel_rationale": row["why"],
                "family": row.get("family", ""),
                "curated_genes": row.get("genes", ""),
                "synonyms": "; ".join(mondo_values(node, "synonyms")),
                "xrefs": "; ".join(mondo_values(node, "xrefs")),
            }
        )
    return resolved, problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", default=str(REPO_ROOT))
    parser.add_argument("--skip-reactome", action="store_true", help="Skip UniProt/Reactome (offline debugging).")
    parser.add_argument("--mondo-json", help="Path to an existing mondo.json (default: search data/raw/mondo).")
    parser.add_argument("--extra-raw-dir", action="append", default=[],
                        help="Another data/raw folder to search for existing Mondo/HPO files (repeatable).")
    parser.add_argument("--download-mondo", action="store_true", help="Allow downloading Mondo if no local copy exists.")
    parser.add_argument("--refresh-hpo", action="store_true", help="Ignore local HPO files and fetch the latest release.")
    parser.add_argument("--refresh-api", action="store_true", help="Ignore cached UniProt/Reactome responses.")
    args = parser.parse_args()
    root = Path(args.repo_root).resolve()
    raw_root = root / "data" / "raw"
    # This repo first, then the sibling working copy (../data/raw) where the seed pipeline was first run.
    raw_roots = [raw_root] + [Path(p).resolve() for p in args.extra_raw_dir]
    sibling = root.parent / "data" / "raw"
    if sibling.is_dir() and sibling not in raw_roots:
        raw_roots.append(sibling)
    processed = root / "data" / "processed"
    now = utc_now()
    retrieved_at = iso(now)

    hpo_tag, hpo_paths, hpo_urls = hpo_release(raw_roots, refresh=args.refresh_hpo)
    hpoa_rows = read_hpo_table(hpo_paths["phenotype.hpoa"])
    g2d_rows = read_hpo_table(hpo_paths["genes_to_disease.txt"])
    terms = parse_obo(hpo_paths["hp.obo"])
    alt = {a: t["id"] for t in terms.values() for a in t["alt_ids"]}
    hpo_names = {r["database_id"]: r["disease_name"] for r in hpoa_rows}

    mondo, mondo_tag, mondo_path = load_mondo(
        raw_roots, Path(args.mondo_json) if args.mondo_json else None, allow_download=args.download_mondo
    )
    nodes, omim_to_mondo, parents = index_mondo(mondo)
    del mondo

    panel, problems = resolve_panel(nodes, omim_to_mondo, hpo_names)
    for problem in problems:
        print(f"Excluded: {problem}", file=sys.stderr)
    if not panel:
        raise FetchError("No panel disease could be resolved")
    by_hpo_id = {row["hpo_disease_id"]: row for row in panel}

    # Panel diseases plus the seed MONDO nodes already in the graph, linked by is_a.
    seed_ids = ["MONDO:0018149", "MONDO:0017720"]
    panel_ids = {row["disease_id"] for row in panel}
    hierarchy = []
    for disease_id in sorted(panel_ids):
        for ancestor in sorted(ancestors(disease_id, parents)):
            if ancestor in seed_ids or ancestor in panel_ids or ancestor in GROUP_ANCHORS or ancestor in CLASS_ANCHORS:
                direct = ancestor in parents.get(disease_id, [])
                hierarchy.append(
                    {
                        "child_id": disease_id,
                        "parent_id": ancestor,
                        "parent_label": str(nodes.get(ancestor, {}).get("lbl", "")),
                        "relation": "is_a" if direct else "is_a_transitive",
                        "grouping": "class" if ancestor in CLASS_ANCHORS else "series",
                        "mondo_release_tag": mondo_tag,
                    }
                )

    for row in panel:
        row.update({"mondo_release_tag": mondo_tag, "hpo_release_tag": hpo_tag, "retrieved_at": retrieved_at})
    write_csv(
        processed / "cluster_diseases.csv",
        panel,
        ["disease_id", "label", "hpo_disease_id", "hpo_disease_name", "family", "panel_role", "panel_rationale",
         "curated_genes", "synonyms", "xrefs", "mondo_release_tag", "hpo_release_tag", "retrieved_at"],
    )
    write_csv(processed / "cluster_disease_hierarchy.csv", hierarchy,
              ["child_id", "parent_id", "parent_label", "relation", "grouping", "mondo_release_tag"])

    # Disease-phenotype annotations: phenotypic abnormality aspect only, NOT-qualified rows dropped.
    annotations = []
    for r in hpoa_rows:
        panel_row = by_hpo_id.get(r.get("database_id", ""))
        if not panel_row or r.get("aspect") != "P" or r.get("qualifier", "").upper() == "NOT":
            continue
        term_id = alt.get(r["hpo_id"], r["hpo_id"])
        term = terms.get(term_id)
        if not term or term["obsolete"]:
            continue
        annotations.append(
            {
                "disease_id": panel_row["disease_id"],
                "hpo_disease_id": r["database_id"],
                "hpo_id": term_id,
                "hpo_label": term["name"],
                "frequency": r.get("frequency", ""),
                "onset": r.get("onset", ""),
                "evidence": r.get("evidence", ""),
                "reference": r.get("reference", ""),
                "hpo_release_tag": hpo_tag,
            }
        )
    write_csv(processed / "cluster_disease_phenotypes.csv", annotations,
              ["disease_id", "hpo_disease_id", "hpo_id", "hpo_label", "frequency", "onset", "evidence",
               "reference", "hpo_release_tag"])

    # Term table: every ancestor of a panel annotation, with background IC, so the
    # similarity step can run offline from committed CSVs.
    counts, corpus_size = information_content(hpoa_rows, terms, alt)
    cache: dict[str, frozenset[str]] = {}
    needed: set[str] = set()
    for a in annotations:
        needed |= term_closure(a["hpo_id"], terms, cache)
    term_rows = []
    for term_id in sorted(needed):
        count = counts.get(term_id, 0)
        term_rows.append(
            {
                "hpo_id": term_id,
                "hpo_label": terms[term_id]["name"],
                "parents": "; ".join(p for p in terms[term_id]["parents"] if p in needed),
                "annotated_disease_count": count,
                "corpus_disease_count": corpus_size,
                "information_content": f"{-math.log(count / corpus_size):.6f}" if count and corpus_size else "",
                "hpo_release_tag": hpo_tag,
            }
        )
    write_csv(processed / "cluster_hpo_terms.csv", term_rows,
              ["hpo_id", "hpo_label", "parents", "annotated_disease_count", "corpus_disease_count",
               "information_content", "hpo_release_tag"])

    gene_links = []
    for r in g2d_rows:
        panel_row = by_hpo_id.get(r.get("disease_id", ""))
        if not panel_row:
            continue
        curated = panel_row.get("curated_genes", "")
        symbol = r.get("gene_symbol", "")
        used = r.get("association_type", "").upper() == "MENDELIAN" and symbol not in ("", "-")
        if curated:
            used = used and symbol in {g.strip() for g in curated.split(";") if g.strip() and g.strip() != "-"}
        gene_links.append(
            {
                "disease_id": panel_row["disease_id"],
                "hpo_disease_id": r["disease_id"],
                "gene_symbol": symbol,
                "ncbi_gene_id": r.get("ncbi_gene_id", ""),
                "association_type": r.get("association_type", ""),
                "used_for_scoring": str(used).lower(),
                "source": r.get("source", ""),
                "hpo_release_tag": hpo_tag,
            }
        )
    write_csv(processed / "cluster_disease_genes.csv", gene_links,
              ["disease_id", "hpo_disease_id", "gene_symbol", "ncbi_gene_id", "association_type", "used_for_scoring",
               "source", "hpo_release_tag"])

    gene_pathways: list[dict[str, str]] = []
    reactome_version = ""
    uniprot_release = ""
    if not args.skip_reactome:
        try:
            body, _ = cached_bytes(raw_root / "reactome" / "database_version.txt",
                                   f"{REACTOME_BASE}/data/database/version", "text/plain", args.refresh_api)
            reactome_version = body.decode("utf-8").strip()
        except FetchError:
            reactome_version = "unknown"
        symbols = sorted({g["gene_symbol"] for g in gene_links if g["used_for_scoring"] == "true"})
        for symbol in symbols:
            accession, protein_name, uniprot_release = uniprot_accession(
                symbol, raw_root / "uniprot" / "gene_search", args.refresh_api
            )
            pathways = reactome_pathways(accession, raw_root / "reactome" / "uniprot_pathways", args.refresh_api)
            print(f"{symbol} -> {accession}: {len(pathways)} Reactome pathways", flush=True)
            for p in pathways:
                gene_pathways.append(
                    {
                        "gene_symbol": symbol,
                        "uniprot_accession": accession,
                        "protein_name": protein_name,
                        "pathway_id": str(p.get("stId", "")),
                        "pathway_label": str(p.get("displayName", "")),
                        "is_in_disease": str(bool(p.get("isInDisease", False))).lower(),
                        "reactome_version": reactome_version,
                        "source_url": f"https://reactome.org/content/detail/{p.get('stId', '')}",
                    }
                )
            time.sleep(0.2)
    background = 0
    mapping_path = ""
    if gene_pathways:
        try:
            sizes, background, mapping_path = reactome_pathway_sizes(raw_root / "reactome", reactome_version,
                                                                     args.refresh_api)
        except (FetchError, OSError) as error:
            # Pathway sizes are reported alongside the evidence, not used for scoring: carry on without them.
            print(f"Warning: Reactome mapping file unavailable ({error}); pathway sizes left blank.", file=sys.stderr)
            sizes = {}
        for row in gene_pathways:
            row["pathway_size_human"] = sizes.get(row["pathway_id"], "")
            row["background_proteins"] = background or ""
    write_csv(processed / "cluster_gene_pathways.csv", gene_pathways,
              ["gene_symbol", "uniprot_accession", "protein_name", "pathway_id", "pathway_label",
               "is_in_disease", "pathway_size_human", "background_proteins", "reactome_version", "source_url"])

    manifest = {
        "pipeline": "RarePath cluster expansion fetch",
        "script_version": SCRIPT_VERSION,
        "retrieved_at": retrieved_at,
        "panel_requested": len(PANEL),
        "panel_resolved": len(panel),
        "excluded": problems,
        "sources": {
            "hpo": {
                "release_tag": hpo_tag,
                "urls": hpo_urls,
                "sha256": {name: sha256_file(path) for name, path in hpo_paths.items()},
                "hpoa_header": hpoa_metadata(hpo_paths["phenotype.hpoa"]),
            },
            "mondo": {"release_tag": mondo_tag, "sha256": sha256_file(mondo_path)},
            "uniprot": {"release": uniprot_release, "search_url": UNIPROT_SEARCH_URL},
            "reactome": {"version": reactome_version, "api": REACTOME_BASE, "mapping_file": REACTOME_MAPPING_URL,
                         "mapping_sha256": sha256_file(Path(mapping_path)) if mapping_path else "",
                         "human_proteins_with_pathways": background},
        },
        "outputs": {
            "cluster_diseases.csv": len(panel),
            "cluster_disease_hierarchy.csv": len(hierarchy),
            "cluster_disease_phenotypes.csv": len(annotations),
            "cluster_hpo_terms.csv": len(term_rows),
            "cluster_disease_genes.csv": len(gene_links),
            "cluster_gene_pathways.csv": len(gene_pathways),
        },
    }
    manifest_path = root / "data" / "manifests" / "cluster_expansion_v0.1.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["outputs"], indent=2))
    print(f"Resolved {len(panel)}/{len(PANEL)} panel diseases. Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (FetchError, OSError, ValueError) as error:
        print(f"Cluster expansion fetch failed: {error}", file=sys.stderr)
        raise SystemExit(1)
