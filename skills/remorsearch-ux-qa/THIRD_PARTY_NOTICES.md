# Third-party notices

Remorsearch UX QA is released under the MIT License (`LICENSE`). This file lists
material from other projects that is included in this folder, and projects that
were studied or can be used alongside it without any of their code being included.

## Included material

### Insane Search toolkit

The original insane-search entrypoint and twelve references are included under
`references/insane-search/`. The entrypoint is renamed `SOURCE.md` with unchanged
bytes, so Remorsearch remains the one discoverable skill. Research loads the
toolkit during acquisition, after candidate URL discovery and before capture.
Selected methods and outputs follow Remorsearch's access, privacy and evidence
controls; unsupported output remains a lead.

Attributed source: https://github.com/fivetaku/insane-search, fivetaku, 2026.
`references/insane-search/PROVENANCE.json` records original file hashes and the
snapshot date. The installed input omitted its license; the upstream MIT notice
retrieved on 2026-10-02 is retained verbatim as
`references/insane-search/upstream-LICENSE`. These records identify the attributed
snapshot and do not prove a current upstream comparison or assign the upstream
license to unrelated maintainer input. Release overrides preserve supplied
license files and record whether their bytes match the attributed snapshot.

The public-page reader also drew ideas from this project: official routes first,
graded response verdicts, honest untried-route reporting, redirect SSRF checks
and an untrusted-content envelope. Its runtime implementation is Remorsearch's
own; bundled reference instructions do not change its supported capture formats.

### Colour vision deficiency matrices (colour-science)

`ergoqa/hf/machado_data.py` contains the colour vision deficiency simulation
matrices of Machado, Oliveira and Fernandes, tabulated per severity, transcribed
from the colour-science package (`colour/blindness/datasets/machado2010.py`).

- Source model: Machado, G. M., Oliveira, M. M. and Fernandes, L. A. F. (2009).
  "A Physiologically-based Model for Simulation of Color Vision Deficiency".
  IEEE Transactions on Visualization and Computer Graphics 15(6), 1291-1298.
- Transcribed from: colour-science, https://github.com/colour-science/colour

```text
BSD 3-Clause License

Copyright 2013 Colour Developers

Redistribution and use in source and binary forms, with or without
modification, are permitted provided that the following conditions are met:

1. Redistributions of source code must retain the above copyright notice, this
   list of conditions and the following disclaimer.

2. Redistributions in binary form must reproduce the above copyright notice,
   this list of conditions and the following disclaimer in the documentation
   and/or other materials provided with the distribution.

3. Neither the name of the copyright holder nor the names of its
   contributors may be used to endorse or promote products derived from
   this software without specific prior written permission.

THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
```

## Installed separately by the user (not included)

- **Playwright** (Apache License 2.0) and its Chromium build, installed with
  `npm install` in `drivers/web/` for the live web driver.
- **Aside** (optional browser research tool), installed and licensed by its own
  distributor.
- Other browser tools that an agent host provides, such as Claude in Chrome,
  Playwright MCP or Chrome DevTools MCP, are used through the host. They are not
  part of this folder.

## Studied as references only (no code included)

- **MiroFish** (github.com/666ghj/MiroFish, AGPL-3.0): the ergonomics mode borrows
  the structure of seed → personas → parallel agents → report → interviews. No
  MiroFish code is used.
- **OASIS** (camel-ai/oasis, Apache-2.0): the social simulation engine under
  MiroFish; reviewed, not used.
- **OMO** (sisyphuslabs/omo): its goal, checkpoint and continuation design was
  inspected for the loop mode; no OMO code or installation is redistributed.
- **Nemotron-Personas-Korea** (NVIDIA, CC BY 4.0): persona records may be linked
  at run time by the user; no dataset rows are included in this folder.
- **insane-research** (github.com/fivetaku/insane-research, MIT License, Copyright
  (c) 2026 fivetaku). Ideas used in `references/research/audience-pipeline.md` and
  `references/research/source-grading.md`: phase contracts; claim status computed
  by a gate with a data-flow lock; independence counting; the EXPAND lead loop;
  schema-forced reader returns merged by code; and a report gate with an annex. We
  changed its grading, so grades depend on the claim kind, and its unit of
  independence, so people count and not only organisations.
- **K-skill** (github.com/NomaDamas/k-skill, MIT License at the repository root;
  its AGPL-3.0-only proxy packages were not used). Studied from 2026-09-28 to
  2026-09-30. Ideas used in the Korean research pack
  (`references/research/korea/`), in the reader's key handling (`uxresearch/`) and
  in the README:
  - a dated per-source registry: the official surface, the route, the
    authentication, the licence and the date it was observed;
  - the missing-credential rule: a missing key is recorded as a gap and a question
    to the user, and the reader never switches to another route;
  - namespaced key names, here `REMORSEARCH_<SERVICE>_<ITEM>`;
  - provenance cards for official statistics: publisher, table, reference period,
    unit, address and retrieval date;
  - the staged order for retrieving statistics from KOSIS: find the table, read
    its metadata, pull a small slice, then widen (from its kosis-stats skill);
  - a detect-only mode and a review threshold at a 30% change ratio for the
    Korean prose check (from its korean-humanizer document, which credits
    github.com/epoko77-ai/im-not-ai, MIT License; that project's README was read
    on 2026-09-30);
  - a capability table with a requirements column in the README;
  - "Done when" and "Failure modes" sections in each reference, and natural Korean
    requests as triggers.

  We deliberately did not adopt its hosted proxy with operator-held keys,
  instructions loaded at run time, reading of search-result pages or undocumented
  endpoints.
