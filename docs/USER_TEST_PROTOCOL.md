# User test protocol

**The question this test answers:** can someone new to RarePath start from a disease search, understand one research link, see the protein evidence, recognise a counterexample, and end with a next step they trust?

The test checks the three misreadings that would make RarePath harmful if they went unnoticed:

1. **A research link is not a treatment claim.** "GM1 and GM2 are related" means they could be studied together, not that a GM2 therapy will work for GM1.
2. **A look-alike is not a recommended partner.** Prader-Willi and Bardet-Biedl 1 share signs, but RarePath advises against treating them as one community.
3. **"Not evaluated" is not "different".** When too little of two proteins' sequences align, RarePath does not compare their shapes. That is a missing measurement, not evidence that the shapes differ.

## Participants

One session with each of these, at least:

| Group | Why | Watch especially |
| --- | --- | --- |
| A family member, or someone from a patient organisation | RarePath's main audience | Misreading 1, and whether they trust the next step |
| A biomedical researcher | Can judge whether the evidence is described correctly | Misreading 3, and whether the method details convince them |
| A reviewer new to the project (for example a hiring manager or a designer) | Sees it the way a portfolio visitor will | Whether the story is clear without help |

Five people in total finds most usability problems. Add more family participants first.

## Before each session

- Run `python pipelines/freeze_candidate.py --check`. Write the candidate name and graph version in the session log.
- Use **static mode**, so every participant sees offline answers built from the same facts. Send the hosted link (https://huijiaoluo.github.io/RarePath/explore.html), or open `demo/explore.html` locally; check that the page footer shows the candidate's graph version. Use API mode only if testing the AI answers is the point of the session.
- Clear the browser's site data, so "Recently viewed" starts empty.
- Say: *"I'm testing the tool, not you. Please think aloud. I won't help during the tasks; afterwards I'll answer anything."*
- Say: *"Please don't type your own family's names or medical details."* Do not record the screen if any personal health information appears; stop and restart the task instead.

## Tasks

Read each task aloud and give it on a card. Time it. Note where the participant hesitates, what they click first, and anything they say about trusting the result. Do not prompt.

**Task 1. From GM1 to GM2.** "Your child has been diagnosed with GM1 gangliosidosis. Find which other disease community is closest, and tell me why RarePath thinks so."

- Success: finds GM2 gangliosidosis, opens "Why we think so", and names at least one reason (the shared breakdown process, a shared sign such as the cherry-red spot, or a shared study).
- Then ask: *"If a treatment helped children with GM2, what would this tell you about GM1?"* (misreading 1)

**Task 2. Existing work and a next step.** "Find one study that already exists, and one concrete thing you could do this week."

- Success: names PRONTO (NCT05109793), or another listed study, and opens "See the plan".
- Then ask: *"What would you need to check before contacting them?"* Look for: whether the study is still running, eligibility and age ranges, consent for sharing data.

**Task 3. A look-alike.** "Now look at Bardet-Biedl syndrome 1. RarePath mentions Prader-Willi syndrome. Should these two communities work together? Why or why not?"

- Success: says they look similar but RarePath marks the biology as different, and does not recommend them as partners.
- Then ask: *"What does 'look similar, but different biology' mean to you?"* (misreading 2)

**Task 4. Protein and variants.** "Open the gene behind Tay-Sachs disease. Tell me what you learn about its protein, and how it compares with other proteins."

- Success: opens HEXA; says HEXA and HEXB are closely related (similar sequence and nearly the same predicted shape); describes the coloured dots as disease-causing variants reported in ClinVar.
- Then ask: *"What does 'not evaluated' mean for HEXA and GLB1?"* (misreading 3)
- Then ask: *"Do the dots show how common each variant is?"* (They do not: they show where ClinVar records cluster.)

## After the tasks

Ask in this order, before explaining anything:

1. *"In one sentence, what is RarePath for?"*
2. *"Which part did you trust most, and which least? Why?"*
3. *"Was anything said more strongly than the evidence allowed?"*
4. *"Would you use the next step it suggested? What would stop you?"*
5. On a scale of 1 to 5: *"How confident are you that you could explain the GM1–GM2 link to someone else?"*

## Record sheet

One row per participant. Keep notes free of names and health details: use P1, P2, and so on.

| Field | Values |
| --- | --- |
| Participant, group | P1, family / researcher / reviewer |
| Candidate, graph version, mode | e.g. demo-candidate-1, g…, static |
| Task 1–4: success, time, notes | yes / partial / no; minutes; what happened |
| Misreading 1 (link ≠ treatment) | understood / misread / unclear |
| Misreading 2 (look-alike ≠ partner) | understood / misread / unclear |
| Misreading 3 (not evaluated ≠ different) | understood / misread / unclear |
| Variant dots (records, not frequency) | understood / misread / unclear |
| One-sentence purpose | their words |
| Trust most / least | their words |
| Overclaims noticed | their words |
| Confidence 1–5 | |
| Changes to make | each with the screen it applies to |

## Deciding what to change

- A misreading by **any** family participant is a priority: change the wording on that screen, then re-test that task with a new participant.
- A task that two participants fail is a design problem, not a participant problem.
- Every change goes into the CHANGELOG with the session it came from. A change to data or wording that the graph contains changes the graph version, so freeze a new candidate before the next session.
