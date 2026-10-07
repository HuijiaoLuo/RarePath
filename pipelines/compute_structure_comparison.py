#!/usr/bin/env python3
"""Compute a bounded, sequence-guided 3D backbone comparison.

This is a transparent preliminary structure layer for the four AlphaFold DB
models already fetched by ``fetch_alphafold_structures.py``. It does not run a
database structure search and it does not report a TM-score. Instead, it:

1. reproduces the BLOSUM62 affine local alignment used for sequence evidence;
2. maps its residue pairs to AlphaFold PDB C-alpha coordinates;
3. retains pairs whose two AlphaFold pLDDT values meet a stated threshold; and
4. finds the rigid rotation and translation that minimize C-alpha RMSD.

The result is useful as a reproducible check for a strong sequence-homology
lead such as HEXA/HEXB. It is not evidence of a shared disease mechanism,
substrate, clinical effect, or a substitute for a structure-search method such
as TM-align or Foldseek.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import combinations
from pathlib import Path

if __package__ in (None, ""):
    # ``python pipelines/compute_structure_comparison.py`` puts the pipelines
    # directory, not the repository root, on sys.path.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipelines.compute_protein_similarity import (
    alignment_metrics,
    load_records,
    smith_waterman_blosum62_affine_with_positions,
)


SCRIPT_VERSION = "0.1.0"
METHOD = "sequence_guided_ca_superposition_horn_quaternion_v0.1"
SEQUENCE_ALIGNMENT_METHOD = "smith_waterman_local_blosum62_affine_v0.2"
PLDDT_CUTOFF = 70.0
MIN_MAPPED_CA_PAIRS = 30
MIN_MAPPING_COVERAGE_PCT = 25.0

CSV_FIELDS = [
    "structure_comparison_id",
    "source_protein_id",
    "target_protein_id",
    "source_gene_symbol",
    "target_gene_symbol",
    "method",
    "sequence_alignment_method",
    "source_structure_id",
    "target_structure_id",
    "source_model_version",
    "target_model_version",
    "source_model_sha256",
    "target_model_sha256",
    "alignment_score",
    "identity_pct",
    "aligned_residue_pairs",
    "minimum_sequence_coverage_pct",
    "mapped_ca_pairs",
    "minimum_mapped_ca_coverage_pct",
    "plddt_cutoff",
    "high_confidence_ca_pairs",
    "source_mean_plddt_mapped",
    "target_mean_plddt_mapped",
    "source_mean_plddt_used",
    "target_mean_plddt_used",
    "ca_rmsd_angstrom",
    "structure_source",
    "source_model_url",
    "target_model_url",
    "assertion_level",
    "evidence_id",
    "status",
    "notes",
]

THREE_TO_ONE = {
    "ALA": "A", "ARG": "R", "ASN": "N", "ASP": "D", "CYS": "C",
    "GLN": "Q", "GLU": "E", "GLY": "G", "HIS": "H", "ILE": "I",
    "LEU": "L", "LYS": "K", "MET": "M", "PHE": "F", "PRO": "P",
    "SER": "S", "THR": "T", "TRP": "W", "TYR": "Y", "VAL": "V",
}

Vector = tuple[float, float, float]


@dataclass(frozen=True)
class CaAtom:
    """One C-alpha atom, in model order, with AlphaFold pLDDT in B-factor."""

    residue: str
    coordinate: Vector
    plddt: float


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_ca_trace(path: Path) -> list[CaAtom]:
    """Read one C-alpha per PDB residue, preserving coordinate order.

    AlphaFold PDB uses the B-factor field for pLDDT. Alternate locations are
    skipped unless blank or ``A``; the downloaded AlphaFold models contain no
    alternate conformations, but the check makes the parser explicit.
    """

    trace: list[CaAtom] = []
    seen_residues: set[tuple[str, str, str]] = set()
    with path.open("r", encoding="utf-8") as stream:
        for line in stream:
            if not line.startswith("ATOM") or line[12:16].strip() != "CA":
                continue
            if line[16] not in (" ", "A"):
                continue
            residue_key = (line[21], line[22:26], line[26])
            if residue_key in seen_residues:
                continue
            try:
                residue = THREE_TO_ONE[line[17:20].strip()]
                coordinate = (
                    float(line[30:38]),
                    float(line[38:46]),
                    float(line[46:54]),
                )
                plddt = float(line[60:66])
            except (KeyError, ValueError) as error:
                raise ValueError(f"Could not parse C-alpha atom in {path}: {line!r}") from error
            trace.append(CaAtom(residue, coordinate, plddt))
            seen_residues.add(residue_key)
    if not trace:
        raise ValueError(f"No C-alpha atoms found in {path}")
    return trace


def validate_trace_against_sequence(trace: list[CaAtom], sequence: str, path: Path) -> None:
    observed = "".join(atom.residue for atom in trace)
    if observed != sequence:
        raise ValueError(
            f"PDB C-alpha sequence does not match UniProt sequence for {path}: "
            f"{len(observed)} model residues vs {len(sequence)} sequence residues."
        )


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def centroid(points: list[Vector]) -> Vector:
    count = len(points)
    if not count:
        raise ValueError("Cannot center an empty coordinate set")
    return tuple(sum(point[index] for point in points) / count for index in range(3))  # type: ignore[return-value]


def subtract(point: Vector, offset: Vector) -> Vector:
    return (point[0] - offset[0], point[1] - offset[1], point[2] - offset[2])


def add(point: Vector, offset: Vector) -> Vector:
    return (point[0] + offset[0], point[1] + offset[1], point[2] + offset[2])


def matvec(matrix: list[list[float]], point: Vector) -> Vector:
    return tuple(sum(matrix[row][column] * point[column] for column in range(3)) for row in range(3))  # type: ignore[return-value]


def largest_eigenvector_symmetric_4(matrix: list[list[float]]) -> list[float]:
    """Return the unit eigenvector for a symmetric 4x4 matrix's largest root.

    Jacobi rotations are practical here because the matrix is always 4x4. The
    routine keeps this pipeline standard-library-only and avoids a hidden
    numerical package dependency.
    """

    if len(matrix) != 4 or any(len(row) != 4 for row in matrix):
        raise ValueError("Expected a 4x4 matrix")
    values = [row[:] for row in matrix]
    vectors = [[1.0 if row == column else 0.0 for column in range(4)] for row in range(4)]
    for _ in range(100):
        row, column = max(
            ((row, column) for row in range(4) for column in range(row + 1, 4)),
            key=lambda pair: abs(values[pair[0]][pair[1]]),
        )
        off_diagonal = values[row][column]
        if abs(off_diagonal) < 1e-12:
            break
        angle = 0.5 * math.atan2(2.0 * off_diagonal, values[column][column] - values[row][row])
        cosine, sine = math.cos(angle), math.sin(angle)
        original_row = values[row][row]
        original_column = values[column][column]

        for index in range(4):
            if index in (row, column):
                continue
            value_row = values[index][row]
            value_column = values[index][column]
            values[index][row] = values[row][index] = cosine * value_row - sine * value_column
            values[index][column] = values[column][index] = sine * value_row + cosine * value_column
        values[row][row] = (
            cosine * cosine * original_row
            - 2.0 * sine * cosine * off_diagonal
            + sine * sine * original_column
        )
        values[column][column] = (
            sine * sine * original_row
            + 2.0 * sine * cosine * off_diagonal
            + cosine * cosine * original_column
        )
        values[row][column] = values[column][row] = 0.0

        for index in range(4):
            vector_row = vectors[index][row]
            vector_column = vectors[index][column]
            vectors[index][row] = cosine * vector_row - sine * vector_column
            vectors[index][column] = sine * vector_row + cosine * vector_column

    largest_index = max(range(4), key=lambda index: values[index][index])
    result = [vectors[index][largest_index] for index in range(4)]
    scale = math.sqrt(sum(value * value for value in result))
    if scale == 0:
        raise ValueError("Could not determine a rotation quaternion")
    return [value / scale for value in result]


def quaternion_rotation(quaternion: list[float]) -> list[list[float]]:
    """Convert a normalized [w, x, y, z] quaternion into a 3x3 rotation."""

    w, x, y, z = quaternion
    return [
        [1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
        [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
        [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)],
    ]


def horn_rotation(source: list[Vector], target: list[Vector]) -> list[list[float]]:
    """Find the proper rotation from centered source points to target points.

    Horn's quaternion formulation obtains the Kabsch least-squares rigid fit
    without a general SVD. ``source`` and ``target`` must already have their
    centroids removed and must have corresponding points in the same order.
    """

    if len(source) != len(target) or len(source) < 3:
        raise ValueError("Need at least three paired coordinates for a rigid fit")
    covariance = [[0.0] * 3 for _ in range(3)]
    for source_point, target_point in zip(source, target):
        for row in range(3):
            for column in range(3):
                covariance[row][column] += source_point[row] * target_point[column]
    xx, xy, xz = covariance[0]
    yx, yy, yz = covariance[1]
    zx, zy, zz = covariance[2]
    trace = xx + yy + zz
    quaternion_matrix = [
        [trace, yz - zy, zx - xz, xy - yx],
        [yz - zy, xx - yy - zz, xy + yx, zx + xz],
        [zx - xz, xy + yx, -xx + yy - zz, yz + zy],
        [xy - yx, zx + xz, yz + zy, -xx - yy + zz],
    ]
    return quaternion_rotation(largest_eigenvector_symmetric_4(quaternion_matrix))


def rigid_superposition(source: list[Vector], target: list[Vector]) -> tuple[float, list[list[float]], Vector]:
    """Return minimum C-alpha RMSD, rotation, and translation for paired points."""

    source_center = centroid(source)
    target_center = centroid(target)
    centered_source = [subtract(point, source_center) for point in source]
    centered_target = [subtract(point, target_center) for point in target]
    rotation = horn_rotation(centered_source, centered_target)
    translation = subtract(target_center, matvec(rotation, source_center))
    squared_error = sum(
        sum((add(matvec(rotation, source_point), translation)[axis] - target_point[axis]) ** 2 for axis in range(3))
        for source_point, target_point in zip(source, target)
    )
    return math.sqrt(squared_error / len(source)), rotation, translation


def mapped_ca_pairs(
    source_trace: list[CaAtom],
    target_trace: list[CaAtom],
    positions: list[tuple[int | None, int | None]],
) -> list[tuple[CaAtom, CaAtom]]:
    pairs: list[tuple[CaAtom, CaAtom]] = []
    for source_index, target_index in positions:
        if source_index is None or target_index is None:
            continue
        try:
            pairs.append((source_trace[source_index], target_trace[target_index]))
        except IndexError as error:
            raise ValueError("Sequence alignment index is outside the PDB C-alpha trace") from error
    return pairs


def load_structure_rows(path: Path) -> dict[str, dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as stream:
        rows = list(csv.DictReader(stream))
    result = {row["protein_id"]: row for row in rows if row.get("status") == "downloaded"}
    if not result:
        raise ValueError(f"No downloaded structure models found in {path}")
    return result


def build_row(
    root: Path,
    source: dict[str, str],
    target: dict[str, str],
    structures: dict[str, dict[str, str]],
    plddt_cutoff: float,
    min_mapped_ca_pairs: int,
    min_mapping_coverage_pct: float,
) -> dict[str, str]:
    source_structure = structures[source["protein_id"]]
    target_structure = structures[target["protein_id"]]
    source_path = root / source_structure["raw_model_path"]
    target_path = root / target_structure["raw_model_path"]
    if sha256_file(source_path) != source_structure["model_sha256"]:
        raise ValueError(f"Structure checksum mismatch: {source_path}")
    if sha256_file(target_path) != target_structure["model_sha256"]:
        raise ValueError(f"Structure checksum mismatch: {target_path}")
    source_trace = parse_ca_trace(source_path)
    target_trace = parse_ca_trace(target_path)
    validate_trace_against_sequence(source_trace, source["_sequence"], source_path)
    validate_trace_against_sequence(target_trace, target["_sequence"], target_path)

    score, aligned_source, aligned_target, positions = smith_waterman_blosum62_affine_with_positions(
        source["_sequence"], target["_sequence"]
    )
    metrics = alignment_metrics(source["_sequence"], target["_sequence"], score, aligned_source, aligned_target)
    mapped = mapped_ca_pairs(source_trace, target_trace, positions)
    mapped_coverage = min(
        100.0 * len(mapped) / len(source_trace),
        100.0 * len(mapped) / len(target_trace),
    )
    source_mapped_plddt = [pair[0].plddt for pair in mapped]
    target_mapped_plddt = [pair[1].plddt for pair in mapped]
    high_confidence = [
        pair for pair in mapped if pair[0].plddt >= plddt_cutoff and pair[1].plddt >= plddt_cutoff
    ]

    pair_key = f"{source['protein_id']}__{target['protein_id']}".replace(":", "_")
    row = {
        "structure_comparison_id": f"SIMSTRUCT:{METHOD}:{pair_key}",
        "source_protein_id": source["protein_id"],
        "target_protein_id": target["protein_id"],
        "source_gene_symbol": source["gene_symbol"],
        "target_gene_symbol": target["gene_symbol"],
        "method": METHOD,
        "sequence_alignment_method": SEQUENCE_ALIGNMENT_METHOD,
        "source_structure_id": source_structure["structure_id"],
        "target_structure_id": target_structure["structure_id"],
        "source_model_version": source_structure["model_version"],
        "target_model_version": target_structure["model_version"],
        "source_model_sha256": source_structure["model_sha256"],
        "target_model_sha256": target_structure["model_sha256"],
        "alignment_score": str(score),
        "identity_pct": f"{float(metrics['identity_pct']):.3f}",
        "aligned_residue_pairs": str(metrics["aligned_residues"]),
        "minimum_sequence_coverage_pct": f"{float(metrics['minimum_coverage_pct']):.3f}",
        "mapped_ca_pairs": str(len(mapped)),
        "minimum_mapped_ca_coverage_pct": f"{mapped_coverage:.3f}",
        "plddt_cutoff": f"{plddt_cutoff:.1f}",
        "high_confidence_ca_pairs": str(len(high_confidence)),
        "source_mean_plddt_mapped": f"{mean(source_mapped_plddt):.3f}",
        "target_mean_plddt_mapped": f"{mean(target_mapped_plddt):.3f}",
        "source_mean_plddt_used": "",
        "target_mean_plddt_used": "",
        "ca_rmsd_angstrom": "",
        "structure_source": "AlphaFold Protein Structure Database; predicted monomer models",
        "source_model_url": source_structure["model_url"],
        "target_model_url": target_structure["model_url"],
        "assertion_level": "inferred",
        "evidence_id": f"COMPUTED:SIMSTRUCT:{METHOD}:{pair_key}",
        "status": "",
        "notes": "",
    }
    if len(mapped) < min_mapped_ca_pairs or mapped_coverage < min_mapping_coverage_pct:
        row["status"] = "not_evaluated_insufficient_sequence_mapping"
        row["notes"] = (
            "No rigid superposition: the sequence-guided C-alpha mapping did not meet the "
            f"predeclared gate of {min_mapped_ca_pairs} pairs and {min_mapping_coverage_pct:.1f}% "
            "minimum coverage. This is not evidence of structural dissimilarity."
        )
        return row
    if len(high_confidence) < min_mapped_ca_pairs:
        row["status"] = "not_evaluated_insufficient_high_confidence_pairs"
        row["notes"] = (
            "No rigid superposition: fewer than the predeclared minimum number of mapped C-alpha "
            f"pairs had pLDDT >= {plddt_cutoff:.1f} in both AlphaFold models."
        )
        return row

    source_points = [pair[0].coordinate for pair in high_confidence]
    target_points = [pair[1].coordinate for pair in high_confidence]
    rmsd, _rotation, _translation = rigid_superposition(source_points, target_points)
    row["source_mean_plddt_used"] = f"{mean([pair[0].plddt for pair in high_confidence]):.3f}"
    row["target_mean_plddt_used"] = f"{mean([pair[1].plddt for pair in high_confidence]):.3f}"
    row["ca_rmsd_angstrom"] = f"{rmsd:.3f}"
    row["status"] = "computed"
    row["notes"] = (
        "Sequence-guided C-alpha rigid superposition on aligned residue pairs with pLDDT >= "
        f"{plddt_cutoff:.1f} in both predicted monomer models. RMSD is not a TM-score, an "
        "independent structural alignment, or a clinical similarity measure."
    )
    return row


def write_outputs(root: Path, rows: list[dict[str, str]], args: argparse.Namespace) -> Path:
    output_path = root / args.output
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    manifest_path = root / "data" / "manifests" / "structure_comparison_v0.1.json"
    payload = {
        "pipeline": "RarePath bounded sequence-guided AlphaFold C-alpha comparison",
        "script_version": SCRIPT_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "inputs": {
            "proteins_csv": args.proteins_csv,
            "proteins_fasta": args.proteins_fasta,
            "structure_models_csv": args.structure_models_csv,
        },
        "method": {
            "name": METHOD,
            "sequence_alignment": SEQUENCE_ALIGNMENT_METHOD,
            "coordinate_selection": "PDB C-alpha atoms mapped by affine local alignment",
            "confidence_filter": f"both AlphaFold pLDDT >= {args.plddt_cutoff:.1f}",
            "rigid_fit_objective": "minimize sum_i ||R*x_i + t - y_i||^2 with R a proper rotation",
            "solver": "Horn quaternion least-squares fit; 4x4 symmetric eigenproblem solved by Jacobi rotations",
            "not_reported": ["TM-score", "lDDT", "database-search hit", "clinical similarity"],
        },
        "gates": {
            "minimum_mapped_ca_pairs": args.min_mapped_ca_pairs,
            "minimum_mapping_coverage_pct": args.min_mapping_coverage_pct,
        },
        "result_counts": {
            "total_pairs": len(rows),
            "computed": sum(row["status"] == "computed" for row in rows),
            "not_evaluated": sum(row["status"].startswith("not_evaluated") for row in rows),
        },
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--proteins-csv", default="data/processed/proteins.csv")
    parser.add_argument("--proteins-fasta", default="data/processed/proteins.fasta")
    parser.add_argument("--structure-models-csv", default="data/processed/structure_models.csv")
    parser.add_argument("--output", default="data/processed/structure_comparison.csv")
    parser.add_argument("--plddt-cutoff", type=float, default=PLDDT_CUTOFF)
    parser.add_argument("--min-mapped-ca-pairs", type=int, default=MIN_MAPPED_CA_PAIRS)
    parser.add_argument("--min-mapping-coverage-pct", type=float, default=MIN_MAPPING_COVERAGE_PCT)
    args = parser.parse_args()
    if not 0 <= args.plddt_cutoff <= 100:
        parser.error("--plddt-cutoff must be between 0 and 100")
    if args.min_mapped_ca_pairs < 3:
        parser.error("--min-mapped-ca-pairs must be at least 3")
    if not 0 <= args.min_mapping_coverage_pct <= 100:
        parser.error("--min-mapping-coverage-pct must be between 0 and 100")

    root = Path(args.repo_root).resolve()
    proteins = load_records(root / args.proteins_csv, root / args.proteins_fasta)
    structures = load_structure_rows(root / args.structure_models_csv)
    missing = [record["protein_id"] for record in proteins if record["protein_id"] not in structures]
    if missing:
        raise ValueError("Missing downloaded AlphaFold model(s): " + ", ".join(missing))
    rows = [
        build_row(
            root,
            source,
            target,
            structures,
            args.plddt_cutoff,
            args.min_mapped_ca_pairs,
            args.min_mapping_coverage_pct,
        )
        for source, target in combinations(proteins, 2)
    ]
    manifest_path = write_outputs(root, rows, args)
    computed = sum(row["status"] == "computed" for row in rows)
    print(f"Wrote {len(rows)} structure comparison rows; computed={computed}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as error:
        print(f"Structure comparison failed: {error}")
        raise SystemExit(1)
