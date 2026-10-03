# RarePath Ecosystem Roadmap

## Product thesis

RarePath can grow from a graph viewer into a consent-aware research coordination platform. The useful unit is not an isolated graph node or a public patient profile. It is a traceable research lead that connects:

```text
patient priorities -> natural history -> biology -> candidate intervention
                  -> biomarkers/endpoints -> studies -> collaborators
```

Every lead should show its evidence, uncertainty, owner, and next validation step.

## Four product layers

### 1. Evidence and biology layer

Keep the current Neo4j graph as the evidence-backed foundation:

- diseases, genes, variants, proteins, studies, organizations, and evidence;
- curated versus inferred relationships;
- versioned public-data snapshots;
- source URLs and reproducible data releases.

Protein similarity, phenotype similarity, and pathway matches belong here as derived signals. They should remain visibly different from curated disease-gene facts.

### 2. R&D insight layer

Generate a reviewable research brief for each disease or mechanism. A brief should contain:

- disease definition and unresolved biology;
- candidate targets and biological rationale;
- possible modalities, such as enzyme replacement, small molecule, ASO, or gene therapy;
- measurable biomarkers and patient-relevant outcomes;
- natural-history gaps and possible external-control data;
- relevant studies and research assets;
- candidate collaborators and their public institutional roles;
- evidence grade, assumptions, risks, and the next experiment.

The system should generate hypotheses and structured questions. A researcher or clinician must review them before they are presented as a development plan.

### 3. Collaboration layer

Represent organizations, laboratories, clinicians, patient groups, platform owners, and study teams as permissioned profiles. Prefer:

- public institutional contact points;
- a “request introduction” workflow;
- expertise, disease areas, methods, data or sample capabilities, and geography;
- a record of consent and the purpose of a requested introduction.

Do not publish private email addresses, patient contact details, or unverified claims of expertise. Store the request and the response status rather than creating an open contact dump.

### 4. Patient and caregiver layer

Patients should be able to contribute priorities, structured outcomes, and optional longitudinal updates. They should be able to see what was collected, why it is useful, who can access it, and how to withdraw or change sharing preferences.

For rare diseases, a dynamic-consent or re-consent workflow is more appropriate than a one-time upload. Consent should separately cover voice recording, transcription, research reuse, re-contact, data linkage, sharing with industry, and publication.

## Patient interview concept

An interview assistant could reduce the burden of collecting patient experience and natural-history information. It should be treated as a data-collection interface, not as a clinical decision-maker.

Recommended flow:

```text
consent -> guided interview -> transcription -> redaction -> human review
        -> structured patient-reported outcomes -> research registry/graph
```

Use a fixed question bank for the core data and an open-ended section for patient priorities. Store the structured answer, a provenance link to the transcript segment, and an uncertainty flag. Do not rely on an unreviewed summary as the research record.

### ElevenLabs boundary

ElevenLabs can be considered for the conversational voice interface, but it should not be the default repository for identifiable health interviews. Voice can be personal or biometric data, and an interview can contain genetic, health, and family information.

If ElevenLabs is used in a pilot:

1. Obtain explicit consent for recording, transcription, third-party processing, and research reuse.
2. Do not use voice cloning or a public voice library for patient data.
3. Configure the shortest practical retention, disable audio saving where possible, and verify the applicable data-processing agreement and regional terms.
4. Send the minimum necessary content; avoid names, addresses, dates of birth, and exact locations in the audio sent to the service.
5. Treat automated redaction as a first pass only. A human must review transcripts and redaction before research use.
6. Keep the research identifier and consent ledger in the project-controlled system, separate from the audio provider.
7. Obtain IRB/REC and data-protection review before recruiting real patients.

For the first prototype, use synthetic interviews or typed responses. A self-hosted or institution-approved speech-to-text system is preferable for identifiable research data until the governance path is clear.

## When there are only one or two known cases

The platform should switch from a population dashboard to a case-coordination workflow:

1. Confirm the molecular and clinical definition with the treating team and a qualified rare-disease center.
2. Create a coded longitudinal record with explicit consent for re-contact and international matching.
3. Capture genotype, phenotype, laboratory results, imaging, treatment history, patient priorities, and time-stamped outcomes using a common schema.
4. Search for phenocopies and mechanistically related cases using phenotype, gene, protein, pathway, and variant evidence. Do not silently merge different diagnoses.
5. Track biospecimen availability and functional-assay opportunities separately from the public graph.
6. Discuss individualized-therapy, compassionate-use, or expanded-access options with the relevant clinical and regulatory experts. Do not present a platform-generated candidate as a treatment recommendation.
7. Use within-person longitudinal comparisons and carefully justified external controls when appropriate. Two cases are not enough to make a general efficacy claim.

The rarity itself increases re-identification risk. Do not show exact patient counts, dates, locations, or distinctive combinations in public search results unless the participant has explicitly authorized that disclosure. Use a permissioned matching service and notify the participant before sharing contact information.

## UI for the ecosystem

The first user-facing release should have:

- a disease research brief;
- a small evidence-backed graph around the selected disease;
- a target and protein-similarity panel;
- a natural-history and patient-priorities panel;
- a collaborator directory with request-introduction actions;
- an audit/evidence drawer showing source, date, method, and uncertainty.

Do not start with a full graph canvas. Start with a disease page and let users expand one or two hops. The graph is a way to explain a result, not the whole product.

## Suggested staged plan

### Phase 1: research navigation

- finish the disease page and evidence drawer;
- expose read-only Neo4j API endpoints;
- add protein mapping and baseline similarity;
- add organization and study profiles with public contact links.

### Phase 2: collaboration

- add researcher and patient-organization profiles;
- add permissioned introduction requests;
- add R&D brief generation with citations and human review;
- add a consent ledger for re-contact and data sharing.

### Phase 3: patient data pilot

- use synthetic or typed interview data first;
- validate the question bank with a patient organization and a research team;
- obtain ethics and data-protection approvals;
- pilot a small, longitudinal, consented natural-history workflow;
- add voice only after retention, transcription, and deletion behavior has been tested.

## Success criteria

The ecosystem is useful when a researcher can:

1. start from a disease or gene;
2. see the supporting evidence and uncertainty;
3. find a plausible target, biomarker, or study lead;
4. understand which patient-reported data would reduce uncertainty;
5. request an introduction without exposing private contact information;
6. reproduce the source data and see when each claim was last refreshed.

