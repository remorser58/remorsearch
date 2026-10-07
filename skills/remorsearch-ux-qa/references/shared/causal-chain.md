# Causal chain

Use this card for each priority research issue and every P0/P1 product finding. Link the claim, observation, run and finding IDs for each supported layer. Research can finish with a cause hypothesis and next evidence; unknown organizational constraints remain unknown.

## 1. Required chain

| Layer | Record |
| --- | --- |
| Situation / symptom | Task, context and visible UI or scrubbed source statement |
| Direct friction | What cannot be found, understood, operated or recovered |
| Product or service mechanism | State, persistence, data, ranking, permission, policy or implementation behavior |
| Organizational / business constraint | Ownership, cost, regulation or incentive only when evidenced; otherwise unknown |
| Immediate behavior change | Repeat, wait, abandon, seek help or unsafe assumption; observed or inferred |
| User outcome | Task integrity, effort, safety, confidence, trust or accessibility |
| Product outcome | Possible errors, support cost, retention or conversion; conditional without measurements |
| Remediation hypothesis | Smallest useful change at the deepest confirmed layer within scope |
| Trade-off | Cost, displaced work, freshness or new risk |
| Validation | Same-scenario replay and evidence that could disprove the proposed cause |

Mark every causal link verified or inferred and every statement observed, inferred or unknown. A post verifies that an experience was reported; it does not verify the product mechanism. UI preference stays a hypothesis. Separate loss of state, service policy and visual hierarchy before choosing a fix.

## 2. Example: input disappears

Situation (observed, RUN-1): after entering the delivery note and returning from an address error, the field is empty; capture quotes its label and error.

Friction (observed): the entered note does not reach the final order. Mechanism (inferred): rerender may recreate state from defaults; inspect code only during an authorized technical pass. Organizational constraint: unknown. Behavior change: repeat input if noticed (inferred). User outcome: task corruption (observed); downstream safety harm depends on what the note contained (inferred). Product outcome: support or fulfilment errors may rise; no rate was measured.

Hypothesis: preserve the form model through validation, back and return. Trade-off: stale values need explicit reset and review. Validation: check every entered field after every transition and compare final payload/state on the same fixture, plus adjacent recovery states. A confirmed different trigger changes the mechanism claim.

## 3. Questions before a proposal

What state, information, ordering, permission or recovery is missing? Does the service rule cause the friction? Which new/expert contexts were tested? Does the proposed fix remove work or move it? What would disprove the cause? Record a concrete validation task and measure benefit before claiming conversion, retention or satisfaction improved.
