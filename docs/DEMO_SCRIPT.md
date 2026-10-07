# 1-minute walkthrough script

This walkthrough follows a family or patient group to either a justified collaboration and next step, or an honest gap with a plan. It does both in 60 seconds. Every click below was tested on the current build.

**Persona:** Maria leads a patient group for **GM1 gangliosidosis**. There is no approved treatment.

## Before recording

- Start the server from the Git Bash window where your OpenAI key works: `python api/server.py`. It should print `Chat: on`.
- Open http://127.0.0.1:8000/explore.html, set the browser zoom to 110%, and reload once so the conversation starts fresh.
- Have the two typed inputs ready: `GM1` and `Bardet-Biedl syndrome 1`.
- Record at 1440 × 900 or larger, so the map panel shows on the right.

## Shot list

| Time | On screen | Voice-over |
| --- | --- | --- |
| 0:00–0:06 | The opening question: "Which rare disease is your family facing?" | "Maria's son has GM1 gangliosidosis. There's no treatment, and she doesn't know who else is working on it." |
| 0:06–0:14 | Type **GM1** and press Enter. The answer card appears with the map on the right. | "She types the name. RarePath shows the three closest communities and one next step." |
| 0:14–0:24 | Click **GM2 gangliosidosis**. The evidence panel opens; scroll briefly over the sources. | "GM2 is a strong link: their genes act in the same breakdown process, the children share a cherry-red spot in the eye, and both are already in the same studies. Every line has a source." |
| 0:24–0:30 | Close it. Click **6 more communities**, then **Niemann-Pick disease, type C1** ("needs review"). | "Not every link is a match. Niemann-Pick C1 is another lysosomal disease with similar signs but no shared process, so RarePath marks it as a lead to check." |
| 0:30–0:37 | Click **4 existing studies**. Point at PRONTO and the GM1 and GM2 tags. | "Work already exists. PRONTO, a study of children with GM1 and GM2, ran for three and a half years and has finished collecting data." |
| 0:37–0:46 | Click **See the plan**. Scroll from the checklist to the draft email, then click **Copy message**. | "Her next step: talk to NTSAD, the GM2 community, about comparing that data instead of building a new study. RarePath lists what an expert must check, and drafts the email." |
| 0:46–0:53 | Close the panel. Type **Bardet-Biedl syndrome 1**. Point at the red line: **Prader-Willi syndrome**. | "And when two diseases only look alike, it says so. Prader-Willi shares obesity with Bardet-Biedl, but not the biology." |
| 0:53–0:60 | Cut to the case study's 10× line. | "Reusing an existing study instead of starting one could turn about four years into about four months. That's the hypothesis to test next. RarePath: from a diagnosis to a shared next step." |

## Optional beats (+10 s each)

Before Bardet-Biedl syndrome, type **Can we use PRONTO data for our children?** The answer cites its sources as numbered markers; click one to show the record behind it. This shows the OpenAI-built part.

At the end, type **Alexander disease**: RarePath says it can't find it, lists what it searched and suggests what to try next (the honest gap).

## Longer walkthrough (about 2 minutes)

1. **The problem (20 s).** Most rare genetic diseases have no approved treatment, so families end up organising research themselves.
2. **What RarePath does (40 s).** The demo journey above, in fast forward.
3. **Why it can be trusted (30 s).** Every link has a source and a label (from a database, or computed). All 23 known-biology checks pass, including 12 written before the data was scored. The chat answers only from cited facts.
4. **10× and what's next (30 s).** The months-instead-of-years case, the assumptions to check with patient groups, and how the panel grows by adding one OMIM number.
