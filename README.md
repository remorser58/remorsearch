# Remorsearch UX QA

English | [한국어](README.ko.md)

Remorsearch UX QA is an agent skill for Claude Code and Codex. Use it to improve the UX of an existing product.

Give the agent a URL or a repository, and ask for an improvement. The agent then does these steps:

1. It examines the product and the decisions of the developers.
2. It does baseline QA to find questions.
3. It researches the experiences of related users.
4. It applies scoped fixes that you can revert.
5. It replays the affected tasks to verify the fixes.

A problem list, a persona set or a research brief is optional.

## Components

The agent selects the components for each request. You do not select a mode. A research-only or review-only request does not change the product.

| Component | Function | Requirement |
| --- | --- | --- |
| **research** | Finds user experiences, workarounds and counterexamples in communities, reviews and official sources. Keeps the source context and the gaps. | A permitted source. For YouTube comments, your own YouTube Data API key. |
| **persona-qa** | Tests task completion, input preservation, error recovery, keyboard use and accessibility on the real product. Uses synthetic test conditions. | Access to the product and safe test data. The web driver needs Node.js 22 and Playwright. |
| **ergonomics** (experimental) | Screens reach, touch, perception, timing and layout with simulated profiles. | Applicable scenarios. |
| **loop** | Records scoped fixes. Replays the current build and checks for regressions and for changes to the intent. | The browser and Figma tools of the host agent. |

## Install

The Python tools need Python 3.10 or later on macOS, Linux or WSL. They use only the standard library.

1. Clone the repository.

   ```sh
   git clone https://github.com/remorser58/remorsearch.git
   ```

2. Copy the skill folder into the skills directory of your agent.

   Claude Code (personal):

   ```sh
   mkdir -p ~/.claude/skills
   cp -R remorsearch/skills/remorsearch-ux-qa ~/.claude/skills/
   ```

   To share the skill with a team, copy the folder into `.claude/skills/` in the project.

   Codex:

   ```sh
   mkdir -p ~/.codex/skills
   cp -R remorsearch/skills/remorsearch-ux-qa ~/.codex/skills/
   ```

3. Optional: install the live web driver. persona-qa and ergonomics use it on real web pages. Use Node.js 22.

   ```sh
   cd ~/.claude/skills/remorsearch-ux-qa/drivers/web
   npm ci && npx playwright install chromium
   ```

   For Codex, use `~/.codex/skills/remorsearch-ux-qa/drivers/web`.

## Use

Write the request in plain words, or call the skill by its name:

```
/remorsearch-ux-qa Improve our app UX. URL: https://app.example.test or repository: /path/to/product
/remorsearch-ux-qa 우리 앱 UX 개선해줘. URL 또는 저장소는 여기야.
/remorsearch-ux-qa Find out why people abandon our checkout, from reviews and community posts.
/remorsearch-ux-qa 결제 화면을 처음 쓰는 사용자 페르소나로 QA해 줘. Figma 파일은 이거야.
/remorsearch-ux-qa Check one-handed and colour-blind usability of the signup flow on a Galaxy S24.
```

The agent finds tasks, questions and scenarios in the product and in the project documents. It asks you only for access that it does not have, or for decisions that are not clear. It continues the other work while it waits.

## Evidence rules

- Each statement has one label: `observed`, `inferred` or `unknown`. Repetition does not change an inference into a fact.
- Synthetic personas and simulated profiles make test conditions only. They do not show the preference or the discomfort of real users.
- A community signal is a hypothesis until the agent confirms the behavior on the real product.
- A research or review request is read-only. An improvement request permits ordinary, reversible fixes in its scope. Deployment, publication and changes to real accounts need a separate permission.
- The agent makes screen and UX changes in Figma first. It records the file, the node and the version.
- An improvement is complete only after a replay on the current build, an adjacent regression check and an intent check.

Research and QA runs can share a machine-readable evidence bundle (`schemas/ux-evidence-bundle.v1.schema.json`). The offline validator checks IDs, cross-references, permission records and the misuse of synthetic personas. To try it with the sample bundle, run:

