#!/usr/bin/env python3
"""Compute reproducible pairwise protein-sequence similarity baselines.

Two local-alignment methods are intentionally kept side by side:

1. a transparent Smith-Waterman baseline with +2/-1/-2 scoring; and
2. Smith-Waterman with the BLOSUM62 substitution matrix and affine gaps.

The output is a computational research-navigation signal. It is not a disease
similarity, pathogenicity, or treatment-effectiveness prediction.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable


LINEAR_MATCH_SCORE = 2
LINEAR_MISMATCH_SCORE = -1
LINEAR_GAP_SCORE = -2
AFFINE_GAP_OPEN = 11
AFFINE_GAP_EXTEND = 1
# Karlin-Altschul statistics for gapped BLOSUM62 with gap costs 11/1, as tabulated in
# NCBI BLAST (blast_stat.c). E = K * m * n * exp(-lambda * S); bits = (lambda * S - ln K) / ln 2.
# No finite-length (edge-effect) correction is applied, so E-values are slightly conservative
# for very short alignments. They apply only to the BLOSUM62 affine method; the linear
# teaching baseline has no published parameters and keeps these fields empty.
KA_LAMBDA = 0.267
KA_K = 0.041
KA_SOURCE = "NCBI BLAST gapped BLOSUM62 parameters (gap open 11, extend 1): lambda=0.267, K=0.041"
SIGNIFICANT_EVALUE = 1e-3
NEGATIVE_INFINITY = -10**9

LINEAR_METHOD = "smith_waterman_local_linear_v0.1"
AFFINE_METHOD = "smith_waterman_local_blosum62_affine_v0.2"
BLOSUM62_SOURCE_URL = "https://ftp.ncbi.nlm.nih.gov/blast/matrices/BLOSUM62"

H_STOP = 0
H_DIAGONAL = 1
H_FROM_HORIZONTAL_GAP = 2
H_FROM_VERTICAL_GAP = 3
GAP_FROM_H = 1
GAP_FROM_GAP = 2

BLOSUM62_TEXT = """
   A  R  N  D  C  Q  E  G  H  I  L  K  M  F  P  S  T  W  Y  V  B  Z  X  *
