# Swarm and Social Layer

## MiroFish in one paragraph

MiroFish (666ghj/MiroFish, first release 2025-12-22, GitHub global trending #1
around 2026-03-07, AGPL-3.0, backed by Shanda) chains: seed text → GraphRAG
knowledge graph in Zep → LLM-written personas (age, gender, MBTI, bio, memories;
invented, not sampled) → parallel Twitter-like and Reddit-like simulations on
CAMEL-AI OASIS (Apache-2.0, arXiv 2411.11581) → a ReportAgent → chats with
individual agents. It publishes no validation of its predictions; its own report
prompt calls the simulation "a rehearsal of the future", and simulated posts are
written back into the same graph as source facts. OASIS agents herd more than
humans, and more so as agent counts grow. The same author's earlier BettaFish
(微舆, viral November 2025, GPL-2.0) is public-opinion analysis of real
platforms, not persona simulation. Full notes:
`docs/human-factors/llm-persona-simulation-validity.md` and
`docs/mirofish-reference-review.md`.
These are repository documents, not installed with the skill.

## What the swarm is here

A swarm is N ergonomic profiles × M devices × K scenarios, each operating the
real surface (or analysed on a shared recording), with deterministic models and
a differential aggregation:

```
scenario + surface ──► profiles (stratified coverage, assumptions listed)
        │
        ├─► scripted run per device/orientation ──► analysed under every profile on that device
        └─► interactive persona runs (LLM agents) ──► notes (judgment)
                          │
                          ▼
            ergo_qa.py swarm  ──►  findings with differential conditions
                          │           (e.g. grip=one_hand_left, vision.cvd=deutan)
                          ▼
            report agent (cites IDs only) ──► report.md, bundle.json
```

The differential condition is the useful output: "fails only for left one-hand
grips on 6.1"+ phones" is actionable and testable with real users; "7 of 16
agents failed" is not a population statement and is never presented as one.

## Report agent rules

- Cite only run, snapshot, observation and finding IDs; add no new facts.
- Tag every sentence with its evidence type (measured / model / judgment /
  simulated discourse).
- State conditions, not frequencies. No percentages, confidence intervals,
  sentiment scores or population weighting.
- List untested groups next to every finding that depends on a profile.
- Lint the text for prediction framing ("users will", "예측", "대부분의 사용자")
  and rewrite it as a hypothesis.

## Optional experience board (MiroFish-style social layer)

Purpose: surface disagreements between profiles and generate hypotheses and
Aside search queries. Not a forecast of real reactions.

1. After runs, each persona agent posts at most three short notes. Each note must
   cite at least one of its own observation IDs; notes without a citation are
   dropped.
2. Other agents may reply only with their own evidence ("EP-07 (right one-hand)
   reached it in natural zone: OB-…"), never with opinions about users in
   general.
3. The board is stored separately from evidence (`report/board.json`), never
   written back into findings, and every item text starts with
   「[시뮬레이션 · 합성 담론 · 실제 사용자 발화 아님]」.
4. The report agent extracts argument types and risk hypotheses, each with a way
   to verify it with real users or with research mode queries
   (for example `[서비스] 왼손 불편`, `[서비스] 버튼 안 닿음`).
5. No numbers come out of the board (no share of voice, no sentiment %).

## Swarm size and sensitivity

- Start with the coverage plan (per device: its grips, then 7 condition strata;
  pointer devices skip the 3 touch-only ones). 14 profiles on a phone and 7 on a
  desktop cover every stratum that applies to the device once.
- Report sensitivity: how findings change with a second device class, a second
  agent model, or with/without cross-profile analysis. A finding that appears
  only under one setting is labelled as such.
- More agents from the same model add coverage of choices, not independent
  evidence.