```sh
python3 ~/.claude/skills/remorsearch-ux-qa/scripts/validate_bundle.py ~/.claude/skills/remorsearch-ux-qa/examples/bundle/minimal.json
```

## Public sources

The research stage reads only pages that are public without an account.

- The agent uses the best browser tool of the host. The order is an agentic browser (Aside, Claude in Chrome, the built-in browser of the Claude app), an automation browser, then the reader in the skill. Results of plain web search are leads only.
- The reader stops at logins, paywalls, CAPTCHAs, bot blocks, robots.txt rules, AI or TDM opt-outs and rate limits. It records each stop as a coverage gap.
- The reader does not disguise itself. It reads one page at a time for each host, at an interval of 8 seconds or more.
- Before the agent reads the text, the reader removes phone numbers, email addresses, ID numbers, card and account numbers and IP addresses. Quotes are short. Author names become salted keys.
- The reader stops on hosts whose terms restrict automated collection or AI use. To read these hosts, you must record your terms check and the applicable written permission.

For more information, see [`public-page-access.md`](skills/remorsearch-ux-qa/references/research/public-page-access.md).

## Korean research

For a Korean product, Korean users or a report in Korean, the research stage also uses the Korean pack. The pack is in Korean. It starts at [`overview.md`](skills/remorsearch-ux-qa/references/research/korea/overview.md). It includes:

- a map of 27 Korean channels, with the access route, the expected stops and the terms status of each channel
- Korean query methods and user language (초성체, sarcasm, register)
- markers for disclosure and review rewards, and the grading rules for them
- a legal checklist (not legal advice) and a report template in Korean
- KWCAG 2.2 and WCAG 2.2 notes for persona-qa, in [`kwcag-2.2.md`](skills/remorsearch-ux-qa/references/persona-qa/kwcag-2.2.md)

YouTube comments come only through the YouTube Data API. Put your key in the environment variable `REMORSEARCH_YOUTUBE_API_KEY`. As the key holder, you must obey the YouTube API terms.

## Limits

- The host agent supplies the live browser, Figma and the builds. The loop CLI imports their records. It does not start them.
- The web driver uses Chromium device emulation. It does not test iOS Safari, native apps or real devices.
- The ergonomics mode is experimental. Use its results for screening, not for certification.
- Some sites stop the reader. These sites stay as coverage gaps.

## Repository layout

```
.claude-plugin/                plugin manifest
skills/remorsearch-ux-qa/      the skill (copy this folder)
  SKILL.md                     entry point: modes, shared rules, tools
  references/                  workflows and reference material
  scripts/                     CLIs: validate_bundle, ux_loop, ux_research, ergo_qa
  uxloop/ uxresearch/ ergoqa/  Python packages for the CLIs
  schemas/                     JSON schemas for the CLIs
  drivers/web/                 live Playwright driver (Node.js)
  examples/                    synthetic samples
README.md, README.ko.md        this page in English and in Korean
```

## License

MIT. See [`LICENSE`](LICENSE). Third-party material is in [`THIRD_PARTY_NOTICES.md`](skills/remorsearch-ux-qa/THIRD_PARTY_NOTICES.md).

## Credits

The public-page reader and the research gate use ideas from fivetaku's [insane-search](https://github.com/fivetaku/insane-search) and [insane-research](https://github.com/fivetaku/insane-research) (both MIT). The skill includes the original insane-search toolkit as reference material. Its bytes, provenance and upstream license stay unchanged. The research gate does not include code or text from insane-research.

The Korean pack and the bilingual layout of this README use ideas from [K-skill](https://github.com/NomaDamas/k-skill) (MIT), DaleSeo's [korean-skills](https://github.com/DaleSeo/korean-skills) (MIT), [SoDam-Persona-Codex](https://github.com/sodam-ai/SoDam-Persona-Codex) (Apache-2.0) and fivetaku's [gptaku_plugins](https://github.com/fivetaku/gptaku_plugins) (MIT). These are ideas only.

Platform names are descriptive. There is no affiliation with these platforms.