A  4 -1 -2 -2  0 -1 -1  0 -2 -1 -1 -1 -1 -2 -1  1  0 -3 -2  0 -2 -1  0 -4
R -1  5  0 -2 -3  1  0 -2  0 -3 -2  2 -1 -3 -2 -1 -1 -3 -2 -3 -1  0 -1 -4
N -2  0  6  1 -3  0  0  0  1 -3 -3  0 -2 -3 -2  1  0 -4 -2 -3  3  0 -1 -4
D -2 -2  1  6 -3  0  2 -1 -1 -3 -4 -1 -3 -3 -1  0 -1 -4 -3 -3  4  1 -1 -4
C  0 -3 -3 -3  9 -3 -4 -3 -3 -1 -1 -3 -1 -2 -3 -1 -1 -2 -2 -1 -3 -3 -2 -4
Q -1  1  0  0 -3  5  2 -2  0 -3 -2  1  0 -3 -1  0 -1 -2 -1 -2  0  3 -1 -4
E -1  0  0  2 -4  2  5 -2  0 -3 -3  1 -2 -3 -1  0 -1 -3 -2 -2  1  4 -1 -4
G  0 -2  0 -1 -3 -2 -2  6 -2 -4 -4 -2 -3 -3 -2  0 -2 -2 -3 -3 -1 -2 -1 -4
H -2  0  1 -1 -3  0  0 -2  8 -3 -3 -1 -2 -1 -2 -1 -2 -2  2 -3  0  0 -1 -4
I -1 -3 -3 -3 -1 -3 -3 -4 -3  4  2 -3  1  0 -3 -2 -1 -3 -1  3 -3 -3 -1 -4
L -1 -2 -3 -4 -1 -2 -3 -4 -3  2  4 -2  2  0 -3 -2 -1 -2 -1  1 -4 -3 -1 -4
K -1  2  0 -1 -3  1  1 -2 -1 -3 -2  5 -1 -3 -1  0 -1 -3 -2 -2  0  1 -1 -4
M -1 -1 -2 -3 -1  0 -2 -3 -2  1  2 -1  5  0 -2 -1 -1 -1 -1  1 -3 -1 -1 -4
F -2 -3 -3 -3 -2 -3 -3 -3 -1  0  0 -3  0  6 -4 -2 -2  1  3 -1 -3 -3 -1 -4
P -1 -2 -2 -1 -3 -1 -1 -2 -2 -3 -3 -1 -2 -4  7 -1 -1 -4 -3 -2 -2 -1 -2 -4
S  1 -1  1  0 -1  0  0  0 -1 -2 -2  0 -1 -2 -1  4  1 -3 -2 -2  0  0  0 -4
T  0 -1  0 -1 -1 -1 -1 -2 -2 -1 -1 -1 -1 -2 -1  1  5 -2 -2  0 -1 -1  0 -4
W -3 -3 -4 -4 -2 -2 -3 -2 -2 -3 -2 -3 -1  1 -4 -3 -2 11  2 -3 -4 -3 -2 -4
Y -2 -2 -2 -3 -2 -1 -2 -3  2 -1 -1 -2 -1  3 -3 -2 -2  2  7 -1 -3 -2 -1 -4
V  0 -3 -3 -3 -1 -2 -2 -3 -3  3  1 -2  1 -1 -2 -2  0 -3 -1  4 -3 -2 -1 -4
B -2 -1  3  4 -3  0  1 -1  0 -3 -4  0 -3 -3 -2  0 -1 -4 -3 -3  4  1 -1 -4
Z -1  0  0  1 -3  3  4 -2  0 -3 -3  1 -1 -3 -1  0 -1 -3 -2 -2  1  4 -1 -4
X  0 -1 -1 -1 -2 -1 -1 -1 -1 -1 -1 -1 -1 -1 -2  0  0 -2 -1 -1 -1 -1 -1 -4
* -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4 -4  1
"""

CSV_FIELDS = [
    "similarity_id",
    "source_protein_id",
    "target_protein_id",
    "source_gene_symbol",
    "target_gene_symbol",
    "method",
    "substitution_matrix",
    "gap_model",
    "gap_open_penalty",
    "gap_extend_penalty",
    "alignment_score",
    "identity_pct",
    "identical_residues",
    "aligned_residues",
    "query_aligned_residues",
    "target_aligned_residues",
    "alignment_length",
    "query_coverage_pct",
    "target_coverage_pct",
    "minimum_coverage_pct",
    "gap_fraction_pct",
    "evalue",
    "bitscore",
    "embedding_model",
    "embedding_version",
    "cosine_similarity",
    "structure_source",
    "tm_score",
    "lddt",
    "assertion_level",
    "evidence_id",
    "primary_score",
    "score_name",
    "dataset_release",
    "source_url",
    "method_source_url",
    "notes",
]


def parse_substitution_matrix(text: str) -> dict[str, dict[str, int]]:
    """Parse the NCBI-format matrix embedded above into a lookup table."""

    lines = [line.split() for line in text.splitlines() if line.strip()]
    header = lines[0]
    matrix: dict[str, dict[str, int]] = {}
    for row in lines[1:]:
        residue, values = row[0], row[1:]
        if len(values) != len(header):
            raise ValueError(f"Invalid BLOSUM62 row for {residue}")
        matrix[residue] = dict(zip(header, map(int, values), strict=True))
    return matrix


BLOSUM62 = parse_substitution_matrix(BLOSUM62_TEXT)


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("ascii")).hexdigest()


def parse_fasta(path: Path) -> dict[str, str]:
    sequences: dict[str, str] = {}
    current_id: str | None = None
    chunks: list[str] = []
    with path.open("r", encoding="utf-8") as stream:
        for raw_line in stream:
            line = raw_line.strip()
            if not line:
                continue
            if line.startswith(">"):
                if current_id is not None:
                    sequences[current_id] = "".join(chunks).upper()
                current_id = line[1:].split("|", 1)[0]
                chunks = []
            else:
                chunks.append(line)
    if current_id is not None:
        sequences[current_id] = "".join(chunks).upper()
    return sequences


def smith_waterman_linear(sequence_a: str, sequence_b: str) -> tuple[int, str, str]:
    """Local alignment with constant match, mismatch, and gap scores."""

    rows, columns = len(sequence_a) + 1, len(sequence_b) + 1
    scores = [[0] * columns for _ in range(rows)]
    pointers = [bytearray(columns) for _ in range(rows)]
    best_score = 0
    best_i = best_j = 0

    for i in range(1, rows):
        residue_a = sequence_a[i - 1]
        for j in range(1, columns):
            residue_b = sequence_b[j - 1]
            diagonal = scores[i - 1][j - 1] + (
                LINEAR_MATCH_SCORE
                if residue_a == residue_b
                else LINEAR_MISMATCH_SCORE
            )
            up = scores[i - 1][j] + LINEAR_GAP_SCORE
            left = scores[i][j - 1] + LINEAR_GAP_SCORE
            value = max(0, diagonal, up, left)
            scores[i][j] = value
            if value == 0:
                pointers[i][j] = H_STOP
            elif value == diagonal:
                pointers[i][j] = H_DIAGONAL
            elif value == up:
                pointers[i][j] = H_FROM_VERTICAL_GAP
            else:
                pointers[i][j] = H_FROM_HORIZONTAL_GAP
            if value > best_score:
                best_score, best_i, best_j = value, i, j

    aligned_a: list[str] = []
    aligned_b: list[str] = []
    i, j = best_i, best_j
    while i > 0 and j > 0 and scores[i][j] > 0:
        pointer = pointers[i][j]
        if pointer == H_DIAGONAL:
            aligned_a.append(sequence_a[i - 1])
            aligned_b.append(sequence_b[j - 1])
            i -= 1
            j -= 1
        elif pointer == H_FROM_VERTICAL_GAP:
            aligned_a.append(sequence_a[i - 1])
            aligned_b.append("-")
            i -= 1
        elif pointer == H_FROM_HORIZONTAL_GAP:
            aligned_a.append("-")
            aligned_b.append(sequence_b[j - 1])
            j -= 1
        else:
            break

    return best_score, "".join(reversed(aligned_a)), "".join(reversed(aligned_b))


def blosum62_score(residue_a: str, residue_b: str) -> int:
    try:
        return BLOSUM62[residue_a][residue_b]
    except KeyError as error:
        raise ValueError(
            f"Unsupported residue for BLOSUM62: {residue_a!r} or {residue_b!r}"
        ) from error


def smith_waterman_blosum62_affine_with_positions(
    sequence_a: str, sequence_b: str
) -> tuple[int, str, str, list[tuple[int | None, int | None]]]:
    """Local alignment with BLOSUM62 and NCBI-style affine gap costs.

    A gap of length k has cost -(gap_open + gap_extend * k). With the
    parameters below, a one-residue gap costs -12 and each added residue costs
    -1. H stores the best local score; horizontal_gap and vertical_gap retain
    the state needed to distinguish opening a gap from extending one.
    """

    rows, columns = len(sequence_a) + 1, len(sequence_b) + 1
    h = [[0] * columns for _ in range(rows)]
    horizontal_gap = [[NEGATIVE_INFINITY] * columns for _ in range(rows)]
    vertical_gap = [[NEGATIVE_INFINITY] * columns for _ in range(rows)]
    h_pointers = [bytearray(columns) for _ in range(rows)]
    horizontal_pointers = [bytearray(columns) for _ in range(rows)]
    vertical_pointers = [bytearray(columns) for _ in range(rows)]
    best_score = 0
    best_i = best_j = 0

    for i in range(1, rows):
        residue_a = sequence_a[i - 1]
        for j in range(1, columns):
            residue_b = sequence_b[j - 1]

            horizontal_from_h = h[i][j - 1] - AFFINE_GAP_OPEN - AFFINE_GAP_EXTEND
            horizontal_from_gap = horizontal_gap[i][j - 1] - AFFINE_GAP_EXTEND
            if horizontal_from_h >= horizontal_from_gap:
                horizontal_gap[i][j] = horizontal_from_h
                horizontal_pointers[i][j] = GAP_FROM_H
            else:
                horizontal_gap[i][j] = horizontal_from_gap
                horizontal_pointers[i][j] = GAP_FROM_GAP

            vertical_from_h = h[i - 1][j] - AFFINE_GAP_OPEN - AFFINE_GAP_EXTEND
            vertical_from_gap = vertical_gap[i - 1][j] - AFFINE_GAP_EXTEND
            if vertical_from_h >= vertical_from_gap:
                vertical_gap[i][j] = vertical_from_h
                vertical_pointers[i][j] = GAP_FROM_H
            else:
                vertical_gap[i][j] = vertical_from_gap
                vertical_pointers[i][j] = GAP_FROM_GAP

            diagonal = h[i - 1][j - 1] + blosum62_score(residue_a, residue_b)
            value = max(0, diagonal, horizontal_gap[i][j], vertical_gap[i][j])
            h[i][j] = value
            if value == 0:
                h_pointers[i][j] = H_STOP
            elif value == diagonal:
                h_pointers[i][j] = H_DIAGONAL
            elif value == horizontal_gap[i][j]:
                h_pointers[i][j] = H_FROM_HORIZONTAL_GAP
            else:
                h_pointers[i][j] = H_FROM_VERTICAL_GAP
            if value > best_score:
                best_score, best_i, best_j = value, i, j

    aligned_a: list[str] = []
    aligned_b: list[str] = []
    positions: list[tuple[int | None, int | None]] = []
    state = "h"
    i, j = best_i, best_j
    while i > 0 and j > 0:
        if state == "h":
            pointer = h_pointers[i][j]
            if pointer == H_STOP or h[i][j] <= 0:
                break
            if pointer == H_DIAGONAL:
                aligned_a.append(sequence_a[i - 1])
                aligned_b.append(sequence_b[j - 1])
                positions.append((i - 1, j - 1))
                i -= 1
                j -= 1
            elif pointer == H_FROM_HORIZONTAL_GAP:
                state = "horizontal_gap"
            else:
                state = "vertical_gap"
        elif state == "horizontal_gap":
            pointer = horizontal_pointers[i][j]
            aligned_a.append("-")
            aligned_b.append(sequence_b[j - 1])
            positions.append((None, j - 1))
            j -= 1
            state = "h" if pointer == GAP_FROM_H else "horizontal_gap"
        else:
            pointer = vertical_pointers[i][j]
            aligned_a.append(sequence_a[i - 1])
            aligned_b.append("-")
            positions.append((i - 1, None))
            i -= 1
            state = "h" if pointer == GAP_FROM_H else "vertical_gap"

    return (
        best_score,
        "".join(reversed(aligned_a)),
        "".join(reversed(aligned_b)),
        list(reversed(positions)),
    )


def smith_waterman_blosum62_affine(
    sequence_a: str, sequence_b: str
) -> tuple[int, str, str]:
    """Return the public three-value affine local-alignment result.

    The companion ``*_with_positions`` function additionally retains the
    zero-based residue indices used during traceback. That mapping is needed
    by the separate, sequence-guided structure comparison pipeline.
    """

    score, aligned_a, aligned_b, _positions = smith_waterman_blosum62_affine_with_positions(
        sequence_a, sequence_b
    )
    return score, aligned_a, aligned_b


def alignment_metrics(
    sequence_a: str, sequence_b: str, score: int, aligned_a: str, aligned_b: str
) -> dict[str, float | int]:
    alignment_length = len(aligned_a)
    paired_residues = sum(
        residue_a != "-" and residue_b != "-"
        for residue_a, residue_b in zip(aligned_a, aligned_b)
    )
    identical = sum(
        residue_a == residue_b and residue_a != "-"
        for residue_a, residue_b in zip(aligned_a, aligned_b)
    )
    query_aligned_residues = sum(residue != "-" for residue in aligned_a)
    target_aligned_residues = sum(residue != "-" for residue in aligned_b)
    gaps = alignment_length - paired_residues
    identity_pct = 100.0 * identical / paired_residues if paired_residues else 0.0
    query_coverage_pct = 100.0 * query_aligned_residues / len(sequence_a)
    target_coverage_pct = 100.0 * target_aligned_residues / len(sequence_b)
    return {
        "alignment_score": score,
        "identity_pct": identity_pct,
        "identical_residues": identical,
        "aligned_residues": paired_residues,
        "query_aligned_residues": query_aligned_residues,
        "target_aligned_residues": target_aligned_residues,
        "alignment_length": alignment_length,
        "query_coverage_pct": query_coverage_pct,
        "target_coverage_pct": target_coverage_pct,
        "minimum_coverage_pct": min(query_coverage_pct, target_coverage_pct),
        "gap_fraction_pct": 100.0 * gaps / alignment_length if alignment_length else 0.0,
    }


def karlin_altschul(score: float, length_a: int, length_b: int) -> tuple[float, float]:
    """Return (E-value, bit score) for a raw BLOSUM62 11/1 local-alignment score."""
    evalue = KA_K * length_a * length_b * math.exp(-KA_LAMBDA * score)
    bits = (KA_LAMBDA * score - math.log(KA_K)) / math.log(2)
    return evalue, bits


def interpretation(identity_pct: float, minimum_coverage_pct: float) -> str:
    if identity_pct >= 30 and minimum_coverage_pct >= 50:
        return "stronger sequence-homology signal; inspect domains and structure"
    if identity_pct >= 20 and minimum_coverage_pct >= 30:
        return "partial sequence-similarity lead; do not infer shared disease mechanism"
    return "low or localized sequence similarity; retain pathway and phenotype evidence separately"


def load_records(csv_path: Path, fasta_path: Path) -> list[dict[str, str]]:
    sequences = parse_fasta(fasta_path)
    with csv_path.open("r", encoding="utf-8", newline="") as stream:
        records = list(csv.DictReader(stream))
    if len(records) < 2:
        raise ValueError(f"Need at least two protein records in {csv_path}")
    for record in records:
        protein_id = record["protein_id"]
        sequence = sequences.get(protein_id)
        if not sequence:
            raise ValueError(f"Missing FASTA sequence for {protein_id}")
        expected_hash = record.get("sequence_sha256", "")
        actual_hash = sha256_text(sequence)
        if expected_hash and expected_hash != actual_hash:
            raise ValueError(f"Sequence checksum mismatch for {protein_id}")
        record["_sequence"] = sequence
    return records


AlignmentFunction = Callable[[str, str], tuple[int, str, str]]


def method_specs() -> tuple[dict[str, str | AlignmentFunction], ...]:
    return (
        {
            "method": LINEAR_METHOD,
            "substitution_matrix": "identity_match+2_mismatch-1",
            "gap_model": "linear",
            "gap_open_penalty": "",
            "gap_extend_penalty": str(abs(LINEAR_GAP_SCORE)),
            "score_name": "smith_waterman_linear_raw_score",
            "method_source_url": "",
            "notes": "Transparent teaching baseline; not calibrated for protein substitution chemistry.",
            "align": smith_waterman_linear,
        },
        {
            "method": AFFINE_METHOD,
            "substitution_matrix": "BLOSUM62",
            "gap_model": "affine; cost=-(open + extend*gap_length)",
            "gap_open_penalty": str(AFFINE_GAP_OPEN),
            "gap_extend_penalty": str(AFFINE_GAP_EXTEND),
            "score_name": "smith_waterman_blosum62_affine_raw_score",
            "method_source_url": BLOSUM62_SOURCE_URL,
            "notes": "BLOSUM62 with NCBI-style affine gaps; raw score is only comparable within this method.",
            "align": smith_waterman_blosum62_affine,
        },
    )


def build_rows(records: list[dict[str, str]]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for index, source in enumerate(records):
        for target in records[index + 1 :]:
            source_id = source["protein_id"]
            target_id = target["protein_id"]
            pair_key = f"{source_id}__{target_id}".replace(":", "_")
            for spec in method_specs():
                align = spec["align"]
                assert callable(align)
                score, aligned_a, aligned_b = align(source["_sequence"], target["_sequence"])
                metrics = alignment_metrics(
                    source["_sequence"], target["_sequence"], score, aligned_a, aligned_b
                )
                identity_pct = float(metrics["identity_pct"])
                minimum_coverage_pct = float(metrics["minimum_coverage_pct"])
                method = str(spec["method"])
                evalue_text = bits_text = significance = ""
                if method == AFFINE_METHOD:
                    evalue, bits = karlin_altschul(float(score), len(source["_sequence"]), len(target["_sequence"]))
                    evalue_text, bits_text = f"{evalue:.3g}", f"{bits:.1f}"
                    significance = (
                        f"E-value {evalue:.2g}: {'statistically significant' if evalue < SIGNIFICANT_EVALUE else 'not distinguishable from chance'}. "
                    )
                row = {
                    "similarity_id": f"SIMSEQ:{method}:{pair_key}",
                    "source_protein_id": source_id,
                    "target_protein_id": target_id,
                    "source_gene_symbol": source["gene_symbol"],
                    "target_gene_symbol": target["gene_symbol"],
                    "method": method,
                    "substitution_matrix": str(spec["substitution_matrix"]),
                    "gap_model": str(spec["gap_model"]),
                    "gap_open_penalty": str(spec["gap_open_penalty"]),
                    "gap_extend_penalty": str(spec["gap_extend_penalty"]),
                    "alignment_score": str(metrics["alignment_score"]),
                    "identity_pct": f"{identity_pct:.3f}",
                    "identical_residues": str(metrics["identical_residues"]),
                    "aligned_residues": str(metrics["aligned_residues"]),
                    "query_aligned_residues": str(metrics["query_aligned_residues"]),
                    "target_aligned_residues": str(metrics["target_aligned_residues"]),
                    "alignment_length": str(metrics["alignment_length"]),
                    "query_coverage_pct": f"{float(metrics['query_coverage_pct']):.3f}",
                    "target_coverage_pct": f"{float(metrics['target_coverage_pct']):.3f}",
                    "minimum_coverage_pct": f"{minimum_coverage_pct:.3f}",
                    "gap_fraction_pct": f"{float(metrics['gap_fraction_pct']):.3f}",
                    "evalue": evalue_text,
                    "bitscore": bits_text,
                    "embedding_model": "",
                    "embedding_version": "",
                    "cosine_similarity": "",
                    "structure_source": "",
                    "tm_score": "",
                    "lddt": "",
                    "assertion_level": "inferred",
                    "evidence_id": f"COMPUTED:SIMSEQ:{method}:{pair_key}",
                    "primary_score": str(metrics["alignment_score"]),
                    "score_name": str(spec["score_name"]),
                    "dataset_release": ";".join(
                        sorted(
                            {
                                source.get("source_release", "unknown"),
                                target.get("source_release", "unknown"),
                            }
                        )
                    ),
                    "source_url": f"{source.get('source_url', '')};{target.get('source_url', '')}",
                    "method_source_url": str(spec["method_source_url"]),
                    "notes": (
                        f"{significance}{interpretation(identity_pct, minimum_coverage_pct)}. "
                        f"{spec['notes']} Alignment checksum={sha256_text(aligned_a + '|' + aligned_b)}."
                    ),
                }
                rows.append(row)
    return rows


def write_manifest(root: Path, records: list[dict[str, str]], rows: list[dict[str, str]]) -> None:
    manifest_path = root / "data" / "manifests" / "protein_similarity_v0.2.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "pipeline": "RarePath protein sequence similarity baselines",
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "inputs": {
            "proteins_csv": "data/processed/proteins.csv",
            "proteins_fasta": "data/processed/proteins.fasta",
            "protein_count": len(records),
            "unique_pair_count": len(records) * (len(records) - 1) // 2,
            "result_row_count": len(rows),
        },
        "methods": [
            {key: value for key, value in spec.items() if key != "align"}
            for spec in method_specs()
        ],
        "significance": {
            "applies_to": AFFINE_METHOD,
            "parameters": KA_SOURCE,
            "formula": "E = K*m*n*exp(-lambda*S); bits = (lambda*S - ln K)/ln 2; no edge correction",
            "significant_if_evalue_below": SIGNIFICANT_EVALUE,
        },
        "interpretation": "Computational research-navigation signals; not disease, pathogenicity, or treatment predictions.",
    }
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--proteins-csv", default="data/processed/proteins.csv")
    parser.add_argument("--proteins-fasta", default="data/processed/proteins.fasta")
    parser.add_argument("--output", default="data/processed/protein_similarity.csv")
    args = parser.parse_args()

    root = Path(args.repo_root).resolve()
    records = load_records(root / args.proteins_csv, root / args.proteins_fasta)
    rows = build_rows(records)
    output_path = root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    write_manifest(root, records, rows)
    print(f"Wrote {len(rows)} comparison rows for {len(records)} proteins to {output_path}")
    print(f"Methods: {LINEAR_METHOD}; {AFFINE_METHOD}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
