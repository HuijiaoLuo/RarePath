# Data sources, licences and attribution

RarePath contains two different kinds of material:

1. RarePath's original code, interface, documentation and derived methods, which
   are released under the Apache License 2.0 in [`LICENSE`](../LICENSE).
2. Third-party data, records and links, which keep the terms of their own
   providers. The Apache licence for this repository does not relicense those
   sources.

The current public snapshot uses the following sources. Release numbers and
retrieval dates are recorded in `data/manifests/` so that a future rebuild can
refresh both the data and this attribution record.

| Source | What RarePath uses | Current snapshot | Licence or use condition | Attribution and link |
| --- | --- | --- | --- | --- |
| [Mondo Disease Ontology](https://mondo.monarchinitiative.org/pages/download/) | Disease names, synonyms, cross-references, disease series and classes | v2026-09-01 | CC BY 4.0 | Credit the Mondo Disease Ontology and cite the paper the Mondo repository lists: “Mondo: integrating disease terminology across communities”, *Genetics* 232(4), 2026, [doi:10.1093/genetics/iyaf215](https://doi.org/10.1093/genetics/iyaf215). |
| [Human Phenotype Ontology](https://human-phenotype-ontology.github.io/license.html) | HPO terms, hierarchy and disease annotations | HPO v2026-09-01; annotation header 2026-09-02 | HPO requires acknowledgement, citation and the displayed release/version. HPO files and their logical relationships must not be altered. | Credit the Human Phenotype Ontology Consortium, cite the reference listed on HPO's licence page: Köhler et al., “The Human Phenotype Ontology project: linking molecular biology and disease through phenotype data”, *Nucleic Acids Research* 42 (2014), D966–D974, [doi:10.1093/nar/gkt1026](https://doi.org/10.1093/nar/gkt1026), and show the sentence “This service uses the Human Phenotype Ontology (version …)” where HPO data is displayed. Both RarePath pages show it with the release. HPO's conditions also mention its logo; the pages currently use a text credit, so adding the official logo is an open item. |
| [Reactome](https://reactome.org/license) | Human pathway membership and pathway-size metadata | Reactome v97 | Reactome data and data files are CC0; attribution is encouraged. Reactome software, illustrations and branding have separate terms. RarePath uses the data, not Reactome artwork. | Credit Reactome, link to the [licence](https://reactome.org/license), and cite the [Reactome Knowledgebase 2026 paper](https://doi.org/10.1093/nar/gkaf1223) (or the stable pathway identifier for a pathway-specific citation). |
| [UniProt](https://www.uniprot.org/api-documentation/support-data) | Reviewed human protein mappings, sequences, function and location | UniProt release 2026_03 | Copyrightable parts of the databases are CC BY 4.0, and the UniProt copyright statement should travel with each copy. RarePath shows UniProt function and location text unchanged except for removing evidence tags and keeping only the canonical isoform. | Credit UniProt and retain the accession and release. Cite [“UniProt: the Universal Protein Knowledgebase in 2025”](https://www.uniprot.org/help/publications), *Nucleic Acids Research* 53:D609–D617 (2025). Statement: “Copyrighted by the UniProt Consortium, see https://www.uniprot.org/terms. Distributed under the Creative Commons Attribution (CC BY 4.0) License.” |
| [AlphaFold Protein Structure Database](https://www.alphafold.ebi.ac.uk/) | Versioned predicted monomer models and residue-level pLDDT values | AlphaFold model version 6 for the four seed proteins; expanded profiles are recorded in the manifest | CC BY 4.0. EMBL-EBI expects attribution; predictions are not experimental structures, and AlphaFold DB states its data is not a substitute for professional medical advice. RarePath stores a reduced copy (C-alpha positions and pLDDT), which is a modification of the model files. | Credit AlphaFold DB, EMBL-EBI and Google DeepMind. Cite [AlphaFold Protein Structure Database 2025](https://www.alphafold.ebi.ac.uk/) and the methods paper, [Jumper et al., *Nature* (2021)](https://doi.org/10.1038/s41586-021-03819-2), and retain the [licence/disclaimer](https://alphafold.ebi.ac.uk/assets/License-Disclaimer.pdf). |
| [ClinVar](https://www.ncbi.nlm.nih.gov/clinvar/docs/maintenance_use/) | Public variant classifications and submitter-provided evidence identifiers | Retrieved 2026-10-05; 2,633 retained missense records | Publicly available for reuse; NCBI asks users who copy or distribute data to attribute ClinVar. Classifications remain attributable to the original submitters. ClinVar states its data is not intended for direct diagnostic use or medical decisions without review by a genetics professional; RarePath's variant view is descriptive and repeats that limit. | Credit ClinVar/NCBI, cite one of the [ClinVar publications (for example PMID 29165669)](https://pubmed.ncbi.nlm.nih.gov/29165669/), and retain ClinVar accession/version links where available. |
| [ClinicalTrials.gov](https://clinicaltrials.gov/) | Study identifiers, titles, status snapshots and links | Records retrieved 2026-10-03 to 2026-10-05 | ClinicalTrials.gov's terms ask users to cite the source, show the date the data were processed, and state any modifications. RarePath shows a few fields (title, sponsor, status, conditions) unchanged, with the retrieval date; the links from a study to diseases are RarePath's own. The terms also ask that data be kept current; a static snapshot cannot do that, so every study view says to check the live record. | Credit ClinicalTrials.gov and the U.S. National Library of Medicine; preserve its disclaimer. |
| Patient organisations and foundations | Public organisation names and official links | Curated records in `data/curated/family_resources.csv` | RarePath links to the official pages and does not copy their site content or branding. Their own terms apply. | Credit each organisation by name and link to its official page. |

## Fonts and code

- Fonts (Atkinson Hyperlegible, Bricolage Grotesque) are loaded from Google Fonts under the SIL Open Font License; they are not redistributed in this repository.
- The explorer uses no third-party JavaScript library; the structure viewer is RarePath's own code.

## What is shown in the product

The explorer labels source-backed facts as coming from a database and labels
similarity scores and structure comparisons as computed by RarePath. Every
source record keeps a URL, identifier, snapshot date or release, and method
metadata where available. The page's graph version identifies the exact
content snapshot used by the exported graph and by an API answer.

The AlphaFold models in `demo/data/structures.js` carry an inline CC BY 4.0
notice. The fuller source list belongs here so that the static site, README and
repository all point to the same attribution record.

## Scope and limitations

This file records the terms checked for the current snapshot (last checked 2026-10-08 against each provider's licence or terms page linked above, plus the [AlphaFold DB licence notice](https://alphafold.ebi.ac.uk/assets/License-Disclaimer.pdf) and the [ClinicalTrials.gov terms](https://clinicaltrials.gov/about-site/terms-conditions)); it is not legal
advice. Source terms can change, and a source record may have additional
conditions. Before a commercial redistribution or a large refresh, recheck the
provider's current page and update the manifest and this document together.

RarePath uses aggregate public research data. It does not add patient-level
data to these source snapshots, and its derived similarity, ClinVar pattern and
AlphaFold comparison outputs are research-navigation signals rather than
clinical conclusions.