- **DaleSeo/korean-skills** (github.com/DaleSeo/korean-skills, MIT License).
  Ideas: the register follows the document type, and translationese patterns (for
  example ~에 대해, ~를 통해) form a lint category. The pattern list in
  `references/research/korea/report-template.md` is our own.
- **SoDam-Persona-Codex** (github.com/sodam-ai/SoDam-Persona-Codex, Apache License
  2.0). Ideas: Korean cue words that change how deep a run goes, and the 미확인
  label for statements that were not verified.
- **gptaku_plugins** (github.com/fivetaku/gptaku_plugins, MIT License; the
  collection that also holds insane-search and insane-research). Idea: the
  bilingual README pattern, an English README, a README.ko.md with the same section
  skeleton, and a language switcher line at the top.

The projects in this reference-only section supplied ideas; none of their code,
text, marker lists, word lists or tables is included. Bundled material is listed
separately under Included material.

## Cited or read for facts

Nothing is reproduced from the material in this section except the short KWCAG
clause sentences named below, quoted with attribution.

- Research papers, standards and guidelines cited in the references (for example
  WCAG 2.2, ISO 9241, RFC 9309, the TDM Reservation Protocol and human-factors
  studies) are cited, not reproduced.
- The Korean pack (`references/research/korea/`,
  `references/persona-qa/kwcag-2.2.md`) cites KWCAG 2.2 (KS X OT0003 R3, amended 2022-12-28), the
  Korea Fair Trade Commission's guidelines on endorsements and testimonials,
  guides of the Personal Information Protection Commission, official statistics
  and surveys, and statutes, administrative rules and judgments as read in the
  public legalize-kr mirrors (github.com/legalize-kr). Each is cited with its
  version or date, and marked 미확인 where it was not compared with the primary
  source. The primary-source updates read on 2026-09-30/2026-10-01 cite the
  [RRA standard and official attachment](https://www.rra.go.kr/ko/reference/kcsList_view.do?nb_seq=5247&nb_type=6),
  [NIA amendment announcement](https://www.nia.or.kr/site/nia_kor/ex/bbs/View.do?bcIdx=25083&cbIdx=90549),
  [FTC ordinance attachment](https://www.ftc.go.kr/www/downloadBbsFile.do?atchmnflNo=53785),
  [FTC monitoring results](https://www.ftc.go.kr/www/selectBbsNttView.do?key=12&bordCd=3&nttSn=45909),
  [FTC Q&A release](https://www.korea.kr/briefing/pressReleaseView.do?newsId=156732583),
  [NIA digital-divide report](https://www.nia.or.kr/site/nia_kor/ex/bbs/View.do?cbIdx=81623&bcIdx=29168),
  [NIA internet-usage report](https://www.nia.or.kr/site/nia_kor/ex/bbs/View.do?cbIdx=99870&bcIdx=29198),
  [KCA kiosk report](https://www.kca.go.kr/home/sub.do?menukey=4002&mode=view&no=1003409020),
  [KCA delivery-platform report](https://www.kca.go.kr/home/sub.do?menukey=4002&mode=view&no=1003708987),
  [Naver's cafe notice](https://notice.naver.com/notices/cafe/33743),
  [law.go.kr judgments](https://www.law.go.kr/판례/(2021도1533)) and operator
  terms/robots documentation cited at each fact. Read facts are marked 관찰됨;
  unreached facts retain 미확인. `verified_at` remains null until a person reads
  the primary page. None of it is legal advice.
- Field names, limits and error codes of the KOSIS OpenAPI were read in three
  third-party documents (github.com/WooilJeong/PublicDataReader,
  github.com/rubatoyd/kosis-openapi-mcp and github.com/seokhoonj/pykosis). No
  text or code from them is included.
- Seven more repositories are cited for facts by the shipped Korean documents,
  each named where it is used, with no code included:
  github.com/a11ykr/docs (the unofficial KWCAG 2.2 edition retained for the
  detailed comparison excerpts not rechecked in the primary-source inputs;
  standard metadata and item numbers now cite the RRA original),
  github.com/lak2211-columbia/project-babel (text extractions of two Personal
  Information Protection Commission guides, cited in
  `references/research/korea/legal-checklist.md`),
  github.com/naver/naver-openapi-guide (Naver API terms and migration notes,
  cited in the platform map and the platform data),
  github.com/daumPostcode/QnA (the Daum postcode widget's README and patch
  notes), github.com/Mode1221/CoursePilot and
  github.com/EST-team-project/Qurious (a pull request and an issue thread used
  as observed evidence in the platform map), and
  github.com/Yu-billie/KoCoSa_sarcasm_detection (the KoCoSa paper's
  repository, read for its title, authors and venue in
  `references/research/korea/query-craft.md`). No licence for any of these
  repositories is claimed here: only their public pages were read.
- Platform, agency and company names in the Korean pack are descriptive. There is
  no affiliation with any of them.
