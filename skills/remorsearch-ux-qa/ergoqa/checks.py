"""Ergonomic check catalog and per-snapshot evaluation.

Each check reads measured inputs from a snapshot/run (geometry, colour, timing)
and a profile, applies a model from ergoqa.hf, and emits observations
(docs/ergonomic-swarm-spec.md section 6). Checks never role-play a user.

Basis/epistemic mapping:
- ``measured`` -> ``observed``: the value is read from the surface and compared
  with a fixed standard threshold (e.g. WCAG contrast, 24 px target size).
- ``model`` -> ``inferred``: a published model predicts an outcome for a
  profile (reach difficulty, miss probability, gaze priority, reading time).
- ``judgment`` -> ``inferred``: an LLM persona's note or a human judgment.
"""

from __future__ import annotations

import math
import re
import unicodedata
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from . import params
from .hf import cognition, game, gaze, perception, pointing, reach
from .snapshot import is_number, validate_adaptation, validate_native_state

SEVERITY_ORDER = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}

# Reach-zone labels (thumb-reach-v3); shared with the swarm's derived advice.
ZONE_KO = {"out": "파지를 바꿔야 닿는", "stretch": "엄지를 크게 뻗어야 하는", "mild": "약간 불편한", "natural": "편한"}


@dataclass(frozen=True)
class CheckSpec:
    check_id: str
    category: str
    basis: str
    title_ko: str
    title_en: str
    refs: tuple[str, ...]
    applies_to: tuple[str, ...] = ("web", "android", "ios", "desktop", "game")
    fix_layer: str = "interaction"
    recommendation_ko: str = ""


CATALOG: dict[str, CheckSpec] = {}


def _register(spec: CheckSpec) -> CheckSpec:
    CATALOG[spec.check_id] = spec
    return spec


TI01 = _register(CheckSpec(
    "TI-01", "task", "measured", "명시한 과업 값과 화면 상태 불일치",
    "Authored task expectation differs from the observed state",
    (), ("web", "game"), "persistence",
    "오류 복구와 화면 전환에서 지정한 값·선택 상태를 유지하고 같은 조건으로 재검사하세요.",
))


RH01 = _register(CheckSpec(
    "RH-01", "reach", "model", "한 손 엄지 도달이 어려운 위치의 조작 대상",
    "Action target outside the comfortable thumb zone for this grip",
    ("REF-bergstrom2014", "REF-hoober2013"), ("web", "android", "ios", "game"), "interaction",
    "주요 조작을 파지 손 엄지의 편한 영역(화면 하단 중앙부)으로 옮기거나 하단 고정 바/대체 경로를 제공하세요. 좌우 대칭 배치 또는 손잡이 설정을 검토하세요.",
))
RH02 = _register(CheckSpec(
    "RH-02", "reach", "model", "편한 엄지 영역에 놓인 파괴적 동작",
    "Destructive action sits in the easiest thumb zone",
    ("REF-bergstrom2014", "REF-hoober2013"), ("web", "android", "ios"), "interaction",
    "삭제/탈퇴 같은 파괴적 동작은 편한 영역에서 빼고 확인 단계나 실행 취소를 두세요.",
))
PT01 = _register(CheckSpec(
    "PT-01", "pointing", "measured", "WCAG 2.5.8 최소 타깃 크기(24px) 미달",
    "Target smaller than WCAG 2.5.8 minimum without spacing exception",
    ("REF-wcag22-258",), fix_layer="accessibility",
    recommendation_ko="타깃을 최소 24×24 CSS px 이상(권장 44–48)으로 키우거나 주변 간격을 확보하세요.",
))
PT02 = _register(CheckSpec(
    "PT-02", "pointing", "measured", "터치 타깃 물리 크기가 플랫폼 권장치 미만",
    "Touch target physically smaller than platform guidance",
    ("REF-apple-hig-44pt", "REF-material-48dp", "REF-parhi2006"), ("web", "android", "ios", "game"), "visual",
    "터치 타깃을 44pt/48dp(약 7–9mm) 이상으로 키우세요.",
))
PT03 = _register(CheckSpec(
    "PT-03", "pointing", "model", "주요 동작 옆 파괴적 동작 오터치 위험",
    "Accidental activation risk: destructive action adjacent to a primary/path action",
    ("REF-bi-zhai2013", "REF-henze2011"), fix_layer="interaction",
    recommendation_ko="주요 동작과 파괴적 동작 사이 간격을 충분히 두고(최소 8mm 권장) 파괴적 동작에는 확인/실행 취소를 두세요.",
))
PT04 = _register(CheckSpec(
    "PT-04", "pointing", "model", "예측 오터치 확률이 높은 조작 대상",
    "High predicted touch-miss probability for this profile",
    ("REF-bi-zhai2013", "REF-henze2011", "REF-parhi2006"), ("web", "android", "ios", "game"), "visual",
    "타깃 크기와 간격을 키우고, 이동 중·손떨림 사용자를 위한 여유 영역(hit slop)을 두세요.",
))
PT05 = _register(CheckSpec(
    "PT-05", "pointing", "model", "연속 조작 간 포인팅 난이도(Fitts ID)가 높음",
    "High Fitts index of difficulty between consecutive steps",
    ("REF-fitts1954", "REF-mackenzie1992"), ("web", "desktop", "game"), "ia",
    "연속으로 누르는 조작을 가깝게 두고 타깃을 키우세요.",
))
GZ01 = _register(CheckSpec(
    "GZ-01", "gaze", "model", "주요 동작이 초기 시선 경로에 들어오지 않음",
    "Primary action unlikely to be among the first predicted fixations",
    ("REF-itti1998", "REF-ueyes2023", "REF-nngroup-f-pattern"), fix_layer="visual",
    recommendation_ko="주요 동작의 시각적 위계(크기·대비·위치)를 높이고 경쟁하는 강조 요소를 줄이세요.",
))
GZ02 = _register(CheckSpec(
    "GZ-02", "gaze", "model", "조작 지점에서 멀리 뜨는 피드백/오류 메시지(변화맹 위험)",
    "Feedback or error appears far from where the user just acted",
    ("REF-rensink1997", "REF-ball-ufov"), fix_layer="interaction",
    recommendation_ko="오류·상태 메시지를 조작한 위치 가까이(인라인) 표시하고, 필요하면 포커스를 이동하거나 라이브 영역으로 알리세요.",
))
GZ03 = _register(CheckSpec(
    "GZ-03", "gaze", "model", "중요 정보가 광고처럼 보이는 위치/형태(배너 블라인드니스)",
    "Critical information placed where users habitually ignore ads",
    ("REF-benway1998", "REF-nngroup-banner-blindness"), ("web", "desktop"), "visual",
    "중요 알림을 광고 영역 밖, 작업 흐름 안에 표시하고 광고와 다른 형태를 쓰세요.",
))
GZ04 = _register(CheckSpec(
    "GZ-04", "gaze", "model", "주요 동작보다 눈에 띄는 경쟁 요소가 많음",
    "Many elements out-compete the primary action for attention",
    ("REF-itti1998", "REF-ueyes2023"), fix_layer="visual",
    recommendation_ko="보조 요소의 강조를 낮추고 한 화면의 주요 동작을 하나로 모으세요.",
))
PC01 = _register(CheckSpec(
    "PC-01", "perception", "measured", "텍스트 명도 대비 부족(WCAG 1.4.3)",
    "Text contrast below WCAG 1.4.3",
    ("REF-wcag22-143",), fix_layer="visual",
    recommendation_ko="본문 4.5:1, 큰 글씨 3:1 이상으로 전경/배경 대비를 높이세요.",
))
PC02 = _register(CheckSpec(
    "PC-02", "perception", "measured", "UI 컴포넌트 경계 대비 부족(WCAG 1.4.11)",
    "Non-text contrast of component boundary below 3:1",
    ("REF-wcag22-1411",), fix_layer="visual",
    recommendation_ko="입력창 테두리·버튼 경계를 인접 색과 3:1 이상 대비로 만드세요.",
))
PC03 = _register(CheckSpec(
    "PC-03", "perception", "model", "색각이상에서 구분되지 않는 색상 전용 상태 구분",
    "Colour-only distinction collapses under simulated colour-vision deficiency",
    ("REF-machado2009", "REF-wcag22-141"), fix_layer="visual",
    recommendation_ko="색 외에 텍스트·아이콘·패턴으로 상태를 함께 표시하세요.",
))
PC04 = _register(CheckSpec(
    "PC-04", "perception", "model", "시청 거리 대비 글자가 너무 작음(노안/저시력 프로필)",
    "Text subtends too small a visual angle for this profile",
    ("REF-legge2007", "REF-kwcag22"), fix_layer="visual",
    recommendation_ko="본문 글자 크기를 키우고(모바일 16px 이상 권장) 시스템 글자 크기 확대를 지원하세요.",
))
PC05 = _register(CheckSpec(
    "PC-05", "perception", "model", "강한 햇빛 환경에서 대비 여유 부족",
    "Insufficient contrast margin for bright-light context",
    ("REF-wcag22-146",), ("web", "android", "ios", "game"), "visual",
    "야외 사용이 잦은 화면의 핵심 텍스트는 7:1 이상 대비를 권장합니다.",
))
CG01 = _register(CheckSpec(
    "CG-01", "cognition", "model", "동등한 선택지가 너무 많음(선택 과부하)",
    "Too many equally weighted choices on one decision screen",
    ("REF-hick1952", "REF-hyman1953"), fix_layer="ia",
    recommendation_ko="선택지를 묶거나 추천/기본값을 제시하고 단계적으로 공개하세요.",
))
CG02 = _register(CheckSpec(
    "CG-02", "cognition", "model", "읽기 전에 사라지는 일시 메시지",
    "Transient message disappears before it can be read",
    ("REF-wcag22-221",), fix_layer="content",
    recommendation_ko="토스트 표시 시간을 글자 수에 맞춰 늘리거나 사용자가 닫을 때까지 유지하세요.",
))
CG03 = _register(CheckSpec(
    "CG-03", "cognition", "measured", "조작 후 응답/피드백 지연",
    "Slow or missing feedback after an action",
    ("REF-miller1968", "REF-nielsen1993"), fix_layer="interaction",
    recommendation_ko="100ms 안에 눌림 피드백, 1초 이상 걸리면 진행 표시를 보여주세요.",
))
GM01 = _register(CheckSpec(
    "GM-01", "perception", "model", "HUD/자막 글자가 시청 거리 대비 작음",
    "HUD or subtitle text too small for viewing distance",
    ("REF-xag", "REF-gag"), ("game", "web", "android", "ios"), "visual",
    "HUD/자막 크기를 키우고 크기 조절 옵션을 제공하세요.",
))
GM02 = _register(CheckSpec(
    "GM-02", "reach", "model", "가로 두 엄지 파지에서 닿기 어려운 게임 조작부",
    "Game control hard to reach in landscape two-thumb grip",
    ("REF-bergstrom2014",), ("game", "web", "android", "ios"), "interaction",
    "자주 쓰는 조작부를 하단 좌우 엄지 영역에 두고 위치/크기 커스터마이즈를 제공하세요.",
))
GM03 = _register(CheckSpec(
    "GM-03", "game", "model", "반응 시간보다 짧은 입력 제한 시간(QTE)",
    "Timed input window shorter than the profile's reaction + motor + latency",
    ("REF-der-deary2006", "REF-xag", "REF-gag"), ("game", "web"), "service",
    "제한 시간을 늘리거나 끄는 옵션, 자동 성공 옵션을 제공하세요.",
))
GM04 = _register(CheckSpec(
    "GM-04", "game", "measured", "초당 3회 초과 섬광(광과민성 발작 위험)",
    "More than three flashes in one second over a large area",
    ("REF-wcag22-231", "REF-itu-bt1702"), ("game", "web", "android", "ios", "desktop"), "visual",
    "섬광 빈도를 초당 3회 이하로 낮추고 면적을 줄이세요. 방송·인증이 필요하면 Harding FPA 같은 인증 절차를 따로 밟으세요.",
))
GM05 = _register(CheckSpec(
    "GM-05", "game", "measured", "터치 게임 조작부가 작거나 화면 가장자리에 붙어 있음",
    "Touch game control below platform size or flush against the screen edge",
    ("REF-apple-hig-game-controls", "REF-parhi2006"), ("game", "web", "android", "ios"), "interaction",
    "가상 조이스틱·액션 버튼을 44pt(약 7mm) 이상, 연속 입력용은 9.6mm 이상으로 키우고 화면 가장자리·시스템 제스처 영역에서 떼어 두세요.",
))
GM06 = _register(CheckSpec(
    "GM-06", "game", "measured", "진행에 빠른 반복 입력(연타)이 필요함",
    "Progress requires rapid repeated presses (button mashing)",
    ("REF-xag", "REF-gag"), ("game", "web", "android", "ios"), "service",
    "연타 대신 길게 누르기/토글/자동 진행 옵션을 제공하고 입력 재매핑을 지원하세요.",
))
PT06 = _register(CheckSpec(
    "PT-06", "pointing", "measured", "파괴적 동작이 주요 동작에 간격 없이 붙어 있음(포인터)",
    "Destructive action placed against a primary/path action without separation (pointer devices)",
    ("REF-win32-touch", "REF-apple-hig-44pt"), ("web", "desktop"), "interaction",
    "파괴적 동작을 주요 동작과 떨어뜨리고(8px 이상, 권장 더 멀리) 확인/실행 취소를 두세요.",
))
SM01 = _register(CheckSpec(
    "SM-01", "semantics", "measured", "이름 없는 조작 요소(스크린리더·음성 제어로 식별 불가)",
    "Control without an accessible name",
    ("REF-wcag22-412", "REF-wcag22-244"), ("web", "desktop"), "accessibility",
    "아이콘 버튼·링크에 보이는 텍스트나 aria-label을 주세요.",
))
SM02 = _register(CheckSpec(
    "SM-02", "semantics", "measured", "보이는 레이블이 접근 가능한 이름에 없음(음성 제어 불일치)",
    "Visible label not contained in the accessible name",
    ("REF-wcag22-253",), ("web", "desktop"), "accessibility",
    "aria-label을 지우거나 보이는 문구로 시작하게 바꾸세요.",
))
SM03 = _register(CheckSpec(
    "SM-03", "semantics", "measured", "입력 칸에 프로그램적 레이블이 없음(placeholder만)",
    "Form field without a programmatic label",
    ("REF-wcag22-131", "REF-wcag22-332", "REF-wcag22-412"), ("web", "desktop"), "accessibility",
    "<label for> 또는 aria-labelledby로 보이는 레이블을 연결하고, placeholder를 레이블 대신 쓰지 마세요.",
))
SM07 = _register(CheckSpec(
    "SM-07", "semantics", "measured", "입력 칸 이름이 placeholder·title뿐(모범 사례)",
    "Form field named only by its placeholder or title (best practice)",
    ("REF-wcag22-332", "REF-nngroup-placeholders"), ("web", "desktop"), "accessibility",
    "보이는 <label>을 두고 연결하세요. placeholder는 입력하면 사라져 무엇을 적는 칸인지 잊게 됩니다.",
))
SM08 = _register(CheckSpec(
    "SM-08", "semantics", "measured", "과업이 누른 조작 요소에 역할이 없고 키보드로 갈 수 없음",
    "A control the task clicked has no role and cannot take keyboard focus",
    ("REF-wcag22-211", "REF-wcag22-412"), ("web", "desktop"), "accessibility",
    "<button>이나 <input type=radio|checkbox>를 쓰거나, role·tabindex=0·키보드 동작(Enter/Space)과 상태(aria-pressed, aria-checked)를 주세요.",
))
FM02 = _register(CheckSpec(
    "FM-02", "semantics", "measured", "대화상자·덮는 층이 열렸는데 키보드 초점이 그 안으로 가지 않음",
    "A dialog or covering layer opened but keyboard focus did not move into it",
    ("REF-wcag22-243", "REF-wcag22-412"), ("web", "desktop"), "accessibility",
    "층을 열면 그 안의 첫 조작 요소나 제목으로 초점을 옮기고(role=dialog, aria-modal=true), 닫으면 연 버튼으로 돌려보내세요.",
))
RF01 = _register(CheckSpec(
    "RF-01", "layout", "measured", "320 CSS px 폭에서 내용이 가로로 넘침(리플로)",
    "Content sticks out sideways at 320 CSS px (reflow)",
    ("REF-wcag22-1410",), ("web", "desktop"), "visual",
    "고정 폭(width: 400px 등)을 max-width: 100%와 줄바꿈되는 배치로 바꿔, 320 CSS px 폭(400 % 확대)에서 가로 스크롤 없이 읽히게 하세요.",
))
RF02 = _register(CheckSpec(
    "RF-02", "layout", "measured", "텍스트 간격 변경 뒤 글자가 잘림",
    "Text is clipped after the applicable spacing override",
    ("REF-wcag22-1412",), ("web", "desktop"), "visual",
    "텍스트 간격을 늘린 조건에서도 전문을 읽을 수 있도록 고정 높이와 잘림을 조정하세요.",
))
RF03 = _register(CheckSpec(
    "RF-03", "layout", "measured", "짧은 창에서 콘텐츠에 접근할 수 없음",
    "Content becomes unreachable in the shorter viewport experiment",
    (), ("web", "desktop"), "visual",
    "창 높이가 줄어도 주요 내용과 조작에 도달할 수 있도록 고정 영역과 스크롤 범위를 조정하세요.",
))
SM04 = _register(CheckSpec(
    "SM-04", "semantics", "measured", "오류 문구가 입력 칸과 떨어져 있고 연결되지 않음",
    "Error message neither next to nor linked to a field",
    ("REF-wcag22-331", "REF-wcag22-131", "REF-aria21"), ("web", "desktop"), "content",
    "오류 문구를 해당 칸 바로 아래에 두고 aria-describedby·aria-invalid로 연결하세요.",
))
SM05 = _register(CheckSpec(
    "SM-05", "semantics", "measured", "키보드 포커스가 보이지 않음",
    "Keyboard focus not visible",
    ("REF-wcag22-247",), ("web", "desktop"), "visual",
    "outline을 지우지 말고, 지웠다면 3:1 이상 대비의 포커스 표시(:focus-visible)를 주세요.",
))
SM06 = _register(CheckSpec(
    "SM-06", "semantics", "measured", "포커스된 요소가 고정 영역에 가려짐",
    "Focused element hidden behind a fixed or sticky layer",
    ("REF-wcag22-2411",), ("web", "desktop"), "visual",
    "고정 헤더·푸터 높이만큼 scroll-padding을 주거나 포커스 시 가리지 않게 배치하세요.",
))
LY01 = _register(CheckSpec(
    "LY-01", "layout", "measured", "상자에 잘린 텍스트",
    "Text clipped by its own box or a clipping container",
    ("REF-xctest-textclipped", "REF-wcag22-144", "REF-wcag22-1412"), ("web", "desktop"), "visual",
    "고정 높이·너비와 overflow:hidden을 풀어 글자가 늘어나도 다 보이게 하세요.",
))
PJ01 = _register(CheckSpec(
    "PJ-01", "heuristic", "judgment", "페르소나 에이전트가 기대와 다른 결과/혼란을 기록",
    "Persona agent recorded an expectation mismatch or confusion",
    ("REF-norman2013", "REF-nielsen1994"), fix_layer="interaction",
    recommendation_ko="해당 단계의 기대-결과 불일치를 실제 사용자 테스트로 확인하세요.",
))


@dataclass
class Observation:
    check_id: str
    run_id: str
    profile_id: str
    snapshot_id: str | None
    step_index: int | None
    element_ids: list[str]
    element_key: str
    measurement: dict[str, Any]
    passed: bool
    severity: str | None
    message_ko: str
    model: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self, index: int) -> dict[str, Any]:
        spec = CATALOG[self.check_id]
        basis = spec.basis
        return {
            "id": f"OB-{self.run_id}-{self.profile_id}-{index:04d}",
            "check_id": self.check_id,
            "category": spec.category,
            "run_id": self.run_id,
            "profile_id": self.profile_id,
            "snapshot_id": self.snapshot_id,
            "step_index": self.step_index,
            "element_ids": self.element_ids,
            "element_key": self.element_key,
            "basis": basis,
            "epistemic_status": "observed" if basis == "measured" else "inferred",
            "model": self.model,
            "measurement": self.measurement,
            "passed": self.passed,
            "severity": self.severity if not self.passed else None,
            "message_ko": self.message_ko,
            "message_en": spec.title_en,
            "refs": list(spec.refs),
            **({"extra": self.extra} if self.extra else {}),
        }


@dataclass
class Context:
    run: dict[str, Any]
    snapshot: dict[str, Any]
    previous: dict[str, Any] | None
    step: dict[str, Any] | None
    profile: dict[str, Any]
    device: Any
    scenario: dict[str, Any] | None
    conspicuity: list[list[float]] | None = None
    path_element_ids: set[str] = field(default_factory=set)
    # Elements the task tapped or clicked (a subset of the path; SM-08).
    clicked_element_ids: set[str] = field(default_factory=set)

    @property
    def elements(self) -> list[dict[str, Any]]:
        return [e for e in self.snapshot.get("elements", []) if isinstance(e, dict) and e.get("box")]

    @property
    def viewport(self) -> tuple[float, float]:
        vp = self.snapshot.get("device", {}).get("viewport_css") or [0, 0]
        return float(vp[0]), float(vp[1])

    @property
    def surface_kind(self) -> str:
        return self.snapshot.get("surface", {}).get("kind", "web")

    @property
    def is_touch(self) -> bool:
        return getattr(self.device, "input", "touch") == "touch"

    @property
    def attrs(self) -> dict[str, Any]:
        return self.profile.get("attributes", {})


def element_key(element: dict[str, Any]) -> str:
    selector = element.get("selector") or element.get("id") or "?"
    name = (element.get("name") or element.get("text") or "").strip().replace("\n", " ")[:40]
    return f"{selector}|{name}"


def _roles(element: dict[str, Any]) -> set[str]:
    return set(element.get("roles") or [])


def _usable(element: dict[str, Any]) -> bool:
    """Not covered by a sheet, scrim or overlay and not inert behind an open modal.

    Elements under a modal are evaluated in the snapshots where they are usable;
    judging them while covered produced wrong-state findings (adjudication 2026-09-28).
    """
    occluded = element.get("occluded_fraction")
    return not element.get("inert_by_modal") and not (isinstance(occluded, (int, float)) and occluded >= params.OCCLUDED_MIN_FRACTION)


def _visible(element: dict[str, Any]) -> bool:
    return bool(element.get("visible", True)) and element.get("in_viewport", True) is not False and _usable(element)


def _present(element: dict[str, Any]) -> bool:
    """Rendered (not hidden), whether or not it is inside the current viewport.

    Measured checks (contrast, target size) apply to the whole rendered page, as a
    standard accessibility scan does; position-dependent models (reach, gaze) use
    ``_visible``.
    """
    box = element.get("box") or {}
    return bool(element.get("visible", True)) and box.get("w", 0) > 0 and box.get("h", 0) > 0 and _usable(element)


def _box_mm(ctx: Context, box: dict[str, float]) -> tuple[float, float]:
    from .devices import css_px_to_mm
    return css_px_to_mm(ctx.device, box["w"], "x"), css_px_to_mm(ctx.device, box["h"], "y")


def _point_mm(ctx: Context, x: float, y: float) -> tuple[float, float]:
    from .devices import css_px_to_mm
    return css_px_to_mm(ctx.device, x, "x"), css_px_to_mm(ctx.device, y, "y")


def _display_mm(ctx: Context) -> tuple[float, float]:
    vw, vh = ctx.viewport
    return _point_mm(ctx, vw, vh)


# ---------------------------------------------------------------- reach

def _easiest_point(ctx: Context, box: dict[str, float], geom: Any, grip: str, thumb: float) -> tuple[float, float]:
    """Point (display mm) inside the target, inset from its edges, with the lowest reach difficulty."""
    x0, y0 = _point_mm(ctx, box["x"], box["y"])
    w_mm, h_mm = _box_mm(ctx, box)
    inset_x = min(params.REACH_TARGET_INSET_MM, w_mm / 2)
    inset_y = min(params.REACH_TARGET_INSET_MM, h_mm / 2)
    xs = [x0 + inset_x + (w_mm - 2 * inset_x) * f for f in (0.0, 0.25, 0.5, 0.75, 1.0)]
    ys = [y0 + inset_y + (h_mm - 2 * inset_y) * f for f in (0.0, 0.5, 1.0)]
    best = None
    for x in xs:
        for y in ys:
            d = reach.reach_score(x, y, geom, grip, thumb)["difficulty"]
            if best is None or d < best[0]:
                best = (d, (x, y))
    return best[1]


def check_reach(ctx: Context) -> list[Observation]:
    """Reach/grip checks (HGR-3/5/11). Model-only severities are capped at P2."""
    if not ctx.is_touch:
        return []
    grip = ctx.attrs.get("grip")
    orientation = ctx.snapshot.get("device", {}).get("orientation", "portrait")
    landscape_game = orientation == "landscape" and grip == "two_thumbs"
    if grip not in reach.SUPPORTED_GRIPS or grip.startswith("cradle"):
        return []
    out: list[Observation] = []
    geom = reach.geometry_for_device(ctx.device)
    if reach.tablet_like(geom) and grip.startswith("one_hand"):
        return []  # HGR-9: nobody operates a tablet with the holding thumb; the phone model does not apply
    thumb = float(ctx.attrs.get("thumb_length_mm") or params.THUMB_LENGTH_MM["all"][0])
    for element in ctx.elements:
        roles = _roles(element)
        is_game = "game_control" in roles
        on_path = element.get("id") in ctx.path_element_ids
        if not (element.get("interactive") or is_game) or not _visible(element):
            continue
        if not (roles & {"primary", "destructive", "game_control"} or on_path):
            continue
        cx, cy = pointing.centre(element["box"])
        pt = _point_mm(ctx, cx, cy)
        label = element.get("name") or element.get("text") or element.get("selector")
        base = (ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"))
        if not (landscape_game and is_game):
            # Users tap wherever the target is easiest to reach, so a full-width bottom
            # button is scored at its reachable end, not its centre (cross-review 2026-09-28).
            pt = _easiest_point(ctx, _target_box(element), geom, grip, thumb)
        if landscape_game and is_game:
            cost = reach.landscape_control_cost(pt[0], pt[1], geom, *params.LANDSCAPE_REST_INSET_MM)
            far = cost["travel_mm"] > params.LANDSCAPE_TRAVEL_MAX_MM
            # Apple HIG: frequent controls near the thumbs, secondary controls (pause, menus)
            # at the top. Only controls the play uses repeatedly are held to the thumb rule.
            # A scripted run's tap count reflects the script, not real play, so gameplay
            # controls are frequent unless they are secondary (pause, menu, settings).
            if _secondary_control(element) and "timed" not in roles:
                continue
            failed = cost["top_band"] or far
            severity = ("P2" if cost["top_band"] else "P3") if failed else None
            out.append(Observation(
                "GM-02", *base, [element["id"]], element_key(element),
                {"name": "thumb_travel_mm", "value": cost["travel_mm"], "unit": "mm", "threshold": params.LANDSCAPE_TRAVEL_MAX_MM, "comparator": "<=",
                 "top_band": cost["top_band"], "thumb": cost["thumb"]},
                not failed, severity,
                f"게임 조작 '{label}'은(는) {cost['thumb']} 엄지 휴지 위치에서 {cost['travel_mm']:.0f}mm"
                + (" 떨어진 상단 영역에 있습니다(자주 쓰는 조작은 엄지 근처, 상단은 보조 메뉴용: Apple HIG)." if cost["top_band"] else " 떨어져 있습니다."),
                "landscape-thumb-rest-v1",
                {"point_mm": [round(pt[0], 1), round(pt[1], 1)]},
            ))
            continue
        score = reach.reach_score(pt[0], pt[1], geom, grip, thumb)
        difficulty = score["difficulty"]
        extra = {"point_mm": [round(pt[0], 1), round(pt[1], 1)], "zone": score["zone"], "rho": score["rho"], "theta_deg": score["theta_deg"],
                 "screen_mm": [round(geom.screen_w, 1), round(geom.screen_h, 1)], "calibration": "uncalibrated"}
        if grip.startswith("one_hand"):
            extra["asymmetry_L_minus_R"] = round(reach.asymmetry(pt[0], pt[1], geom, thumb), 3)
        if "destructive" in roles and not on_path:
            # Risk of accidental activation matters when there is no confirmation or undo
            # (declared irreversible); a destructive link that opens a confirm dialog is fine.
            failed = score["zone"] == "natural" and not score["cramped"] and "irreversible" in roles
            out.append(Observation(
                "RH-02", *base, [element["id"]], element_key(element),
                {"name": "reach_difficulty", "value": difficulty, "unit": "0-1", "threshold": params.REACH_EASY_MAX, "comparator": ">"},
                not failed, "P3" if failed else None,
                f"파괴적 동작 '{label}'이(가) {grip} 파지에서 가장 편한 엄지 영역에 있습니다.",
                reach.MODEL_ID, extra,
            ))
            continue
        severity = None
        # Secondary game controls (pause, menu, settings) are occasional and belong at the
        # top by convention (Apple HIG), as in GM-02: out of reach is P3, a stretch is fine.
        secondary = is_game and "primary" not in roles and "timed" not in roles and _secondary_control(element)
        key_control = bool(roles & {"primary", "game_control"}) and not secondary
        if score["zone"] == "out":
            # Critical controls out of one-thumb reach: P2 (model cap). Other controls the
            # task happens to use (fields, tabs): P3, since reaching them is expected.
            severity = "P2" if key_control else "P3"
        elif score["zone"] == "stretch" and key_control:
            severity = "P2" if difficulty >= params.REACH_HARD else "P3"
        elif score["cramped"] and key_control and min(_box_mm(ctx, element["box"])) < params.TOUCH_TARGET_CORNER_MM:
            severity = "P3"
        zone_ko = ZONE_KO[score["zone"]]
        out.append(Observation(
            "RH-01", *base, [element["id"]], element_key(element),
            {"name": "reach_difficulty", "value": difficulty, "unit": "0-1", "threshold": params.REACH_HARD, "comparator": "<",
             "grip": grip, "zone": score["zone"]},
            severity is None, severity,
            f"'{label}'은(는) {grip} 파지·엄지 {thumb:.0f}mm 기준 {zone_ko} 위치입니다(난이도 {difficulty:.2f}"
            + (", 손바닥 가까운 좁은 영역" if score["cramped"] else "") + ").",
            reach.MODEL_ID, extra,
        ))
    return out


# ---------------------------------------------------------------- pointing

def _interactive(ctx: Context, whole_page: bool = False) -> list[dict[str, Any]]:
    present = _present if whole_page else _visible
    return [e for e in ctx.elements if (e.get("interactive") or "game_control" in _roles(e)) and present(e) and e.get("enabled", True)]


def _target_box(element: dict[str, Any]) -> dict[str, float]:
    """The largest region that accepts the element's click: its box or an associated <label>.

    A 20 px checkbox inside a 48 px label is a 48 px target (HTML activation behaviour;
    WCAG 2.5.8 counts the region that accepts the pointer action).
    """
    boxes = [element["box"]] + [b for b in (element.get("hit_boxes") or []) if isinstance(b, dict) and b.get("w", 0) > 0 and b.get("h", 0) > 0]
    return max(boxes, key=lambda b: min(b["w"], b["h"]) * 1e6 + b["w"] * b["h"])


def _critical(ctx: Context, element: dict[str, Any]) -> bool:
    return bool(_roles(element) & {"primary", "destructive", "game_control"}) or element.get("id") in ctx.path_element_ids


def check_target_size(ctx: Context) -> list[Observation]:
    out: list[Observation] = []
    targets = _interactive(ctx, whole_page=True)
    target_boxes = {t["id"]: _target_box(t) for t in targets}
    one_handed = str(ctx.attrs.get("grip", "")).startswith("one_hand")
    for element in targets:
        if element.get("tag") in ("canvas",) and not _roles(element):
            continue
        critical = _critical(ctx, element)
        label = element.get("name") or element.get("text") or element.get("selector")
        tbox = target_boxes[element["id"]]
        others = [b for tid, b in target_boxes.items() if tid != element["id"] and b is not tbox]
        ok, reason = pointing.wcag_target_size_ok(tbox, others, params.WCAG_TARGET_MIN_CSS_PX)
        if not ok:
            out.append(Observation(
                "PT-01", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                [element["id"]], element_key(element),
                {"name": "target_css_px", "value": [round(tbox["w"], 1), round(tbox["h"], 1)], "unit": "css_px", "threshold": params.WCAG_TARGET_MIN_CSS_PX, "comparator": ">=", "reason": reason},
                False, "P1" if critical else "P2",
                f"'{label}' 크기 {tbox['w']:.0f}×{tbox['h']:.0f}px로 WCAG 2.5.8 최소 24px 미달, 간격 예외도 불충족({reason}).",
            ))
        if ctx.is_touch and critical and "game_control" not in _roles(element):
            # Platform size guidance (44 pt / 48 dp / 9.2 mm one-thumb) is applied to the
            # controls a task depends on; small secondary targets are covered by PT-01.
            w_mm, h_mm = _box_mm(ctx, tbox)
            side = min(w_mm, h_mm)
            severity = None
            threshold = params.TOUCH_TARGET_MIN_MM
            criterion = "platform_min"
            if side < params.TOUCH_TARGET_PLATFORM_FLOOR_MM and critical:
                severity, threshold = "P1", params.TOUCH_TARGET_PLATFORM_FLOOR_MM
                criterion = "platform_floor"
            elif side < params.TOUCH_TARGET_MIN_MM:
                severity = "P2" if critical else "P3"
            elif one_handed and critical and side < params.TOUCH_TARGET_ONE_HAND_MM and \
                    pointing.dual_gaussian_hit_probability(w_mm, h_mm, 1.0) < pointing.dual_gaussian_hit_probability(params.TOUCH_TARGET_ONE_HAND_MM, params.TOUCH_TARGET_ONE_HAND_MM, 1.0):
                severity, threshold = "P3", params.TOUCH_TARGET_ONE_HAND_MM
                criterion = "one_hand_reference"
            if severity:
                out.append(Observation(
                    "PT-02", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                    [element["id"]], element_key(element),
                    {"name": "target_mm", "value": [round(w_mm, 2), round(h_mm, 2)], "unit": "mm", "threshold": threshold, "comparator": ">=",
                     "criterion": criterion},
                    False, severity,
                    f"'{label}' 물리 크기 {w_mm:.1f}×{h_mm:.1f}mm (기준 {threshold}mm 이상).",
                ))
    return out


def _box_mm_rect(ctx: Context, box: dict[str, float]) -> dict[str, float]:
    x, y = _point_mm(ctx, box["x"], box["y"])
    w, h = _box_mm(ctx, box)
    return {"x": x, "y": y, "w": w, "h": h}


def _miss_severity(p_miss: float) -> str | None:
    for limit, sev in params.MISS_PROBABILITY_SEVERITY:
        if p_miss >= limit:
            return sev
    return None


def _misfire_severity(p_bad: float, irreversible: bool) -> str | None:
    if p_bad >= params.DESTRUCTIVE_NEIGHBOUR_PROB and irreversible:
        return "P0"
    if p_bad >= params.DESTRUCTIVE_NEIGHBOUR_PROB_HIGH:
        return "P1"
    if p_bad >= params.DESTRUCTIVE_NEIGHBOUR_PROB:
        return "P2"
    return None


def _worse(a: str | None, b: str | None) -> str | None:
    if a is None:
        return b
    if b is None:
        return a
    return a if SEVERITY_ORDER[a] <= SEVERITY_ORDER[b] else b


def _cap(severity: str | None, cap: str) -> str | None:
    if severity is None:
        return None
    return severity if SEVERITY_ORDER[severity] >= SEVERITY_ORDER[cap] else cap


def check_touch_accuracy(ctx: Context) -> list[Observation]:
    """Dual-Gaussian miss and misfire probabilities (MP-02/03/11/12).

    Severity from the published model at k=1 (young able-bodied baseline) can reach
    P1 (P0 for declared irreversible misfires). Inflation by profile multipliers is a
    declared assumption: it adds findings only for targets below the one-thumb
    research size (9.2 mm) and is capped at P2.
    """
    if not ctx.is_touch:
        return []
    out: list[Observation] = []
    k = float(ctx.attrs.get("motor", {}).get("touch_sigma_multiplier") or 1.0)
    targets = _interactive(ctx)
    destructive = [t for t in targets if "destructive" in _roles(t)]
    for element in targets:
        roles = _roles(element)
        if not _critical(ctx, element) or "destructive" in roles and element.get("id") not in ctx.path_element_ids:
            continue
        rect = _box_mm_rect(ctx, _target_box(element))
        ref = params.TOUCH_TARGET_ONE_HAND_MM
        # "Small" means harder to hit than Parhi's 9.2 mm one-thumb square at the same
        # spread; a 19 x 8.8 mm button is easier to hit than that square.
        small = (1.0 - pointing.dual_gaussian_hit_probability(rect["w"], rect["h"], k)) > (1.0 - pointing.dual_gaussian_hit_probability(ref, ref, k))
        p_base = 1.0 - pointing.dual_gaussian_hit_probability(rect["w"], rect["h"], 1.0)
        p_miss = 1.0 - pointing.dual_gaussian_hit_probability(rect["w"], rect["h"], k)
        severity = _miss_severity(p_base)
        platform_size = params.TOUCH_PROFILE_ONLY_P3_MIN_MM is not None and min(rect["w"], rect["h"]) >= params.TOUCH_PROFILE_ONLY_P3_MIN_MM
        profile_only = False
        if k > 1.0 and small:
            # Profile inflation is an assumption: P2 only for the primary action or a
            # control the task actually used; otherwise P3 (MP-02, adjudication 2026-09-28).
            # A target that meets the platform size gets P3 at most from inflation alone
            # (SIT-01: walking and tremor studies find 7-8 mm targets usable; dev round 8).
            cap = "P2" if ("primary" in roles or element.get("id") in ctx.path_element_ids) else "P3"
            if severity is None and platform_size:
                cap = "P3"
            inflated = _worse(severity, _cap(_miss_severity(p_miss), cap))
            profile_only = severity is None and inflated is not None
            severity = inflated
        measurement = {"name": "miss_probability", "value": round(p_miss, 4), "unit": "probability", "threshold": params.MISS_PROBABILITY_SEVERITY[-1][0], "comparator": "<",
                       "sigma_multiplier": k, "baseline_miss_probability": round(p_base, 4), "target_mm": [round(rect["w"], 2), round(rect["h"], 2)],
                       "profile_only": profile_only}
        if (severity is not None and k > 1.0 and ("primary" in roles or element.get("id") in ctx.path_element_ids)
                and params.TOUCH_TARGET_MIN_MM <= min(rect["w"], rect["h"]) < ref):
            # Advice data only (SIT-05), never a verdict: the smallest square at this
            # profile's observed spread that matches the 9.2 mm reference square at
            # k = 1 in the same dual-Gaussian model — a model-equivalent comparison,
            # not an accessibility requirement or a calibrated human error rate.
            # Limited to the failed primary/taskpath 7-9.2 mm targets PT-04 already flags.
            # reference_miss_probability is the reference square's own miss at k = 1
            # (~0.46%), kept distinct from baseline_miss_probability, which is the
            # actual target's miss at k = 1. The equivalent size is rounded UP to
            # 0.1 mm so a "minimum" wording never under-shoots the model bound;
            # found_within_search_bound=False only means no match inside the bound.
            same = pointing.equivalent_square_mm(ref, k)
            measurement["same_error_square"] = {
                "reference_mm": ref,
                "reference_sigma_multiplier": 1.0,
                "reference_miss_probability": round(1.0 - pointing.dual_gaussian_hit_probability(ref, ref, 1.0), 5),
                "sigma_multiplier": round(k, 4),
                "equivalent_square_mm": None if same is None else math.ceil(same * 10.0 - 1e-9) / 10.0,
                "found_within_search_bound": same is not None,
                "search_bound_mm": pointing.EQUIV_SQUARE_SEARCH_MAX_MM,
            }
        out.append(Observation(
            "PT-04", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
            [element["id"]], element_key(element),
            measurement,
            severity is None, severity,
            f"'{element.get('name') or element.get('text')}' 예측 오터치 확률 {p_miss*100:.1f}% (기준 인구 {p_base*100:.1f}%, σ배수 {k:.2f}, {rect['w']:.1f}×{rect['h']:.1f}mm).",
            "bi-zhai-2016-dual-gaussian",
        ))
        for bad in destructive:
            if bad is element:
                continue
            bad_rect = _box_mm_rect(ctx, bad["box"])
            p_bad_base = pointing.dual_gaussian_neighbour_probability(rect, bad_rect, 1.0)
            p_bad = pointing.dual_gaussian_neighbour_probability(rect, bad_rect, k)
            gap_mm = _point_mm(ctx, pointing.box_gap(element["box"], bad["box"]), 0)[0]
            if gap_mm > 20 and p_bad < 1e-4:
                continue
            irreversible = "irreversible" in _roles(bad)
            severity = _misfire_severity(p_bad_base, irreversible)
            if k > 1.0:
                cap = "P3" if (severity is None and platform_size and not irreversible) else "P2"  # SIT-01
                severity = _worse(severity, _cap(_misfire_severity(p_bad, irreversible), cap))
            if severity is None and gap_mm < params.DESTRUCTIVE_MIN_GAP_MM:
                severity = "P3"
            out.append(Observation(
                "PT-03", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                [element["id"], bad["id"]], element_key(bad),
                {"name": "destructive_misfire", "value": {"p_misfire": round(p_bad, 5), "p_misfire_baseline": round(p_bad_base, 5), "gap_mm": round(gap_mm, 2)},
                 "unit": "probability/mm", "threshold": {"p": params.DESTRUCTIVE_NEIGHBOUR_PROB, "gap_mm": params.DESTRUCTIVE_MIN_GAP_MM}, "comparator": "<", "sigma_multiplier": k},
                severity is None, severity,
                f"'{element.get('name') or element.get('text')}'을(를) 누르려다 '{bad.get('name') or bad.get('text')}'을(를) 누를 확률 {p_bad*100:.2f}% (기준 인구 {p_bad_base*100:.2f}%), 간격 {gap_mm:.1f}mm.",
                "bi-zhai-2016-dual-gaussian",
            ))
    return out


def check_pointer_separation(ctx: Context) -> list[Observation]:
    """PT-06: destructive action against a primary/path action on pointer devices."""
    if ctx.is_touch:
        return []
    out: list[Observation] = []
    targets = _interactive(ctx, whole_page=True)
    for bad in [t for t in targets if "destructive" in _roles(t)]:
        for good in targets:
            if good is bad or "destructive" in _roles(good) or not _critical(ctx, good):
                continue
            gap = pointing.box_gap(good["box"], bad["box"])
            if gap >= params.POINTER_DESTRUCTIVE_MIN_GAP_CSS_PX:
                continue
            out.append(Observation(
                "PT-06", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                [good["id"], bad["id"]], element_key(bad),
                {"name": "destructive_gap_css_px", "value": round(gap, 1), "unit": "css_px", "threshold": params.POINTER_DESTRUCTIVE_MIN_GAP_CSS_PX, "comparator": ">="},
                False, "P2",
                f"파괴적 동작 '{bad.get('name') or bad.get('text')}'이(가) '{good.get('name') or good.get('text')}'에 {gap:.0f}px 간격으로 붙어 있습니다.",
            ))
    return out


SECONDARY_CONTROL_WORDS = ("pause", "menu", "setting", "option", "help", "close", "back", "exit", "home",
                           "일시정지", "메뉴", "설정", "옵션", "도움말", "닫기", "뒤로", "나가기", "홈")


def _secondary_control(element: dict[str, Any]) -> bool:
    """Pause, menu, settings and similar controls: occasional, placed at the top by convention (Apple HIG)."""
    label = f"{element.get('name') or ''} {element.get('text') or ''} {element.get('selector') or ''}".lower()
    return any(word in label for word in SECONDARY_CONTROL_WORDS)


def _tap_count(run: dict[str, Any], element: dict[str, Any]) -> int:
    sel = element.get("selector")
    count = 0
    for step in run.get("steps", []):
        action = step.get("action") or {}
        if action.get("action") not in ("tap", "click", "double_tap", "long_press"):
            continue
        # Match by selector: element ids are renumbered in every snapshot.
        if sel and (action.get("target") == sel or step.get("target_selector") == sel):
            count += 1
    return count


def check_game_controls(ctx: Context) -> list[Observation]:
    """GM-05: touch game controls below platform size or flush to the screen edge (HGR-11)."""
    if not ctx.is_touch:
        return []
    out: list[Observation] = []
    vw, vh = ctx.viewport
    for element in ctx.elements:
        if "game_control" not in _roles(element) or not _visible(element):
            continue
        box = element["box"]
        w_mm, h_mm = _box_mm(ctx, box)
        side = min(w_mm, h_mm)
        edge_css = min(box["x"], box["y"], vw - (box["x"] + box["w"]), vh - (box["y"] + box["h"]))
        edge_mm = _point_mm(ctx, max(0.0, edge_css), 0)[0]
        severity = None
        reasons = []
        serial = not _secondary_control(element) or "timed" in _roles(element) or _tap_count(ctx.run, element) >= 2
        if side < params.TOUCH_TARGET_MIN_MM:
            severity = "P2"
            reasons.append(f"{side:.1f}mm < 44pt(약 {params.TOUCH_TARGET_MIN_MM}mm)")
        elif side < params.TOUCH_TARGET_SERIAL_MM and serial:
            # Parhi's 9.6 mm is for serial thumb tapping; an occasional control (pause) is not serial.
            severity = "P3"
            reasons.append(f"{side:.1f}mm < 연속 입력 권장 {params.TOUCH_TARGET_SERIAL_MM}mm")
        if 0 <= edge_mm < params.GAME_CONTROL_EDGE_MIN_MM:
            severity = _worse(severity, "P3")
            reasons.append(f"가장자리에서 {edge_mm:.1f}mm (시스템 제스처/베젤 간섭)")
        out.append(Observation(
            "GM-05", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
            [element["id"]], element_key(element),
            {"name": "game_control_mm", "value": [round(w_mm, 1), round(h_mm, 1)], "unit": "mm", "threshold": params.TOUCH_TARGET_SERIAL_MM,
             "comparator": ">=", "edge_mm": round(edge_mm, 1)},
            severity is None, severity,
            f"게임 조작 '{element.get('name') or element.get('selector')}': " + ("; ".join(reasons) if reasons else "기준 충족"),
        ))
    return out


def check_fitts_sequence(ctx: Context) -> list[Observation]:
    step = ctx.step
    prev = ctx.previous
    if not step or not prev or ctx.is_touch:
        return []
    if step.get("action", {}).get("action") not in ("click", "tap", "double_tap"):
        return []
    point = step.get("point")
    prev_point = prev.get("focus_point")
    # Element ids are renumbered per snapshot: resolve the step's target in its before
    # snapshot (the previous one here) and match it in this snapshot by selector.
    before_target = next((e for e in prev.get("elements", []) if e.get("id") == step.get("target_element_id")), None)
    target = next((e for e in ctx.elements if before_target is not None and e.get("selector") == before_target.get("selector")), before_target)
    if not point or not prev_point or not target:
        return []
    distance = math.hypot(point["x"] - prev_point["x"], point["y"] - prev_point["y"])
    width = max(1.0, min(target["box"]["w"], target["box"]["h"]))
    index = pointing.fitts_id(distance, width)
    failed = index > params.FITTS_ID_HIGH_BITS
    return [Observation(
        "PT-05", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
        [target["id"]], element_key(target),
        {"name": "fitts_id_bits", "value": round(index, 2), "unit": "bits", "threshold": params.FITTS_ID_HIGH_BITS, "comparator": "<=",
         "predicted_mt_ms": round(pointing.fitts_mt_ms(distance, width, params.FITTS_MOUSE_A_MS, params.FITTS_MOUSE_B_MS), 0)},
        not failed, "P3" if failed else None,
        f"직전 조작 위치에서 '{target.get('name') or target.get('text')}'까지 Fitts ID {index:.1f}bit.",
        "fitts-shannon-v1",
    )]


# ---------------------------------------------------------------- gaze

_FIXATION_CACHE: dict[tuple, dict[str, list[float]]] = {}


def _gaze_kind(ctx: Context) -> str:
    return gaze.prior_kind(getattr(ctx.device, "form_factor", "phone"), ctx.surface_kind)


def _priorities(ctx: Context) -> dict[str, float]:
    enriched = []
    for e in ctx.elements:
        if not _usable(e):
            continue
        item = dict(e)
        fg, bg = perception.parse_color(e.get("color_fg")), perception.parse_color(e.get("color_bg"))
        if fg and bg:
            item["_contrast"] = perception.contrast_ratio(fg, bg)
        fill, container = perception.parse_color(e.get("color_bg")), perception.parse_color(e.get("container_bg") or "#ffffff")
        if fill and container and e.get("interactive"):
            item["_fill_contrast"] = (perception.contrast_ratio(fill, container) - 1.0) / 4.0
        enriched.append(item)
    return gaze.element_priorities(enriched, ctx.viewport, _gaze_kind(ctx), ctx.conspicuity)


def _viewing_distance(ctx: Context) -> float:
    vision = ctx.attrs.get("vision", {})
    return float(vision.get("viewing_distance_mm") or getattr(ctx.device, "viewing_distance_mm", 300) or 300)


def _notice_scale(ctx: Context) -> float:
    vision = ctx.attrs.get("vision", {})
    older = ctx.attrs.get("age_band") == "70s+"
    low_vision = vision.get("acuity") in ("reduced", "low")
    loaded = ctx.attrs.get("cognition", {}).get("time_pressure") == "high"
    return params.NOTICE_PERSONA_SCALE if (older or low_vision or loaded) else 1.0


def _salient_change(ctx: Context, element: dict[str, Any], new: bool) -> tuple[bool, dict[str, Any]]:
    """GZ-02 salience: a new object that is >= 1 deg and >= 3:1 against its surroundings."""
    from .devices import mm_per_css_px

    b = gaze.clipped_visible_box(element, ctx.viewport)
    if b is None:
        return False, {"size_deg": None, "reason": "visible_geometry_unverified"}
    x, y, w, h = b
    eye = (ctx.viewport[0] / 2, ctx.viewport[1] / 2)
    sx, sy, distance = mm_per_css_px(ctx.device, "x"), mm_per_css_px(ctx.device, "y"), _viewing_distance(ctx)
    width = gaze.angular_separation_css((x, y + h / 2), (x + w, y + h / 2), sx, sy, distance, eye)
    height = gaze.angular_separation_css((x + w / 2, y), (x + w / 2, y + h), sx, sy, distance, eye)
    if width is None or height is None:
        return False, {"size_deg": None, "reason": "invalid_geometry"}
    size_deg = max(width, height)
    fg = perception.parse_color(element.get("color_fg"))
    bg = perception.parse_color(element.get("color_bg"))
    container = perception.parse_color(element.get("container_bg") or "#ffffff")
    contrast = 1.0
    if bg and container and bg != container:
        contrast = perception.contrast_ratio(bg, container)
    elif fg and bg:
        contrast = perception.contrast_ratio(fg, bg)
    # A new message whose own text stands out (bold or with a warning/status icon, and
    # at least 4.5:1) is a salient object even when its box barely differs from the page.
    text = (element.get("text") or "").strip()
    text_contrast = perception.contrast_ratio(fg, bg) if fg and bg else 1.0
    emphatic = (element.get("font_weight") or 400) >= 600 or text[:1] in params.SALIENT_ICON_CHARS
    text_salient = text_contrast >= params.SALIENT_TEXT_MIN_CONTRAST and emphatic
    salient = new and size_deg >= params.SALIENT_CHANGE_MIN_DEG and (contrast >= params.SALIENT_CHANGE_MIN_CONTRAST or text_salient)
    return salient, {"size_deg": round(size_deg, 2), "contrast": round(contrast, 2), "text_contrast": round(text_contrast, 2),
                     "text_salient": text_salient, "new_object": new}


def _screen_changed(previous: dict[str, Any] | None, current: dict[str, Any]) -> bool:
    """True when an action replaced the screen (navigation or a full re-render).

    Feedback on a new screen is where the user re-orients, not a peripheral change.
    """
    if previous is None:
        return False
    if (previous.get("surface") or {}).get("url") != (current.get("surface") or {}).get("url"):
        return True
    before = {e.get("selector") or e.get("id") for e in previous.get("elements", []) if _visible(e)}
    after = {e.get("selector") or e.get("id") for e in current.get("elements", []) if _visible(e)}
    if not before:
        return False
    return len(before - after) / len(before) >= params.SCREEN_CHANGE_FRACTION


def _app_scrolled(ctx: Context) -> bool:
    """The app scrolled the window by at least APP_SCROLL_REORIENT_FRACTION of the screen
    during the step (not a scroll, swipe or drag the user made)."""
    if ctx.previous is None:
        return False
    if ((ctx.step or {}).get("action") or {}).get("action") in ("scroll", "swipe", "drag"):
        return False
    a = ((ctx.previous.get("surface") or {}).get("scroll") or {}).get("y")
    b = ((ctx.snapshot.get("surface") or {}).get("scroll") or {}).get("y")
    if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
        return False
    return abs(b - a) >= params.APP_SCROLL_REORIENT_FRACTION * ctx.viewport[1]


def _feedback_focus_anchor(ctx: Context, feedback: dict[str, Any]) -> tuple[tuple[float, float], dict[str, Any]] | None:
    """Observed pointer-triggered focus transfer to this message's unique field.

    DOM focus supplies a bounded attention-anchor assumption, never measured
    gaze. Missing/ambiguous evidence and direct pointer focus keep the input
    anchor. The original input remains the physical thumb-occlusion anchor.
    """
    step = ctx.step or {}
    action = step.get("action") or {}
    if step.get("result") != "ok" or action.get("action") not in ("tap", "click", "double_tap", "long_press"):
        return None
    previous = ctx.previous or {}
    if step.get("before") not in (None, previous.get("snapshot_id")) or step.get("after") not in (None, ctx.snapshot.get("snapshot_id")):
        return None
    before_focus, after_focus = previous.get("focus") or {}, ctx.snapshot.get("focus") or {}
    if not isinstance(before_focus, dict) or not isinstance(after_focus, dict):
        return None
    before_id, after_id = before_focus.get("dom_id"), after_focus.get("dom_id")
    observed_body = before_focus.get("on_body") is True
    observed_field = before_focus.get("on_body") is False and isinstance(before_id, str) and bool(before_id)
    if not (observed_body or observed_field) or not isinstance(after_id, str) or not after_id or before_id == after_id or after_focus.get("on_body") is not False:
        return None
    fields = [e for e in ctx.elements if e.get("dom_id") == after_id]
    if len(fields) != 1:
        return None
    field = fields[0]
    a11y = field.get("a11y") or {}
    if not isinstance(a11y, dict):
        return None
    if (field.get("role") not in FIELD_ROLES and field.get("tag") not in ("input", "select", "textarea")):
        return None
    if not _visible(field) or not field.get("enabled", True) or a11y.get("hidden") or a11y.get("focusable") is False or a11y.get("rendered") is False:
        return None
    box = gaze.clipped_visible_box(field, ctx.viewport)
    if box is None:
        return None
    target_id = step.get("target_element_id")
    targets = [e for e in previous.get("elements", []) if
               (e.get("id") == target_id if target_id else isinstance(action.get("target"), str) and e.get("selector") == action["target"])]
    if len(targets) != 1 or not targets[0].get("interactive") or targets[0].get("dom_id") == after_id or targets[0].get("tag") == "label":
        return None
    message_id = feedback.get("dom_id")
    if not isinstance(message_id, str) or not message_id or sum(e.get("dom_id") == message_id for e in ctx.elements) != 1:
        return None
    described_by = a11y.get("described_by") or []
    relation = "aria-describedby" if isinstance(described_by, list) and message_id in described_by else None
    if a11y.get("invalid") is True and a11y.get("error_message") == message_id:
        relation = "aria-errormessage"
    if relation is None:
        return None
    x, y, w, h = box
    return (x + w / 2, y + h / 2), {
        "anchor_basis": "observed_programmatic_focus_relocation",
        "anchor_assumption": "attention_near_focused_field_unmeasured",
        "focus_before_dom_id": before_id, "focus_before_on_body": observed_body, "focus_after_dom_id": after_id,
        "anchor_field_id": field["id"], "feedback_focus_relation": relation,
    }


def check_gaze(ctx: Context) -> list[Observation]:
    from .devices import mm_per_css_px

    out: list[Observation] = []
    priorities = _priorities(ctx)
    kind = _gaze_kind(ctx)
    base = (ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"))
    focus = ctx.snapshot.get("focus_point")
    vw, vh = ctx.viewport
    if not all(is_number(v) and v > 0 for v in (vw, vh)):
        return out
    if focus is not None and (not isinstance(focus, dict) or not all(is_number(focus.get(k)) for k in ("x", "y"))):
        return out
    if focus:
        start = (float(focus["x"]), float(focus["y"]))
        start_basis = gaze.START_LAST_ACTION
    else:
        px, py = gaze.prior_peak(kind)
        start = (px * vw, py * vh)
        start_basis = gaze.START_PRIOR_PEAK
    sx, sy = mm_per_css_px(ctx.device, "x"), mm_per_css_px(ctx.device, "y")
    viewing = _viewing_distance(ctx)
    if not all(is_number(v) and v > 0 for v in (sx, sy, viewing)):
        return out
    eye = (vw / 2, vh / 2)
    geometry = {"geometry_model": gaze.GEOMETRY_ID, "eye_projection": gaze.EYE_PROJECTION,
                "eye_projection_css": list(eye), "mm_per_css_px": [sx, sy], "viewing_distance_mm": viewing,
                "anchor_basis": start_basis, "anchor_css": list(start), "measured_gaze": False}
    regions = gaze.equivalent_regions([e for e in ctx.elements if e["id"] in priorities], ctx.viewport)
    region_of = {i: r for r in regions for i in r["member_ids"]}
    for region in regions:
        region["priority"] = max(priorities[i] for i in region["member_ids"])
    visible_primary = [e for e in ctx.elements if "primary" in _roles(e) and _visible(e) and e.get("enabled", True)]
    inputs = tuple((r["member_ids"], r["centre"], r["priority"]) for r in regions)
    cache_key = (gaze.MODEL_ID, inputs, viewing, start, sx, sy, eye, params.GAZE_MC_RUNS, params.GAZE_MC_FIXATIONS)
    probs = _FIXATION_CACHE.get(cache_key)
    if probs is None and regions and visible_primary:
        _, probs = gaze.sample_equivalent_fixations(ctx.elements, priorities, ctx.viewport, start, sx, viewing,
                                                   mm_per_css_px_y=sy, eye_css=eye, seed=1)
        _FIXATION_CACHE[cache_key] = probs
    probs = probs or {}
    interactive_ids = {e["id"] for e in _interactive(ctx)}
    k = params.GAZE_EARLY_FIXATIONS
    sampling = {"model_version": gaze.MODEL_ID, "n_runs": params.GAZE_MC_RUNS,
                "n_fix": params.GAZE_MC_FIXATIONS, "start_basis": start_basis, "seed": 1,
                "region_count": len(regions), "calibrated": False, **geometry}
    for element in visible_primary:
        region = region_of.get(element["id"])
        series = probs.get(element["id"])
        if region is None or not series or len(series) < k:
            reason = "visible_geometry_unverified" if region is None else "invalid_sampling_geometry"
            out.append(Observation(
                "GZ-01", *base, [element["id"]], element_key(element),
                {"name": "p_fixated_within_k", "value": None, "unit": "simulation_hit_fraction", "k": k,
                 "reason": reason, "visible_geometry": element.get("visible_geometry"), **sampling},
                False, None, "주요 동작의 보이는 영역을 확인할 수 없어 시선 시뮬레이션 판정을 보류했습니다.",
                gaze.MODEL_ID, extra={"verdict": "inconclusive"},
            ))
            continue
        fraction = series[k - 1]
        severity = "P3" if fraction < params.GAZE_PRIMARY_P2 else None
        out.append(Observation(
            "GZ-01", *base, [element["id"]], element_key(element),
            {"name": "p_fixated_within_k", "value": round(fraction, 3), "unit": "simulation_hit_fraction",
             "threshold": params.GAZE_PRIMARY_P2, "comparator": ">=", "k": k,
             "reference_target": params.GAZE_PRIMARY_PASS, "decision_rule": "P3 below hypothesis threshold; reference target is advisory",
             "priority": round(region["priority"], 3), "region_aliases": list(region["member_ids"]), **sampling},
            severity is None, severity,
            f"주요 동작 '{element.get('name') or element.get('text')}' 영역을 처음 {k}번 선택 안에 포함한 시뮬레이션 비율 {fraction:.2f}"
            + f" ({params.GAZE_MC_RUNS}회 실행, 경로당 {params.GAZE_MC_FIXATIONS}회 선택). 시작점은 "
            + ("마지막 입력 위치" if focus else "위치 prior의 최고점")
            + "이며 실제 시선 관측과 사람의 발견 확률은 확인되지 않았습니다.",
            gaze.MODEL_ID,
        ))
        competing = [r for r in regions if r is not region and r["priority"] > region["priority"]
                     and interactive_ids.intersection(r["member_ids"])]
        failed = len(competing) >= params.GAZE_COMPETITORS_MAX
        out.append(Observation(
            "GZ-04", *base, [element["id"], *(r["member_ids"][0] for r in competing[:5])], element_key(element),
            {"name": "competing_interactive_elements", "value": len(competing), "unit": "region_count",
             "threshold": params.GAZE_COMPETITORS_MAX, "comparator": "<",
             "competing_region_aliases": [list(r["member_ids"]) for r in competing], **sampling},
            not failed, "P3" if failed else None,
            f"주요 동작보다 시각적 우선순위가 높은 조작 영역 {len(competing)}개. 같은 요소의 중복 표현은 한 번 계산했습니다.",
            gaze.MODEL_ID,
        ))
    # GZ-02: feedback noticing after an action (change blindness + thumb occlusion).
    if ctx.previous is not None and focus:
        # After a screen replacement, content of the new screen is where the user
        # re-orients (not peripheral), but transient messages (toasts, declared timing
        # windows) shown with it can still be missed.
        replaced = _screen_changed(ctx.previous, ctx.snapshot)
        reoriented = _app_scrolled(ctx)
        transient = {w.get("selector") for w in (ctx.scenario or {}).get("timing_windows", []) if w.get("kind") in (None, "transient_text")}
        # Messages already rendered before the step, in view or not: a message scrolled
        # out of view (by the page or by the driver's pre-action scroll) is not new.
        before = {e.get("selector") or e.get("id"): e for e in ctx.previous.get("elements", []) if _present(e) and (e.get("text") or "").strip()}
        scale = _notice_scale(ctx)
        grip = ctx.attrs.get("grip", "")
        geom = reach.geometry_for_device(ctx.device) if ctx.is_touch else None
        thumb = float(ctx.attrs.get("thumb_length_mm") or params.THUMB_LENGTH_MM["all"][0])
        feedback = []
        for element in ctx.elements:
            roles = _roles(element)
            is_feedback = roles & {"error_message", "critical_message", "status"} or element.get("role") in ("alert", "status")
            if not is_feedback or not (element.get("text") or "").strip():
                continue  # an empty live-region slot is not a message yet
            if replaced and element.get("selector") not in transient:
                continue
            key = element.get("selector") or element.get("id")
            prior = before.get(key)
            changed_text = prior is not None and (prior.get("text") or "") != (element.get("text") or "")
            if prior is not None and not changed_text:
                continue
            if _present(element) and element.get("in_viewport") is False and (element.get("text") or "").strip():
                # New or changed feedback rendered outside the viewport cannot be seen at all
                # (UXD-12: P1 when it is an error or critical message).
                critical = bool(roles & {"error_message", "critical_message"}) or element.get("role") == "alert"
                # A message that just appeared off-screen is missed feedback. An existing one
                # whose text changed while the user is elsewhere (a status line, an earlier
                # error being updated) is only a prompt to check (dev-2 clean pages).
                sev = ("P1" if critical else "P2") if prior is None else "P3"
                out.append(Observation(
                    "GZ-02", *base, [element["id"]], element_key(element),
                    {"name": "feedback_eccentricity_deg", "value": None, "unit": "deg", "threshold": "in viewport", "comparator": "band",
                     "band": "offscreen", "box": element["box"], "new": prior is None, **geometry},
                    False, sev,
                    f"조작 후 {'새로 나타난' if prior is None else '바뀐'} 메시지 '{(element.get('text') or '')[:30]}'이(가) 화면 밖(뷰포트 바깥)에 있어 보이지 않습니다.",
                    gaze.MODEL_ID,
                ))
                continue
            if not _visible(element) or (reoriented and element.get("selector") not in transient):
                continue
            visible_box = gaze.clipped_visible_box(element, ctx.viewport)
            if visible_box is None:
                out.append(Observation(
                    "GZ-02", *base, [element["id"]], element_key(element),
                    {"name": "feedback_eccentricity_deg", "value": None, "unit": "deg",
                     "band": "unverified", "reason": "visible_geometry_unverified", **geometry},
                    False, None, "피드백의 보이는 영역을 확인할 수 없어 조작 지점과의 각도 판정을 보류했습니다.",
                    gaze.MODEL_ID, extra={"verdict": "inconclusive"},
                ))
                continue
            x, y, w, h = visible_box
            centre_css = (x + w / 2, y + h / 2)
            anchor = _feedback_focus_anchor(ctx, element)
            attention_point, anchor_evidence = anchor if anchor is not None else (start, {})
            feedback_geometry = {**geometry, "input_anchor_css": list(start), "input_anchor_basis": start_basis,
                                 **anchor_evidence, "anchor_css": list(attention_point)}
            # Eccentricity to the nearest point of the message, not its centroid: a wide
            # error box beside the button starts right next to the click (gaze brief rule).
            near_css = (min(max(attention_point[0], x), x + w), min(max(attention_point[1], y), y + h))
            theta = gaze.angular_separation_css(attention_point, near_css, sx, sy, viewing, eye)
            if theta is None:
                continue
            salient, sal = _salient_change(ctx, element, new=prior is None)
            band = gaze.notice_band(theta, salient, scale)
            occluded = False
            if geom is not None and grip.startswith("one_hand"):
                occluded = reach.occluded_by_thumb(_point_mm(ctx, focus["x"], focus["y"]), _point_mm(ctx, *centre_css), geom, grip, thumb, params.OCCLUSION_WEDGE_DEG)
            feedback.append((element, roles, prior, theta, salient, sal, band, occluded, near_css, feedback_geometry))
        # Redundant feedback: when another new, salient message appears where the user is
        # looking (likely noticed, not occluded), a far secondary label is not missed feedback.
        # Redundancy requires the same attention-anchor assumption and point.
        noticed = [f for f in feedback if f[6] == "likely" and f[4] and not f[7]]
        for element, roles, prior, theta, salient, sal, band, occluded, near_css, feedback_geometry in feedback:
            critical = bool(roles & {"error_message", "critical_message"}) or element.get("role") == "alert"
            redundant = any(n[0] is not element and n[9]["anchor_basis"] == feedback_geometry["anchor_basis"]
                            and n[9]["anchor_css"] == feedback_geometry["anchor_css"] for n in noticed)
            severity = None
            if redundant:
                severity = None
            elif band == "likely_missed" or occluded:
                severity = "P2" if critical else "P3"
            elif band == "uncertain" and critical:
                severity = "P3"
            sal = {**sal, "redundant_with_noticed_feedback": redundant}
            out.append(Observation(
                "GZ-02", *base, [element["id"]], element_key(element),
                {"name": "feedback_eccentricity_deg", "value": round(theta, 1), "unit": "deg",
                 "threshold": [round(v * scale, 1) for v in params.NOTICE_BANDS_DEG["salient" if salient else "non_salient"]],
                 "comparator": "band", "band": band, "salient": salient, "occluded_by_thumb": occluded, "persona_scale": scale, "nearest_feedback_css": list(near_css), **feedback_geometry, **sal},
                severity is None, severity,
                f"{'초점이 이동한 입력 칸' if feedback_geometry['anchor_basis'] == 'observed_programmatic_focus_relocation' else '조작 지점'}에서 {theta:.0f}° 떨어진 곳에 {'새' if prior is None else '바뀐'} 메시지 '{(element.get('text') or element.get('name') or '')[:30]}'"
                + f" ({'돌출' if salient else '비돌출'} 변화, 인지 가능성: {band})" + (", 한 손 파지 엄지에 가려질 위치" if occluded else "")
                + (". 입력 칸 근처로 주의가 이동한다고 가정했으며 실제 시선은 측정하지 않았습니다." if feedback_geometry['anchor_basis'] == 'observed_programmatic_focus_relocation'
                   else ". 마지막 입력 위치에서 계산했습니다.")
                + " 눈의 화면 투영점은 화면 중심으로 가정했습니다.",
                gaze.MODEL_ID,
            ))
    # GZ-03: banner-blindness proxy on desktop/web.
    if getattr(ctx.device, "form_factor", "phone") in ("desktop", "laptop"):
        for element in ctx.elements:
            roles = _roles(element)
            if not (roles & {"critical_message", "error_message", "status"}) or not _visible(element):
                continue
            visible_box = gaze.clipped_visible_box(element, ctx.viewport)
            if visible_box is None:
                continue
            box = dict(zip("xywh", visible_box))
            right_rail = box["x"] >= vw * params.AD_RAIL_X_FRAC
            banner = box["y"] <= vh * params.AD_BANNER_Y_FRAC and box["w"] >= vw * 0.6 and box["h"] <= params.AD_BANNER_MAX_H
            ad_like = "ad_like" in roles
            failed = right_rail or ad_like
            if not failed and not banner:
                continue
            out.append(Observation(
                "GZ-03", *base, [element["id"]], element_key(element),
                {"name": "ad_like_zone", "value": {"right_rail": right_rail, "top_banner": banner, "declared_ad_like": ad_like}, "unit": "flags", "threshold": "none", "comparator": "=="},
                not failed, "P3" if failed else None,
                f"중요 정보 '{(element.get('text') or '')[:30]}'이(가) 광고 영역처럼 보이는 위치에 있습니다(배너 블라인드니스 위험, 판단 확인 필요).",
                "ad-zone-proxy-v1",
            ))
    return out


# ---------------------------------------------------------------- perception

def check_contrast(ctx: Context) -> list[Observation]:
    out: list[Observation] = []
    lighting = ctx.attrs.get("context", {}).get("lighting")
    for element in ctx.elements:
        text = (element.get("text") or "").strip()
        if not text or not _present(element) or element.get("enabled", True) is False:
            continue
        fg, bg = perception.parse_color(element.get("color_fg")), perception.parse_color(element.get("color_bg"))
        if not fg or not bg:
            continue
        ratio = perception.contrast_ratio(fg, bg)
        need = perception.required_text_contrast(element.get("font_size_px"), element.get("font_weight"))
        if ratio < need:
            severity = "P2"
            if ratio < params.CONTRAST_SEVERE:
                severity = "P1"
            if _roles(element) & {"primary", "critical_message", "error_message"}:
                severity = "P1"
            out.append(Observation(
                "PC-01", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                [element["id"]], element_key(element),
                {"name": "contrast_ratio", "value": round(ratio, 2), "unit": "ratio", "threshold": need, "comparator": ">=",
                 "fg": element.get("color_fg"), "bg": element.get("color_bg"), "font_size_px": element.get("font_size_px")},
                False, severity,
                f"'{text[:30]}' 대비 {ratio:.2f}:1 (기준 {need}:1).",
            ))
        elif lighting == "bright_sun" and ratio < params.CONTRAST_BRIGHT_LIGHT:
            if not (_roles(element) & {"primary", "critical_message", "error_message", "status"}):
                continue
            out.append(Observation(
                "PC-05", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                [element["id"]], element_key(element),
                {"name": "contrast_ratio", "value": round(ratio, 2), "unit": "ratio", "threshold": params.CONTRAST_BRIGHT_LIGHT, "comparator": ">="},
                False, "P3",
                f"햇빛 환경에서 '{text[:30]}' 대비 {ratio:.2f}:1은 여유가 부족할 수 있습니다.",
                "situational-contrast-v1",
            ))
    for element in _interactive(ctx, whole_page=True):
        tag = element.get("tag")
        role = element.get("role")
        labelled = bool(_label_tokens(element.get("text") or "")) and not element.get("a11y", {}).get("icon_font")
        native = tag in ("input", "select", "textarea")
        # A text-labelled custom radio/checkbox card is identified by its text; WCAG 1.4.11
        # then concerns the state indicator, not the card outline (adjudication 2026-09-28).
        # A switch's track and a slider's thumb are the state indicator itself, so their
        # boundary matters even with a text label.
        paint = element.get("paint")
        if isinstance(paint, dict) and (paint.get("gaps") or paint.get("decorative")):
            continue  # unmeasured paint may identify the control; the report records the gap
        state_parts = isinstance(paint, dict) and any(p.get("kind") != "text" and not p.get("key", "").startswith("self:") for p in paint.get("parts", []))
        form_control = native or role in ("switch", "slider") or (role in ("checkbox", "radio") and state_parts) or (role in ("checkbox", "radio", "textbox", "combobox", "searchbox", "spinbutton") and not labelled)
        icon_only = tag in ("button", "a") and not labelled
        if not (form_control or icon_only):
            continue  # WCAG 1.4.11 does not require a boundary when text identifies the control
        if isinstance(paint, dict):
            # A label's dark foreground cannot stand in for its track/thumb. Distinct
            # indicator nodes are evaluated independently; fill/border on one node
            # remain alternative ways of identifying that node.
            by_part: dict[str, list[tuple[str, float]]] = {}
            for part in paint.get("parts", []):
                if part.get("kind") == "text" and form_control:
                    continue
                if state_parts and role in ("switch", "slider", "checkbox", "radio") and part.get("key", "").startswith("self:"):
                    continue
                fg = perception.parse_color(part.get("color"))
                below = perception.parse_color(part.get("background"))
                if fg and below:
                    node = part["key"].rsplit(":", 1)[0] if form_control else "control"
                    by_part.setdefault(node, []).append((part["key"], perception.contrast_ratio(fg, below)))
            measured_parts = [max(values, key=lambda c: c[1]) for values in by_part.values()]
        else:
            measured_parts = []
        border = perception.parse_color(element.get("border_color"))
        bg = perception.parse_color(element.get("container_bg") or element.get("color_bg"))
        fill = perception.parse_color(element.get("color_bg"))
        container = perception.parse_color(element.get("container_bg"))
        candidates = []
        if not isinstance(paint, dict) and border and bg:
            candidates.append(("border", perception.contrast_ratio(border, bg)))
        if not isinstance(paint, dict) and fill and container and fill != container:
            candidates.append(("fill", perception.contrast_ratio(fill, container)))
        if not isinstance(paint, dict) and icon_only and (element.get("text") or "").strip():
            glyph, glyph_bg = perception.parse_color(element.get("color_fg")), perception.parse_color(element.get("color_bg"))
            if glyph and glyph_bg:
                candidates.append(("glyph", perception.contrast_ratio(glyph, glyph_bg)))
        if candidates:
            measured_parts.append(max(candidates, key=lambda c: c[1]))
        for best_kind, best in measured_parts:
            if best >= params.NON_TEXT_CONTRAST_MIN or element.get("enabled", True) is False:
                continue
            out.append(Observation(
                "PC-02", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                [element["id"]], element_key(element),
                {"name": "non_text_contrast", "value": round(best, 2), "unit": "ratio", "threshold": params.NON_TEXT_CONTRAST_MIN, "comparator": ">=", "kind": best_kind},
                False, "P2",
                f"'{element.get('name') or element.get('selector')}' 경계 대비 {best:.2f}:1 (기준 3:1).",
            ))
    return out


STATE_WORDS = (
    "가능", "불가", "마감", "매진", "완료", "실패", "성공", "오류", "에러", "정상", "위험", "경고", "주의",
    "선택됨", "사용 중", "품절", "예약됨", "비활성", "활성", "없음", "있음", "아군", "적군",
    "입금", "출금", "승인", "취소", "거절", "대기", "진행 중", "만료",
    "available", "full", "sold out", "error", "success", "warning", "ok", "fail", "done", "✓", "✔", "✕", "✗", "!",
)
_SIGNED_AMOUNT = re.compile(r"(^|\s)[+\-−]\s?\d")


def _state_cue(text: str) -> bool:
    lower = text.lower()
    return any(word in lower for word in STATE_WORDS) or bool(_SIGNED_AMOUNT.search(text))


def _colour_groups(ctx: Context) -> list[list[dict[str, Any]]]:
    """Same-shaped siblings (tag, role, size bucket, roles) that could encode state."""
    groups: dict[tuple, list[dict[str, Any]]] = {}
    for element in ctx.elements:
        if not _present(element) or element.get("paint", {}).get("decorative") or element.get("paint", {}).get("gaps") or (element.get("interactive") and element.get("enabled", True) is False):
            continue
        box = element["box"]
        key = (element.get("tag"), element.get("role"), round(box["w"] / 4), round(box["h"] / 4), tuple(sorted(_roles(element) - {"primary"})))
        groups.setdefault(key, []).append(element)
    return [g for g in groups.values() if len(g) >= 2]


def _paint_channels(element: dict[str, Any]) -> dict[str, str]:
    paint = element.get("paint")
    if isinstance(paint, dict):
        # Relative DOM part and SVG geometry must match. Different graphic shapes
        # provide another cue and cannot be inferred to be a colour-only state.
        return {f"{p['key']}|{p.get('shape') or ''}": p["color"] for p in paint.get("parts", [])}
    channels = {k: element.get(k) for k in ("color_bg", "border_color")}
    if (element.get("text") or "").strip():
        channels["color_fg"] = element.get("color_fg")
    return channels


def check_colour_only(ctx: Context) -> list[Observation]:
    """PC-03: states encoded by colour alone collapse under simulated CVD.

    Within a group of same-shaped elements, each colour channel (fill, border,
    text) is examined: when members split into clearly different colours under
    normal vision (dE00 >= 20) the colour is treated as a state code. Different
    labels (times, names) do not count as a state cue; explicit state words or
    icons do. Pairs are exempt when a >= 3:1 luminance difference separates them
    (WCAG G183).
    """
    kind = ctx.attrs.get("vision", {}).get("cvd", "none")
    if kind in (None, "none"):
        return []
    severity_level = float(ctx.attrs.get("vision", {}).get("cvd_severity") or 1.0)
    out: list[Observation] = []
    seen: set[tuple[str, str]] = set()
    for group in _colour_groups(ctx):
        channels = {e["id"]: _paint_channels(e) for e in group}
        for channel in sorted({k for member in channels.values() for k in member}):
            coloured = [(e, perception.parse_color(channels[e["id"]].get(channel))) for e in group]
            coloured = [(e, c) for e, c in coloured if c is not None]
            for i, (a, ca) in enumerate(coloured):
                for b, cb in coloured[i + 1:]:
                    pair = tuple(sorted((a["id"], b["id"])))
                    if pair in seen:
                        continue
                    normal = perception.color_difference(ca, cb)
                    if normal < params.CVD_DISTINCT_NORMAL_DE:
                        continue
                    # ARIA labels are not visible state redundancy.
                    text_a = (a.get("text") or (a.get("name") if "paint" not in a else "") or "").strip()
                    text_b = (b.get("text") or (b.get("name") if "paint" not in b else "") or "").strip()
                    if _state_cue(text_a) or _state_cue(text_b):
                        continue
                    state_contrast = perception.contrast_ratio(ca, cb)
                    simulated = perception.cvd_difference(ca, cb, kind, severity_level)
                    if simulated >= params.CVD_MARGINAL_DE or state_contrast >= params.CVD_STATE_CONTRAST_EXEMPT:
                        continue
                    seen.add(pair)
                    marginal = simulated >= params.CVD_CONFUSABLE_DE
                    # What the colour encodes matters: a status, warning or error state that a
                    # CVD user cannot tell apart is at least P2 (cross-review 2026-09-28).
                    status_like = bool((_roles(a) | _roles(b)) & {"status", "critical_message", "error_message"}) or \
                        {a.get("role"), b.get("role")} & {"status", "alert"}
                    out.append(Observation(
                        "PC-03", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                        [a["id"], b["id"]], element_key(a),
                        {"name": "cvd_delta_e2000", "value": round(simulated, 1), "unit": "dE00", "threshold": params.CVD_MARGINAL_DE, "comparator": ">=",
                         "normal_delta_e2000": round(normal, 1), "cvd": kind, "channel": channel, "state_contrast": round(state_contrast, 2),
                         "confidence": "low" if kind == "tritan" else "model"},
                        False, "P2" if (not marginal or status_like) else "P3",
                        f"'{text_a or a.get('selector')}'와 '{text_b or b.get('selector')}'의 상태 표시 색 차이가 {kind} 시뮬레이션에서 ΔE00 {simulated:.1f}로 사라집니다(색 외 상태 단서 확인 필요).",
                        "machado2009-ciede2000-v1",
                    ))
    return out


def check_text_size(ctx: Context) -> list[Observation]:
    """Legacy em-angle policy and explicit Canvas body estimates for XAG 101."""
    from .snapshot import validate_font_metrics

    out: list[Observation] = []
    vision = ctx.attrs.get("vision", {})
    presbyopic = bool(vision.get("presbyopia")) or vision.get("acuity") in ("reduced", "low")
    # The older-adult critical print size already reflects ageing at a normal reading
    # distance; it is not combined with a longer viewing distance (no double counting).
    viewing = _viewing_distance(ctx)
    comfortable = params.TEXT_MIN_ARCMIN_PRESBYOPIA if presbyopic or ctx.attrs.get("age_band") in ("60s", "70s+") else params.TEXT_MIN_ARCMIN
    is_game_surface = ctx.surface_kind == "game"
    for element in ctx.elements:
        text = (element.get("text") or "").strip()
        size = element.get("font_size_px")
        if not text or not size or not _present(element):
            continue
        size_mm = _point_mm(ctx, 0, float(size))[1]
        angle = perception.visual_angle_arcmin(size_mm, viewing)
        metrics = element.get("font_metrics")
        valid_metrics = isinstance(metrics, dict) and not validate_font_metrics(metrics)
        matched = valid_metrics and metrics.get("status") == "matched_font"
        metric_angles = {}
        if matched:
            heights = {"displayed_body": metrics["body_height_px"], **metrics["probes"]}
            metric_angles = {key: round(perception.visual_angle_arcmin(_point_mm(ctx, 0, height)[1], viewing), 3)
                             for key, height in heights.items()}
        provenance = {"metric": "css_em", "basis": "project_policy", "conformance": "not_assessed",
                      "font_metric_status": metrics.get("status") if valid_metrics else "missing_or_invalid",
                      "font_metric_angles_arcmin": metric_angles, "viewing_distance_mm": viewing,
                      "physical_scale_basis": "device_catalog_vertical_scale", "dom_ink_measured": False}
        hud = "hud" in _roles(element) or is_game_surface
        critical = bool(_roles(element) & {"error_message", "critical_message", "primary"}) or len(text) >= params.BODY_TEXT_MIN_CHARS
        form = getattr(ctx.device, "form_factor", "phone")
        floor_1080 = params.HUD_PLATFORM_MIN_PX_1080.get(form)
        if hud and floor_1080:
            display_px_h = (getattr(ctx.device, "display_px", (0, 0)) or (0, 0))[1] or 1080
            dpr = float(getattr(ctx.device, "dpr", 1.0) or 1.0)
            floor_css = floor_1080 * (display_px_h / 1080.0) / dpr
            if matched:
                body_height = metrics["body_height_px"]
                below = body_height < floor_css
                out.append(Observation(
                    "GM-01", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                    [element["id"]], element_key(element),
                    {**provenance, "name": "hud_displayed_body_height_estimate", "value": body_height,
                     "metric": "displayed_text_ink_body", "unit": "css_px", "threshold": round(floor_css, 3), "comparator": ">=",
                     "guideline": "XAG 101", "method": metrics["method"], "basis": "canvas_font_estimate",
                     "limitations": metrics["limitations"], "font_size_px": size, "reference_floor_px_1080": floor_1080,
                     "display_height_px": display_px_h, "device_dpr": dpr},
                    not below, "P2" if below else None,
                    f"HUD 글자 '{text[:20]}'의 Canvas 본문 높이 추정 {body_height:.2f}px가 XAG 101 비교값 {floor_css:.2f}px"
                    + ("보다 작습니다." if below else " 이상입니다.") + " 화면 글리프 픽셀의 적합성 확인은 필요합니다.",
                    "xag-101-canvas-estimate-v1", extra={"verdict": "estimated_fail" if below else "estimated_pass"},
                ))
            else:
                # Explicit unsupported captures abstain. Old snapshots retain their
                # small-em warning, with no implied rendered-body or XAG verdict.
                legacy_small = metrics is None and float(size) < floor_css
                out.append(Observation(
                    "GM-01", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                    [element["id"]], element_key(element),
                    {**provenance, "name": "hud_body_height_unverified", "value": None, "unit": "css_px",
                     "threshold": round(floor_css, 3), "comparator": ">=", "guideline": "XAG 101",
                     "css_em_proxy_px": size, "proxy_below_floor": float(size) < floor_css,
                     "limitations": metrics.get("limitations", []) if valid_metrics else ["font_metrics_missing_or_invalid"]},
                    False, None,
                    f"HUD 글자 '{text[:20]}'의 표시 본문 높이를 확인할 수 없어 XAG 101 판정을 보류했습니다.",
                    "xag-101-unverified-v1", extra={"verdict": "inconclusive"},
                ))
                if legacy_small:
                    out.append(Observation(
                        "GM-01", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                        [element["id"]], element_key(element),
                        {**provenance, "name": "hud_text_css_em_proxy", "value": size, "unit": "css_px",
                         "threshold": round(floor_css, 3), "comparator": ">=", "tier": "legacy_em_policy"},
                        False, "P2", f"HUD 글자 '{text[:20]}'의 CSS em {size}px가 기존 프로젝트 비교값 {floor_css:.2f}px보다 작습니다. 표시 본문 높이 확인은 필요합니다.",
                        "hud-em-policy-v1",
                    ))
                if metrics is not None:
                    continue
        check_id = "GM-01" if hud else "PC-04"
        if form in ("phone", "foldable", "tablet", "handheld_console") and float(size) < params.TEXT_PLATFORM_MIN_CSS_PX_MOBILE:
            severity = "P2" if (hud or critical) else "P3"
            out.append(Observation(
                check_id, ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
                [element["id"]], element_key(element),
                {**provenance, "name": "font_size_css_px", "value": size, "unit": "css_px", "threshold": params.TEXT_PLATFORM_MIN_CSS_PX_MOBILE, "comparator": ">=",
                 "tier": "platform_minimum"},
                False, severity,
                f"'{text[:30]}'의 CSS em {size}px가 프로젝트의 모바일 비교값 {params.TEXT_PLATFORM_MIN_CSS_PX_MOBILE:.0f}px보다 작습니다. Apple 플랫폼 포인트 적합성은 별도 확인이 필요합니다.",
                "platform-min-text",
            ))
            continue
        if angle < params.TEXT_FLOOR_ARCMIN:
            severity, threshold, tier = ("P1" if critical and _roles(element) & {"error_message", "critical_message"} else "P2"), params.TEXT_FLOOR_ARCMIN, "floor"
        elif (angle < comfortable and not hud and cognition.reading_units(text)[0] >= params.BODY_TEXT_MIN_CHARS
              and not element.get("interactive") and element.get("role") not in ("heading", "button", "link", "cell", "columnheader", "rowheader")):
            # Preserve the legacy running-prose policy without claiming that em
            # is the source paper's glyph metric or calibrated reading speed.
            severity, threshold, tier = "P3", comfortable, "critical_print_size"
        else:
            continue
        out.append(Observation(
            check_id, ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
            [element["id"]], element_key(element),
            {**provenance, "name": "font_visual_angle_arcmin", "value": round(angle, 1), "unit": "arcmin", "threshold": threshold, "comparator": ">=",
             "tier": tier, "font_size_px": size, "viewing_distance_mm": viewing},
            False, severity,
            f"'{text[:30]}'의 CSS em({size}px≈{size_mm:.1f}mm)이 가정한 {viewing/10:.0f}cm 거리에서 {angle:.0f}′로 프로젝트 비교값 {threshold:.1f}′보다 작습니다. 실제 글리프 높이와 독서 수행은 별도 확인이 필요합니다.",
            "visual-angle-v2",
        ))
    return out


# ---------------------------------------------------------------- cognition

def check_choice_overload(ctx: Context) -> list[Observation]:
    out: list[Observation] = []
    groups: dict[tuple, list[dict[str, Any]]] = {}
    # The choice set is the whole rendered group the user scrolls through, including
    # members below the fold or under a sticky bar; only a modal hides the rest.
    members_all = [e for e in ctx.elements if e.get("interactive") and e.get("visible", True) and e.get("enabled", True)
                   and not e.get("inert_by_modal") and e["box"].get("w", 0) > 0 and e["box"].get("h", 0) > 0]
    for element in members_all:
        box = element["box"]
        # Same look, not just a similar size: unrelated controls (a back chevron, date
        # chips and a stepper) were merged by size buckets alone (adjudication 2026-09-28).
        # Choices are siblings in one container; when the driver gives no container id,
        # fall back to identical fill and border.
        parent = (element.get("ancestor_ids") or [None])[0]
        look = ("parent", parent) if parent else ("look", element.get("color_bg"), element.get("border_color"))
        key = (element.get("tag"), element.get("role"), round(box["w"] / 8), round(box["h"] / 8), element.get("font_weight"),
               element.get("font_size_px"), look)
        groups.setdefault(key, []).append(element)
    for members in groups.values():
        if len(members) <= params.CHOICE_OVERLOAD_MAX:
            continue
        labels = [(m.get("text") or m.get("name") or "").strip() for m in members]
        if sum(1 for t in labels if len(t) == 1 and t.isdigit()) >= 8:
            continue  # a numeric keypad: recall of a known code, not a choice among options
        decision_ms = cognition.hick_hyman_ms(len(members))
        out.append(Observation(
            "CG-01", ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"),
            [m["id"] for m in members[:12]], element_key(members[0]),
            {"name": "equal_choices", "value": len(members), "unit": "count", "threshold": params.CHOICE_OVERLOAD_MAX, "comparator": "<=",
             "hick_decision_ms": round(decision_ms)},
            False, "P3",
            f"동일한 모양의 선택지 {len(members)}개(힉-하이먼 예측 결정 시간 약 {decision_ms/1000:.1f}초).",
            "hick-hyman-v1",
        ))
    return out


def _native_state_ack(step: dict[str, Any]) -> dict[str, Any] | None:
    """Bounded re-validation of a step's ``feedback_native_state`` before CG-03 trusts it.

    The driver records it, the run validator rejects malformed shapes at import, and
    this predicate re-checks defensively (analyze may run on in-memory runs): source,
    via/type/event enums, real booleans, changed == (after != before), a finite
    latency >= 0 that agrees with the event's presence, a stable end state, and a
    latency inside the step's observed feedback window. Anything else is not a
    native acknowledgment — it falls through to the ordinary CG-03 finding.
    """
    native = step.get("feedback_native_state")
    if native is None or validate_native_state(native, step):
        return None
    if native.get("event") is None or native.get("stable") is False:
        return None
    return native


def check_run_timing(run: dict[str, Any], profile: dict[str, Any], device: Any, snapshots: dict[str, dict[str, Any]], scenario: dict[str, Any] | None) -> list[Observation]:
    """Checks that need the whole run: feedback latency, transient text, QTE windows, flashes."""
    out: list[Observation] = []
    attrs = profile.get("attributes", {})
    run_id, pid = run["run_id"], profile["profile_id"]
    for step in run.get("steps", []):
        action = (step.get("action") or {}).get("action")
        if action not in ("tap", "click", "double_tap", "press") or step.get("result") != "ok":
            continue
        latency = step.get("feedback_latency_ms")
        band = cognition.latency_band(latency)
        target_id = step.get("target_element_id") or ""
        before_snap = snapshots.get(step.get("before") or "", {})
        before_target = next((e for e in before_snap.get("elements", []) if e.get("id") == target_id), None)
        if before_target is not None and (before_target.get("enabled") is False or before_target.get("visible") is False or not _usable(before_target)):
            continue  # the target was not actionable (closed timed prompt, disabled, covered): no feedback is expected
        native = _native_state_ack(step)
        native_evidence = step.get("feedback_native_state")
        native_control = native_evidence is not None and not validate_native_state(native_evidence, step)
        if band == "no_feedback" and native_control and native_evidence["type"] == "radio" and native_evidence["before"] is True and native_evidence["changed"] is False and native_evidence.get("stable") is not False:
            continue  # reselecting the same native radio leaves selection unchanged: no acknowledgment is expected
        if band == "no_feedback" and before_target is not None and not native_control and before_target.get("role") not in ("checkbox", "radio") and (before_target.get("role") in ("textbox", "searchbox", "combobox", "spinbutton")
                                                                   or before_target.get("tag") in ("input", "textarea", "select")):
            continue  # a field's feedback is its caret and focus ring, which may already be showing
        target_roles = set((before_target or {}).get("roles") or [])
        if band == "no_feedback" and _window_closed_at(run, (step.get("action") or {}).get("target"), step.get("t_start_ms"), target_roles):
            continue  # the tap came after the timed prompt closed: silence is the game's correct response
        after = snapshots.get(step.get("after") or "", {})
        target = before_target  # ids belong to the step's before snapshot
        key = element_key(target) if target else f"{(step.get('action') or {}).get('target', '')}|step-target"
        severity = None
        if band == "needs_progress_indicator":
            severity = "P2"
        elif band == "attention_lost":
            severity = "P1"
        elif band == "no_feedback" and action in ("tap", "click"):
            severity = "P2"
        elif band == "noticeable" and latency is not None and latency > params.LATENCY_DOHERTY_MS:
            severity = "P3"
        if band == "no_feedback" and severity == "P2" and native and native.get("changed") is True:
            # The action activated a native checkbox/radio: its boolean truly changed and a
            # trusted input/change event for that same control, taken at event time, was
            # timed inside the observed window. That is a state (semantic) acknowledgment
            # of the activation, classified with the same response-time bands as any other
            # acknowledgment — never a generic exemption for native controls, and not a
            # calibrated claim of visible paint, perceptibility or a screen-reader
            # announcement (those stay with the DOM/visual evidence, unmeasured here).
            ack_ms = native["latency_ms"]
            ack_band = cognition.latency_band(ack_ms)
            if ack_ms <= params.LATENCY_DOHERTY_MS:
                ack_severity = None
            elif ack_ms <= params.LATENCY_FLOW_MS:
                ack_severity = "P3"
            elif ack_ms <= params.LATENCY_ATTENTION_MS:
                ack_severity = "P2"
            else:
                ack_severity = "P1"
            out.append(Observation(
                "CG-03", run_id, pid, step.get("after"), step.get("step_index"),
                [target_id] if target_id else [], key,
                {"name": "feedback_latency_ms", "value": None, "unit": "ms", "threshold": params.LATENCY_FLOW_MS, "comparator": "<=", "band": band,
                 "acknowledgment": "native_state_change", "acknowledgment_ms": ack_ms, "acknowledgment_band": ack_band,
                 "native_state": [native.get("before"), native.get("after")],
                 "visible_paint_calibrated": False},
                ack_severity is None, ack_severity,
                (f"{step.get('step_index')}단계 조작에서 체크박스/라디오 상태가 {native.get('before')}→{native.get('after')}로 "
                 f"바뀌었고 {ack_ms}ms에 신뢰 입력 이벤트가 확인되었음. "
                 "상태 응답만 측정했으며 화면의 선택 표시·인지 가능성·스크린리더 안내는 별도 미측정.") if ack_severity is None else
                (f"{step.get('step_index')}단계 조작에서 체크박스/라디오 상태가 {native.get('before')}→{native.get('after')}로 "
                 f"바뀌었고 상태 응답이 {ack_ms}ms에 확인됨({ack_band})."),
            ))
            continue
        out.append(Observation(
            "CG-03", run_id, pid, step.get("after"), step.get("step_index"),
            [target_id] if target_id else [], key,
            {"name": "feedback_latency_ms", "value": latency, "unit": "ms", "threshold": params.LATENCY_FLOW_MS, "comparator": "<=", "band": band},
            severity is None, severity,
            f"{step.get('step_index')}단계 조작 후 첫 화면 변화까지 {latency if latency is not None else '없음'}ms ({band}).",
        ))
    age = attrs.get("age_band", "30s")
    reading_rate = float(params.READING_SLOW_SYLLABLES_PER_MIN.get(age, 330))
    windows = {w.get("id"): w for w in (scenario or {}).get("timing_windows", [])}
    surface_game = any(s.get("surface", {}).get("kind") == "game" for s in snapshots.values())
    viewport_area = 0.0
    for snap in snapshots.values():
        vp = snap.get("device", {}).get("viewport_css") or [0, 0]
        viewport_area = max(viewport_area, float(vp[0]) * float(vp[1]))
    for measured in run.get("timing_windows", []):
        declared = windows.get(measured.get("id"), {})
        selector = declared.get("selector") or measured.get("selector")
        element = _element_for_selector(snapshots, selector)
        # A declared timed input is scored by GM-03 even when it appears many times
        # (QTE chains); only undeclared or decorative windows are screened as flashes.
        flash = None if (declared.get("kind") or measured.get("kind")) == "qte" else _dom_flash(measured, element, viewport_area, device, attrs)
        if flash is not None:
            out.append(Observation(
                "GM-04", run_id, pid, None, None, [element["id"]] if element else [], f"{selector}|{measured.get('id')}",
                flash["measurement"], flash["severity"] is None, flash["severity"], flash["message"], "dom-flash-rate-v1",
            ))
            continue
        durations = measured.get("intervals_ms") or measured.get("visible_ms")
        if isinstance(durations, (int, float)):
            durations = [durations]
        durations = [d for d in (durations or []) if isinstance(d, (int, float))]
        if not durations:
            continue
        shortest = min(durations)
        kind = declared.get("kind") or measured.get("kind") or _infer_window_kind(element, measured, run, selector, surface_game)
        if kind not in ("qte", "transient_text"):
            continue  # decorative effects (score pop-ups, sparkles) are not messages or inputs
        key = f"{selector or measured.get('id')}|{measured.get('id')}"
        if kind == "qte":
            rt = float(attrs.get("reaction_time_ms") or params.choice_reaction_ms_for_age("30s"))
            rt95 = game.reaction_time_quantile_ms(rt, rt * params.RT_CV, 0.95)
            latency = params.INPUT_LATENCY_MS.get(getattr(device, "input", "touch"), 80)
            margin = game.timing_window_margin_ms(shortest, rt95, latency)
            # The window itself is measured; the reaction times are modelled. P1 only when
            # even a typical young adult (median, 20s) cannot answer in time; a miss that
            # holds only for this profile's 95th percentile stays P2.
            young = float(params.choice_reaction_ms_for_age("20s"))
            margin_typical = game.timing_window_margin_ms(shortest, young, latency)
            failed = margin < 0
            severity = ("P1" if margin_typical < 0 else "P2") if failed else None
            out.append(Observation(
                "GM-03", run_id, pid, None, None, [], key,
                {"name": "timing_margin_ms", "value": round(margin), "unit": "ms", "threshold": 0, "comparator": ">=",
                 "window_ms": shortest, "reaction_p95_ms": round(rt95), "margin_typical_young_ms": round(margin_typical)},
                not failed, severity,
                f"입력 제한 시간 {shortest:.0f}ms < 이 프로필의 반응 95백분위 {rt95:.0f}ms + 동작/지연.",
                "reaction-window-v1",
            ))
        else:
            text = declared.get("text") or measured.get("text") or ""
            has_action = bool(declared.get("has_action") or measured.get("has_action"))
            need = cognition.min_display_ms(text, reading_rate) if text else params.TOAST_FLOOR_MS
            appearances = int(measured.get("appearances") or 0)
            offscreen = appearances > 0 and int(measured.get("offscreen_appearances") or 0) >= appearances
            failed = shortest + params.TIMING_JITTER_MS < need or has_action or offscreen
            critical = bool(element and _roles(element) & {"error_message", "critical_message"})
            severity = ("P1" if (has_action or (offscreen and critical)) else "P2") if failed else None
            out.append(Observation(
                "CG-02", run_id, pid, None, None, [], key,
                {"name": "visible_ms", "value": shortest, "unit": "ms", "threshold": round(need), "comparator": ">=", "chars": len(text), "offscreen": offscreen,
                 "reading_rate_syll_per_min": reading_rate, "has_action": has_action},
                not failed, severity,
                f"'{text[:30]}' 메시지가 {shortest:.0f}ms만 표시됨(느린 독자 기준 읽기 필요 시간 약 {need:.0f}ms)"
                + (" — 동작이 포함된 메시지가 자동으로 사라짐(WCAG 2.2.1)." if has_action else ".")
                + (" 게다가 화면 밖(뷰포트 바깥)에 나타나 보이지 않았습니다." if offscreen else ""),
                "reading-time-v2",
            ))
    samples = run.get("flash_samples") or []
    if samples:
        flash = _frame_flash(run, samples, device, attrs)
        out.append(Observation(
            "GM-04", run_id, pid, None, None, [], "viewport|flash",
            flash["measurement"], flash["severity"] is None, flash["severity"], flash["message"], flash["model"],
        ))
    # GM-06 (mashing) emits nothing until a press-rate and hold-time sweep measures what
    # the game demands; counting the script's presses measured the script (GQA-13).
    for note in run.get("persona_notes", []):
        if not note.get("confusion"):
            continue
        failure_class = note.get("failure_class", "unknown")
        if failure_class in ("agent_limitation", "environment"):
            continue  # a run limitation, not a UX finding (recorded in the report as a limitation)
        # Judgment-only findings are anchored to the element the note is about (LAT-01),
        # so notes from different runs at the same element can be matched. Severity P3;
        # swarm.aggregate raises a unit to P2 and out of the hypothesis tier only when
        # runs of different model families or input channels noted it (LAT-03).
        selectors = [x for x in (note.get("anchor_selectors") or []) if isinstance(x, str)]
        anchor_key = selectors[0] if selectors else (note.get("screen_key") or f"step-{note.get('step_index')}")
        agent = run.get("agent") or {}
        out.append(Observation(
            "PJ-01", run_id, pid, note.get("anchor_snapshot_id"), note.get("step_index"), list(note.get("anchor_element_ids") or []),
            f"{anchor_key}|persona-note",
            {"name": "persona_confusion", "value": True, "unit": "flag", "threshold": False, "comparator": "==",
             "failure_class": failure_class, "corroborated_claimed": bool(note.get("corroborated_claimed", note.get("corroborated"))),
             "screen_key": note.get("screen_key")},
            False, "P3",
            f"페르소나 기록(시뮬레이션·실제 사용자 발화 아님): 의도 '{note.get('intent', '')}' / 기대 '{note.get('expected', '')}' / 화면 '{note.get('observed', '')}'",
            "llm-persona-note",
            {"agent": {"model_family": agent.get("model_family"), "input_channel": agent.get("input_channel"), "model": agent.get("model")},
             "anchor_selectors": selectors},
        ))
    return out


def _window_closed_at(run: dict[str, Any], target: Any, t_ms: Any, target_roles: set[str] | None = None) -> bool:
    """True when the timed prompt the tap answered had already closed at ``t_ms``.

    A window matches the tap when it is bound to the same selector, or when the target
    is a timed/game control and the window is a QTE.
    """
    if not isinstance(target, str) or not isinstance(t_ms, (int, float)):
        return False
    timed_target = bool((target_roles or set()) & {"timed", "game_control"})
    matched = False
    for w in run.get("timing_windows", []):
        bound = w.get("selector") == target or w.get("id") == target or f"hotspot:{w.get('id')}" == target
        if not (bound or (timed_target and w.get("kind") == "qte")):
            continue
        starts = w.get("starts_ms") or []
        durations = w.get("intervals_ms") or ([w["visible_ms"]] if isinstance(w.get("visible_ms"), (int, float)) else [])
        if not starts or not durations:
            continue
        matched = True
        if any(s <= t_ms <= s + d for s, d in zip(starts, durations)):
            return False
    return matched


def _element_for_selector(snapshots: dict[str, dict[str, Any]], selector: str | None) -> dict[str, Any] | None:
    """The largest visible rendering of selector across the run's snapshots."""
    if not selector:
        return None
    best = None
    for snap in snapshots.values():
        for element in snap.get("elements", []):
            if element.get("selector") != selector:
                continue
            box = element.get("box") or {}
            area = float(box.get("w", 0)) * float(box.get("h", 0))
            if best is None or area > best[0]:
                best = (area, element)
    return best[1] if best else None


def _infer_window_kind(element: dict[str, Any] | None, measured: dict[str, Any], run: dict[str, Any], selector: str | None, game_surface: bool) -> str:
    """Kind for a timing window declared without one.

    A window the run had to act on (tapped/clicked target) or an interactive/timed
    element on a game surface is a timed input; a window showing a readable message
    (>= 8 characters) is transient text; anything else is decorative.
    """
    acted = any((s.get("action") or {}).get("target") == selector for s in run.get("steps", []))
    roles = set((element or {}).get("roles") or [])
    interactive = bool((element or {}).get("interactive"))
    text = (measured.get("text") or (element or {}).get("text") or "").strip()
    if acted or (game_surface and (interactive or "timed" in roles) and len(text) < 8):
        return "qte"
    if game_surface and not roles & {"status", "critical_message", "error_message"}:
        # In games, short-lived text (hit indicators, score pops) usually duplicates the
        # persistent HUD; only declared messages count as text the player must read.
        return "decorative"
    if len(text) >= 8:
        return "transient_text"
    return "decorative"


def _saturated_red(colour: tuple[float, float, float] | None) -> bool:
    """WCAG saturated red on linear R, G, B (as the driver's pixel test): R/(R+G+B) >= 0.8 and (R-G-B)*320 > 20."""
    if not colour:
        return False
    r, g, b = (perception.srgb_to_linear(c) for c in colour)
    total = r + g + b
    return total > 0 and r >= params.FLASH_RED_RATIO * total and r - g - b > params.FLASH_RED_EXCESS


def _dom_flash(measured: dict[str, Any], element: dict[str, Any] | None, viewport_area: float, device: Any, attrs: dict[str, Any]) -> dict[str, Any] | None:
    """WCAG 2.3.1 screening from DOM visibility toggles (in-page 16 ms polling).

    Frame sampling can alias fast flashes; an element that appears and disappears
    repeatedly is a measured flash source. A pair of opposing transitions (appear +
    disappear) is one flash. The element must cover the WCAG area (25 % of a 10 deg
    field, i.e. 0.006 sr, or the whole viewport fraction on unknown geometry) and be
    either saturated red (red flash) or differ in luminance by >= 10 % from what it covers.
    """
    starts = [float(t) for t in (measured.get("starts_ms") or []) if isinstance(t, (int, float))]
    appearances = int(measured.get("appearances") or len(starts))
    if appearances < 4 or len(starts) < 4:
        return None
    if element is None and isinstance(measured.get("appear_box"), dict):
        # Captured by the driver's poll at appearance (the element flashed between snapshots).
        element = {"id": "", "selector": measured.get("selector"), "box": measured["appear_box"],
                   "color_bg": measured.get("appear_bg"), "container_bg": None}
    if element is None:
        return None
    best = 0
    for i, t0 in enumerate(starts):
        best = max(best, sum(1 for t in starts[i:] if t - t0 < 1000.0))
    box = element.get("box") or {}
    fraction = (float(box.get("w", 0)) * float(box.get("h", 0))) / viewport_area if viewport_area else 0.0
    display = getattr(device, "display_mm", None) or (0, 0)
    viewing = float(attrs.get("vision", {}).get("viewing_distance_mm") or getattr(device, "viewing_distance_mm", 300))
    big = game.flash_area_exceeds(fraction, display[0], display[1], viewing) if display[0] else fraction > 0.25
    colour = perception.parse_color(element.get("color_bg"))
    below = perception.parse_color(element.get("container_bg"))
    red = _saturated_red(colour)
    lum_delta = abs(perception.relative_luminance(colour) - perception.relative_luminance(below)) if colour and below else None
    strong = red or lum_delta is None or lum_delta >= params.FLASH_DELTA
    failed = best > 3 and big and strong
    severity = "P0" if failed else None
    return {
        "severity": severity,
        "measurement": {"name": "flashes_per_second", "value": best, "unit": "flashes/s", "threshold": 3, "comparator": "<=",
                        "area_fraction": round(fraction, 3), "area_exceeds": big, "red_flash": red,
                        "luminance_delta": round(lum_delta, 3) if lum_delta is not None else None, "source": "dom-visibility-poll"},
        "message": f"'{element.get('selector')}'이(가) 1초 안에 최대 {best}회 나타났다 사라짐(화면의 {fraction*100:.0f}%"
        + (", 채도 높은 빨강" if red else "") + ")." + (" 광과민성 발작 위험 — 인증 도구로 재검사하세요." if failed else ""),
    }


def _frame_flash(run: dict[str, Any], samples: list[dict[str, Any]], device: Any, attrs: dict[str, Any]) -> dict[str, Any]:
    """WCAG 2.3.1 screening from the driver's flash samples (GM-04, whole run).

    Runs with a block grid (``flash_sampling.block_grid``) get block-based general-
    and red-flash detection within 10 degree fields (game.analyse_block_flashes);
    older runs fall back to the whole-viewport mean luminance. A pass is reported
    as ``inconclusive`` when the sampling did not observe the run well enough
    (capture rate, unsampled waits, truncation).
    """
    sampling = run.get("flash_sampling") if isinstance(run.get("flash_sampling"), dict) else {}
    coverage = game.sampling_coverage(samples, run.get("steps") or [], sampling)
    problems = game.coverage_problems(coverage)
    viewing = float(attrs.get("vision", {}).get("viewing_distance_mm") or getattr(device, "viewing_distance_mm", 300))
    grid = sampling.get("block_grid")
    extended = False
    if game.has_block_grid(samples, grid):
        try:
            from .devices import mm_per_css_px
            pitch: tuple[float, float] | None = (mm_per_css_px(device, "x"), mm_per_css_px(device, "y"))
        except (KeyError, TypeError, ValueError, ZeroDivisionError, AttributeError):
            pitch = None  # unknown panel geometry: WCAG 341 x 256 px proxy for the 10 degree field
        res = game.analyse_block_flashes(samples, grid, pitch, viewing)
        failed, extended = res["failed"], res["extended"]
        kind = max(("general", "red"), key=lambda k: (res[k]["failed"], res[k]["extended_failed"], res[k]["area_sr"]))
        ext_sr = max(res[kind]["sustained_5s_area_sr"], res[kind]["iris_extended_area_sr"])
        worst = res[kind]
        value = worst["field_flashes_per_s"] if worst["area_sr"] > 0 else max(res["general"]["max_flashes_per_s"], res["red"]["max_flashes_per_s"])
        field_sr = 2.0 * math.pi * (1.0 - math.cos(math.radians(params.FLASH_FIELD_DEG / 2.0)))
        measurement: dict[str, Any] = {
            "name": "flashes_per_second", "value": value, "unit": "flashes/s", "threshold": 3, "comparator": "<=",
            "method": res["method"], "flash_kind": kind if worst["area_sr"] > 0 else None,
            "area_sr": worst["area_sr"], "area_threshold_sr": params.FLASH_AREA_SR, "area_exceeds": failed,
            "field_fraction": round(worst["area_sr"] / field_sr, 3), "red_flash": res["red"]["failed"],
            "extended_failure": extended, "sustained_5s": res["sustained_5s"], "iris_extended": res["iris_extended"],
            "iris_warning": res["iris_warning"], "general": res["general"], "red": res["red"],
            "grid": res["grid"], "block_css": res["block_css"], "geometry": res["geometry"],
            "viewing_distance_mm": res["viewing_distance_mm"], "motion_samples": res["moved_samples"],
        }
        where = ""
        if worst["at_ms"] is not None:
            step = next((s.get("step_index") for s in run.get("steps") or []
                         if isinstance(s.get("t_start_ms"), (int, float)) and s["t_start_ms"] <= worst["at_ms"] <= (s.get("t_end_ms") or s["t_start_ms"])), 0)
            measurement["step_index"] = step
            where = f", {worst['at_ms'] / 1000:.1f}초({step}단계) 화면 ({worst['field_center_css'][0]:.0f}, {worst['field_center_css'][1]:.0f}) px 부근"
        label = "적색 섬광" if kind == "red" else "일반 섬광"
        if failed:
            detail = (f"{label}: 초당 3회 초과 깜빡이는 영역이 10° 시야 안에서 {worst['area_sr']:.4f} sr"
                      f"(기준 {params.FLASH_AREA_SR} sr, 시야의 {measurement['field_fraction'] * 100:.0f}%)를 차지함{where}.")
        elif extended:
            rules = [r for r, on in (("5초 안에 10회 이상(초당 2회 이상 지속)", worst["sustained_5s"]),
                                     ("최근 5초 중 4초 이상 초당 2–3회(1초 전이 4–6회, EA IRIS 확장 실패 규칙)", worst["iris_extended"])) if on]
            detail = (f"{label}: {' 또는 '.join(rules)} 깜빡이는 영역이 10° 시야 안에서 {ext_sr:.4f} sr"
                      f"(기준 {params.FLASH_AREA_SR} sr)를 차지함{where}.")
        else:
            detail = (f"초당 3회를 넘게 깜빡이는 영역이 10° 시야 기준 면적을 넘지 않음(최대 {worst['area_sr']:.4f} sr / 기준 {params.FLASH_AREA_SR} sr, "
                      f"국소 최대 초당 {max(res['general']['max_flashes_per_s'], res['red']['max_flashes_per_s']):.1f}회).")
        model = "block-flash-screen-v1"
    else:
        stats = game.count_general_flashes(samples)
        display = getattr(device, "display_mm", None) or (0, 0)
        big = game.flash_area_exceeds(stats["max_area_fraction"], display[0], display[1], viewing) if display[0] else stats["max_area_fraction"] > 0.25
        failed = stats["max_flashes_per_window"] > 3 and big
        extended = not failed and stats["extended"] and big
        measurement = {"name": "flashes_per_second", "value": stats["max_flashes_per_window"], "unit": "flashes/s", "threshold": 3, "comparator": "<=",
                       "method": "viewport-mean-v1", "area_fraction": round(stats["max_area_fraction"], 3), "area_exceeds": big,
                       "flashes_per_5s": stats["max_flashes_per_5s"], "extended_failure": extended}
        detail = (f"1초 창에서 최대 {stats['max_flashes_per_window']:.1f}회 섬광(5초 창 {stats['max_flashes_per_5s']:.1f}회), 변화 면적 "
                  f"{stats['max_area_fraction']*100:.0f}% — 블록 격자가 없는 실행이라 화면 전체 평균 휘도로만 판정(국소·역위상·적색 섬광은 못 봄).")
        model = "general-flash-screen-v1"
    verdict = "fail" if failed else ("extended_fail" if extended else ("inconclusive" if problems else "pass"))
    measurement["verdict"] = verdict
    measurement["coverage"] = coverage
    if problems:
        measurement["coverage_problems"] = problems
    gap = coverage["max_gap_ms"]
    sampled = (f" 표본 {coverage['sampled_ms'] / 1000:.1f}초·평균 {coverage['mean_fps'] or 0:.0f} fps·최대 간격 {gap or 0:.0f} ms"
               + (f"(>{params.FLASH_MAX_GAP_MS:.0f} ms: 그 사이의 짧은 섬광은 놓칠 수 있음)" if gap and gap > params.FLASH_MAX_GAP_MS else "") + ".")
    message = detail + sampled
    if verdict == "inconclusive":
        reasons = {
            "low_fps": f"평균 표본 {coverage['mean_fps'] or 0:.0f} fps < {params.FLASH_MIN_FPS:.0f} fps",
            "unsampled_steps": f"{', '.join(str(s) for s in coverage['unsampled_animating_steps'])}단계(대기·움직이는 화면) 동안 표본 없음",
            "truncated": "드라이버 용량 한도로 표본 수집이 중간에 멈춤",
        }
        message = ("판정 불가(inconclusive, 통과 아님): " + "; ".join(reasons[p] for p in problems)
                   + ". 관찰한 구간에서는 " + detail + sampled)
    if failed or extended:
        message += (" EA IRIS는 인증 도구가 아니며(README 면책), 기본 설정은 화면의 25 % 이상이 바뀌어야 전이로 세므로 국소 섬광은 IRIS를 통과할 수 있습니다."
                    " IRIS 통과가 이 판정을 뒤집지 않습니다. 방송·인증 목적이면 Harding FPA 같은 인증 절차를 따로 밟으세요.")
    return {"measurement": measurement, "severity": "P0" if failed else ("P1" if extended else None), "message": message, "model": model}


_LABEL_NOISE = re.compile(r"[\W_]+", re.UNICODE)
# SM-08: tags that are controls by themselves (a label activates its control) and
# widget roles a click may legitimately land on.
NATIVE_CONTROL_TAGS = frozenset({"a", "button", "input", "select", "textarea", "summary", "label", "option", "canvas", "video", "audio",
                                 "details", "hotspot", "iframe"})
WIDGET_ROLES = frozenset({"button", "link", "checkbox", "radio", "switch", "tab", "menuitem", "menuitemcheckbox", "menuitemradio", "option",
                          "slider", "spinbutton", "textbox", "searchbox", "combobox", "listbox", "treeitem", "gridcell", "scrollbar"})


def _sm08(run_id: str, profile_id: str, snapshot_id: str | None, step_index: int | None, element_ids: list[str], key: str,
          role: str | None, tag: str | None, label: str, context: list[str]) -> Observation:
    return Observation(
        "SM-08", run_id, profile_id, snapshot_id, step_index, element_ids, key,
        {"name": "role_focusable", "value": {"role": role, "tag": tag, "focusable": False}, "unit": "state",
         "threshold": "native control, widget role or tabindex >= 0", "comparator": "in"},
        False, "P1",
        f"과업에서 누른 '{label[:30]}'이(가) 버튼·선택 요소로 선언되지 않았고 키보드로 초점을 받을 수 없습니다. 키보드·스크린리더 사용자는 이 단계를 마칠 수 없습니다(WCAG 2.1.1, 4.1.2).",
        extra={"context_selectors": context} if context else {},
    )


def check_clicked_controls(run: dict[str, Any], profile: dict[str, Any], snapshots: dict[str, dict[str, Any]] | None = None) -> list[Observation]:
    """SM-08 from the steps: a tap or click landed on an element that is not a control, is
    not inside one within five levels, and holds none (the driver's ``target_control``).
    The click evidences the handler only when it did something: a click with no
    feedback at all (no mutation, input event, navigation or visual change) is not
    evidence (persona agents tap static text). Game surfaces, scenario hotspots, game
    controls and content hidden from assistive technology (a dialog's scrim) are
    exempt, as in the snapshot rule."""
    out: list[Observation] = []
    seen: set[str] = set()
    if (run.get("surface") or {}).get("kind") == "game":
        return out
    for st in run.get("steps") or []:
        c = st.get("target_control")
        if not isinstance(c, dict) or st.get("result") != "ok" or c.get("control") or c.get("contains_control") or c.get("tag") in ("html", "body"):
            continue
        if c.get("hidden") or (st.get("feedback_source") is None and st.get("feedback_latency_ms") is None):
            continue
        target = (st.get("action") or {}).get("target")
        if isinstance(target, str) and target.startswith("hotspot:"):
            continue
        snap = (snapshots or {}).get(st.get("before") or "")
        element = next((e for e in (snap or {}).get("elements", []) if c.get("dom_id") and e.get("dom_id") == c["dom_id"]), None)
        if element is not None and ("game_control" in _roles(element) or (element.get("a11y") or {}).get("hidden")):
            continue
        selector = f"#{c['dom_id']}" if c.get("dom_id") else (target if isinstance(target, str) else f"{c.get('tag')}@{st.get('point')}")
        key = element_key(element) if element else f"{selector}|{c.get('text') or ''}"
        if key in seen:
            continue
        seen.add(key)
        out.append(_sm08(run["run_id"], profile["profile_id"], st.get("before"), st.get("step_index"), [element["id"]] if element else [], key,
                         c.get("role"), c.get("tag"), c.get("text") or selector, [f"#{a}" for a in c.get("ancestor_ids") or [] if a]))
    return out


def _inside(inner: dict[str, float], outer: dict[str, float]) -> bool:
    return (inner.get("w", 0) > 0 and inner.get("h", 0) > 0 and inner["x"] >= outer["x"] - 1 and inner["y"] >= outer["y"] - 1
            and inner["x"] + inner["w"] <= outer["x"] + outer["w"] + 1 and inner["y"] + inner["h"] <= outer["y"] + outer["h"] + 1)


# Roles that are form fields even on a <div> (ACT e086e5 applicability).
FIELD_ROLES = frozenset({"textbox", "searchbox", "combobox", "listbox", "spinbutton", "slider"})
ERROR_NEAR_CSS_PX = 48.0  # LAT-09 ER-01: an error further than this from every field needs a programmatic link


def _norm_label(text: str | None) -> str:
    return _LABEL_NOISE.sub("", (text or "").lower())


def _letters(text: str | None) -> int:
    return sum(1 for ch in text or "" if ch.isalpha())


def _dom_id(element: dict[str, Any]) -> str | None:
    if element.get("dom_id"):
        return str(element["dom_id"])
    sel = element.get("selector") or ""
    return sel[1:] if re.fullmatch(r"#[A-Za-z][\w-]*", sel) else None


def _label_tokens(text: str | None) -> list[str]:
    """ACT label-in-name tokenizer: drop (parenthesised) text, case-fold, NFKD, keep
    letters and digits, split on whitespace. A lone "x" is the close symbol, not text."""
    t = re.sub(r"\([^)]*\)", " ", text or "")
    t = unicodedata.normalize("NFKD", t.casefold())
    t = "".join(ch if unicodedata.category(ch)[0] in "LN" else " " for ch in t)
    tokens = t.split()
    return [] if tokens == ["x"] else tokens


def _label_in_name(label: str | None, name: str | None) -> bool:
    """Whether the visible label's tokens are a contiguous run of the name's tokens.
    Korean relaxation (AUT-04): a Hangul label token also matches a name token that
    starts with it, so a trailing particle ("장바구니" / "장바구니에") still counts."""
    lt, nt = _label_tokens(label), _label_tokens(name)
    if not lt:
        return True
    # ACT leaves abbreviations and spelling or hyphenation differences out of scope
    # ("Ave." / "Avenue", "non-standard" / "nonstandard"): treat them as contained.
    if "".join(lt) == "".join(nt) and "-" in f"{label or ''}{name or ''}":
        return True
    abbrev = {w.casefold() for w in re.findall(r"([^\W\d_]+)\.", f"{label or ''} {name or ''}")}

    def same(a: str, b: str) -> bool:
        if a == b:
            return True
        if re.search(r"[\u1100-\u11ff\uac00-\ud7a3]", a) is not None and b.startswith(a):
            return True
        return (a in abbrev and b.startswith(a)) or (b in abbrev and a.startswith(b))

    return any(all(same(lt[j], nt[i + j]) for j in range(len(lt))) for i in range(len(nt) - len(lt) + 1))


def _names_field(field_name: str | None, text: str | None) -> bool:
    """Whether an error text names the field: Hangul names of 2+ syllables anywhere,
    Latin names of 4+ letters as whole words (so "id" does not match "invalid")."""
    name = (field_name or "").strip()
    if not name:
        return False
    if re.search(r"[\uac00-\ud7a3]", name):
        core = _norm_label(name)
        return sum(1 for ch in core if "\uac00" <= ch <= "\ud7a3") >= 2 and core in _norm_label(text)
    words = re.sub(r"[\W_]+", " ", name.lower()).strip()
    return len(words.replace(" ", "")) >= 4 and re.search(rf"\b{re.escape(words)}\b", re.sub(r"[\W_]+", " ", (text or "").lower())) is not None


def _edge_distance(a: dict[str, float], b: dict[str, float]) -> float:
    dx = max(0.0, a["x"] - (b["x"] + b["w"]), b["x"] - (a["x"] + a["w"]))
    dy = max(0.0, a["y"] - (b["y"] + b["h"]), b["y"] - (a["y"] + a["h"]))
    return math.hypot(dx, dy)


def check_semantics(ctx: Context) -> list[Observation]:
    """Names, labels, error association and clipped text (SM-01..04, LY-01).

    Measured from the DOM and profile-independent. They matter most to people the
    swarm does not simulate (screen-reader and voice-control users) and are reported
    for them; the rules follow axe-core / ATF / XCTest practice and are kept narrow
    for precision (automated-ui-accessibility-testing brief).
    """
    out: list[Observation] = []
    base = (ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"))
    dom = [e for e in ctx.elements if e.get("source", "dom") == "dom" and _present(e)]
    # AUT-20: a zero-size control still in the accessibility tree is reached by screen
    # readers and, when focusable, by Tab; only the name rules apply to it (ACT 97a4e1,
    # c487ae, e086e5 applicability), at P2 at most (P3 when it cannot take focus).
    unseen = [e for e in ctx.elements if e.get("source", "dom") == "dom" and not _present(e) and _usable(e)
              and isinstance(e.get("a11y"), dict) and not e["a11y"].get("hidden") and e["a11y"].get("rendered") is True
              and (e["a11y"].get("focusable") or e.get("interactive") or e.get("role") in FIELD_ROLES)
              and not (e.get("tag") == "a" and not e["a11y"].get("focusable"))]  # <a> without href has no link role
    unseen_ids = {id(e) for e in unseen}
    named = dom + unseen
    fields = [e for e in named if isinstance(e.get("a11y"), dict) and (
        (e.get("tag") in ("input", "select", "textarea") and e.get("role") != "button") or e.get("role") in FIELD_ROLES)]

    def cap_unseen(e: dict[str, Any], severity: str) -> str:
        if id(e) not in unseen_ids:
            return severity
        return _cap(severity, "P2" if e["a11y"].get("focusable") else "P3")

    for e in named:
        a = e.get("a11y")
        if not isinstance(a, dict) or (not e.get("enabled", True) and e not in fields):
            continue
        if e.get("role") in ("none", "presentation") and not a.get("focusable"):
            continue  # presentational and not focusable: not in the accessibility tree (ACT e086e5)
        critical = _critical(ctx, e)
        where = e.get("selector") or e.get("id")
        if e in fields:
            source = a.get("name_source")
            if a.get("hidden"):
                continue
            if source == "none":
                # WCAG 4.1.2 / ACT e086e5: no accessible name at all (disabled fields too, at P3).
                out.append(Observation(
                    "SM-03", *base, [e["id"]], element_key(e),
                    {"name": "label_source", "value": source, "unit": "enum", "threshold": "any accessible name", "comparator": "!=",
                     "disabled": not e.get("enabled", True), "visible_to_sighted": id(e) not in unseen_ids},
                    False, cap_unseen(e, "P3" if not e.get("enabled", True) else ("P1" if critical else "P2")),
                    f"입력 칸 '{where}'에 접근 가능한 이름이 없습니다. 스크린리더는 칸의 용도를 알리지 못합니다(WCAG 4.1.2).",
                ))
            elif source in ("placeholder", "title") and id(e) not in unseen_ids:
                # A placeholder or title is an accessible name (ACT e086e5 passes it); a
                # visible label is still better practice, so this is P3 and not a WCAG failure.
                out.append(Observation(
                    "SM-07", *base, [e["id"]], element_key(e),
                    {"name": "label_source", "value": source, "unit": "enum", "threshold": "label|aria-labelledby|aria-label", "comparator": "in"},
                    False, "P3",
                    f"입력 칸 '{where}'의 이름이 {source}뿐입니다. 입력하면 안내가 사라져 무엇을 적는 칸인지 잊기 쉽습니다(모범 사례, WCAG 실패 아님).",
                ))
            continue
        if not e.get("interactive") or e.get("tag") == "canvas":
            continue
        if a.get("hidden"):
            continue  # hidden from assistive technology (a duplicate card-image link, an inert region)
        name = (e.get("name") or "").strip()
        if a.get("name_source") == "none" or not name:
            out.append(Observation(
                "SM-01", *base, [e["id"]], element_key(e),
                {"name": "accessible_name", "value": "", "unit": "text", "threshold": "non-empty", "comparator": "!=",
                 "visible_to_sighted": id(e) not in unseen_ids},
                False, cap_unseen(e, "P1" if critical else "P2"),
                f"조작 요소 '{where}'에 접근 가능한 이름이 없습니다. 스크린리더·음성 제어 사용자는 무엇을 하는 버튼인지 알 수 없습니다(시뮬레이션하지 않는 사용자군).",
            ))
            continue
        if id(e) in unseen_ids:
            continue  # the remaining rules (label in name, errors, clipping) need a rendered box
        visible = (a.get("visible_label") if a.get("visible_label") is not None else e.get("text") or "").strip()
        if a.get("name_source") in ("aria-label", "aria-labelledby") and not a.get("icon_font") and _label_tokens(visible):
            if not _label_in_name(visible, name):
                out.append(Observation(
                    "SM-02", *base, [e["id"]], element_key(e),
                    {"name": "label_in_name", "value": False, "unit": "flag", "threshold": True, "comparator": "==", "visible": visible[:60], "accessible_name": name[:60]},
                    False, "P2" if critical else "P3",
                    f"보이는 문구 '{visible[:30]}'이(가) 접근 가능한 이름 '{name[:30]}'에 없습니다. 음성 제어로 보이는 문구를 말해도 작동하지 않습니다.",
                ))
    # Input errors only: declared error_message, or role=alert that is not declared as a
    # system notice (critical_message/status without error_message).
    # An error signal is needed: a declared error message, or a role=alert while some
    # field is invalid. A "담았습니다" toast with role=alert is not an input error.
    fields = [f for f in fields if id(f) not in unseen_ids]  # distances need a rendered box
    any_invalid = any(f["a11y"].get("invalid") or f["a11y"].get("user_invalid") for f in fields)
    errors = [e for e in dom if (e.get("text") or "").strip() and (
        "error_message" in _roles(e)
        or (e.get("role") == "alert" and any_invalid and not (_roles(e) & {"critical_message", "status"})))]
    if errors and fields:
        for err in errors:
            targets = {i for i in [_dom_id(err), *(err.get("ancestor_ids") or [])] if i}
            linked = any(targets & set(f["a11y"].get("described_by") or []) or f["a11y"].get("error_message") in targets for f in fields)
            nearest = min(_edge_distance(err["box"], f["box"]) for f in fields)
            # WCAG 3.3.1 is met when the text identifies the item in error, wherever it is.
            names_field = any(_names_field(f.get("name"), err.get("text")) for f in fields)
            if linked or nearest <= ERROR_NEAR_CSS_PX or names_field:
                continue
            out.append(Observation(
                "SM-04", *base, [err["id"]], element_key(err),
                {"name": "error_field_distance_css_px", "value": round(nearest, 1), "unit": "css_px", "threshold": ERROR_NEAR_CSS_PX, "comparator": "<=", "linked": False},
                False, "P2",
                f"오류 문구 '{(err.get('text') or '')[:30]}'이(가) 어느 칸이 틀렸는지 적지 않았고, 가장 가까운 입력 칸에서 {nearest:.0f}px 떨어져 있으며, aria-describedby/aria-errormessage로 연결되지도 않았습니다(WCAG 3.3.1).",
            ))
    # SM-08 for recordings made before the driver recorded what each click landed on
    # (newer runs: check_clicked_controls, from the steps).
    if not any(isinstance(st.get("target_control"), dict) for st in ctx.run.get("steps") or []):
        controls = [c for c in ctx.elements if c.get("interactive") or c.get("role") in WIDGET_ROLES]
        for e in dom:
            if e.get("id") not in ctx.clicked_element_ids or e.get("tag") in NATIVE_CONTROL_TAGS or e.get("role") in WIDGET_ROLES:
                continue
            a = e.get("a11y") if isinstance(e.get("a11y"), dict) else {}
            if a.get("focusable") or a.get("hidden") or e.get("tag") == "hotspot" or "game_control" in _roles(e):
                continue
            if any(c is not e and _inside(c["box"], e["box"]) for c in controls):
                continue  # a card whose link or button the keyboard can reach
            out.append(_sm08(*base, [e["id"]], element_key(e), e.get("role"), e.get("tag"), e.get("name") or e.get("text") or e.get("selector") or "", []))
    for e in dom:
        clip = e.get("clipped")
        box = e.get("box") or {}
        if not isinstance(clip, dict) or e.get("interactive") or box.get("w", 0) < 4 or box.get("h", 0) < 4 or not (e.get("text") or "").strip():
            continue
        if clip.get("animated"):
            continue  # tickers and marquees clip by design
        by = clip.get("by")  # a clipping ancestor (a fixed-width chip or label), when not its own box
        # Cut cleanly (ACT 59br37's exceptions: one nowrap line ending in a marker, or a
        # one-line-high box): a truncation note (P3), not a 1.4.4 failure.
        clean = clip.get("act") == "passed"
        if clip.get("ellipsis"):
            how = " (여러 줄 말줄임으로 줄임)." if clip.get("line_clamp") else " (말줄임표로 줄임)."
        elif clean:
            how = " (한 줄 높이 상자로 줄임)."
        else:
            how = ". 글자를 키우거나 번역되면 더 많이 잘립니다."
        out.append(Observation(
            "LY-01", *base, [e["id"]], element_key(e),
            {"name": "text_clipped", "value": True, "unit": "flag", "threshold": False, "comparator": "==", "axis": "x" if clip.get("x") else "y", "ellipsis": bool(clip.get("ellipsis")),
             "clipped_by": by, "act_59br37": clip.get("act")},
            False, "P3" if clip.get("ellipsis") or clean else "P2",
            f"'{(e.get('text') or '')[:30]}' 글자가 {'바깥 상자(' + by + ')' if by else '상자'}에 잘립니다" + how,
            extra={"context_selectors": [by]} if by and by.startswith("#") else {},
        ))
    return out


CLICK_ACTIONS = ("tap", "click", "double_tap", "long_press", "press")
LATE_LAYER_WINDOW_MS = 3000  # a layer first seen at a wait counts for the click before it within this time


def _late_layer_trigger(ctx: Context) -> dict[str, Any] | None:
    """The click step a layer first seen at a wait or snapshot step belongs to.

    Apps often show a spinner first and open the dialog or sheet after a request or a
    timer, after the click step's own after-snapshot. With only waits since that click
    (no other input) and the snapshot within LATE_LAYER_WINDOW_MS of the click, the new
    layer is the click's.
    """
    step = ctx.step
    if step is None or ctx.previous is None or ((step.get("action") or {}).get("action")) not in ("wait", "snapshot"):
        return None
    steps = ctx.run.get("steps") or []
    idx = next((i for i, s in enumerate(steps) if s is step), None)
    if idx is None:
        return None
    j = idx - 1
    while j >= 0 and ((steps[j].get("action") or {}).get("action")) in ("wait", "snapshot"):
        j -= 1
    if j < 0:
        return None
    click = steps[j]
    if (click.get("action") or {}).get("action") not in CLICK_ACTIONS or click.get("result") != "ok":
        return None
    start, end = click.get("t_start_ms"), step.get("t_end_ms")
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or end - start > LATE_LAYER_WINDOW_MS:
        return None
    return click


def check_focus_management(ctx: Context) -> list[Observation]:
    """Focus after a step (AUT-11), from the snapshot's focus record and layers.

    FM-02 (WCAG 2.4.3): a click opened a layer (a declared dialog, or a fixed or
    absolute painted box over at least 40 % of the viewport) that was not there
    before, and keyboard focus is not inside it. A layer first seen at a wait right
    after the click (it opened after a request or timer) counts for that click. SM-06 at the step (2.4.11): the step
    left focus on an element that something else fully covers (an input moved under a
    fixed header after a validation error). Skipped when a layer just opened: the
    trigger behind it is covered by design, and FM-02 reports that case.
    """
    focus = ctx.snapshot.get("focus")
    if not isinstance(focus, dict) or (ctx.snapshot.get("surface") or {}).get("kind") == "game":
        return []  # recorded before the driver kept focus and layers, or a game screen
    out: list[Observation] = []
    base = (ctx.run["run_id"], ctx.profile["profile_id"], ctx.snapshot.get("snapshot_id"), ctx.snapshot.get("step_index"))
    action = ((ctx.step or {}).get("action") or {}).get("action")
    opened = False
    late_click = _late_layer_trigger(ctx)
    if ctx.previous is not None and (action in CLICK_ACTIONS or late_click is not None):
        before = {layer.get("selector") for layer in ctx.previous.get("layers") or [] if isinstance(layer, dict)}
        new_layers = [layer for layer in ctx.snapshot.get("layers") or [] if isinstance(layer, dict) and layer.get("selector") not in before]
        interactive = [e for e in ctx.elements if e.get("interactive") and _visible(e)]
        late = set((ctx.step or {}).get("focus_late_layers") or [])
        for layer in new_layers:
            opened = True
            # Focus inside, at the snapshot or within a second of the click (dialogs that
            # take focus after their entrance transition; the driver lists those on the step).
            if layer.get("contains_focus") or layer.get("selector") in late:
                continue
            kind = layer.get("kind")
            box = layer.get("box") or {"x": 0, "y": 0, "w": 0, "h": 0}
            if kind != "modal":
                # A disclosure the focused trigger controls, or a layer the next Tab
                # reaches (APG disclosure, mega menu): focus need not move.
                if layer.get("follows_focus") or (focus.get("expanded") and layer.get("dom_id") and layer["dom_id"] in (focus.get("controls") or [])):
                    continue
            if kind == "sheet":
                # An undeclared painted box: only a layer with something to operate needs
                # focus (a busy overlay or a status sheet announces itself), and a scrim
                # around a dialog is that dialog's layer.
                if not any(_inside(e["box"], box) for e in interactive):
                    continue
                if any(other is not layer and isinstance(other, dict) and other.get("kind") in ("modal", "dialog") and _inside(other.get("box") or {}, box)
                       for other in ctx.snapshot.get("layers") or []):
                    continue  # the backdrop of a dialog (new or already open): the dialog carries focus
            element = next((e for e in ctx.elements if layer.get("dom_id") and e.get("dom_id") == layer["dom_id"]), None)
            key = element_key(element) if element else f"{layer.get('selector') or '?'}|{layer.get('kind')}"
            where = "문서 본문(body)으로 떨어져" if focus.get("on_body") else "층 바깥에 남아"
            when = "앞선 클릭 뒤 늦게 " if late_click is not None else ""
            out.append(Observation(
                "FM-02", *base, [element["id"]] if element else [], key,
                {"name": "focus_in_layer", "value": False, "unit": "flag", "threshold": True, "comparator": "==",
                 "layer_kind": layer.get("kind"), "focus_on_body": bool(focus.get("on_body")),
                 **({"opened_after_click_step": late_click.get("step_index")} if late_click is not None else {})},
                False, "P2",
                f"'{layer.get('selector')}' 층이 {when}열렸지만 키보드 초점이 {where} 있습니다. 스크린리더·키보드 사용자는 새로 열린 내용을 모른 채 뒤쪽 화면을 계속 탐색합니다(WCAG 2.4.3).",
                extra={"anchor_selectors": [layer["selector"]] if layer.get("selector") else []},
            ))
    # SM-06 at a step: only a focus the step put there (an app moving focus after a
    # validation error), not one a later scroll or wait carried under a sticky bar.
    prev_focus = (ctx.previous or {}).get("focus") if ctx.previous is not None else None
    moved_here = (action in ("tap", "click", "double_tap", "long_press", "press", "type")
                  and (not isinstance(prev_focus, dict) or prev_focus.get("dom_id") != focus.get("dom_id")))
    if not opened and moved_here and not focus.get("on_body") and focus.get("dom_id"):
        target = next((e for e in ctx.elements if e.get("dom_id") == focus["dom_id"]), None)
        covered = (target or {}).get("occluded_fraction")
        under_layer = target is not None and any(
            isinstance(layer, dict) and _inside({**target["box"], "w": 1, "h": 1, "x": target["box"]["x"] + target["box"]["w"] / 2,
                                                  "y": target["box"]["y"] + target["box"]["h"] / 2}, layer.get("box") or {"x": 0, "y": 0, "w": 0, "h": 0})
            for layer in ctx.snapshot.get("layers") or [])
        # Under a layer the user opened: the 2.4.11 note exempts it and FM-02 covers focus.
        if target is not None and not under_layer and target.get("in_viewport") is not False and isinstance(covered, (int, float)) and covered >= 0.999:
            out.append(Observation(
                "SM-06", *base, [target["id"]], element_key(target),
                {"name": "focus_obscured_fraction", "value": round(float(covered), 3), "unit": "fraction", "threshold": 1.0, "comparator": "<",
                 "by": target.get("occluded_by"), "phase": "step", "criterion": "2.4.11", "user_opened": False},
                False, "P2",
                f"이 단계 뒤 키보드 초점이 '{target.get('name') or target.get('selector')}'에 있지만 다른 요소가 그 칸을 완전히 가립니다(WCAG 2.4.11).",
            ))
    return out


REFLOW_TOLERANCE_PX = 4  # borders and rounding; a few px of overflow hide no content
REFLOW_GROUP_MAX = 3  # more boxes than this past the edge on one screen: one finding for the screen


def _url_path(url: str | None) -> str:
    """The path of a URL (no host or port: a local test server's port changes per run)."""
    from urllib.parse import urlsplit
    return urlsplit(url or "").path or (url or "")


def _right_edge(offender: dict[str, Any]) -> float:
    box = offender.get("box") or {}
    return float(box.get("x") or 0) + float(box.get("w") or 0)


def check_reflow(run: dict[str, Any], profile: dict[str, Any], snapshots: dict[str, dict[str, Any]] | None = None) -> list[Observation]:
    """RF-01 (WCAG 1.4.10): at 320 CSS px wide, content that sticks out to the right.

    The driver re-renders a static copy of each distinct screen at 320 px with scripts
    off and lists the outermost elements past the right edge, leaving out
    two-dimensional content (tables, maps, video, code), inert or aria-hidden content,
    anything inside its own scroll or clipping box, and anything off screen at the
    device width too (off-canvas drawers). It counts when the page scrolls sideways or
    the root clips, or when a fixed bar holds the element (a fixed box cannot be
    scrolled to). Text visible at the device width and cut away at 320 px counts too
    ("lost"). A copy that lost its CSS (styles_lost) is not measured.
    """
    out: list[Observation] = []
    seen: set[str] = set()
    for rec in run.get("reflow") or []:
        if not isinstance(rec, dict) or rec.get("error") or rec.get("styles_lost"):
            continue
        width = rec.get("client_width") or 0
        scrolls = (rec.get("scroll_width") or 0) > width + REFLOW_TOLERANCE_PX
        snap = (snapshots or {}).get(rec.get("snapshot_id"))
        for lost in rec.get("lost") or []:
            # Visible at the device width, cut away by a clipping container at 320 px.
            element = None
            if lost.get("dom_id") and snap:
                element = next((e for e in snap.get("elements", []) if e.get("dom_id") == lost["dom_id"]), None)
            anchor = f"#{lost['dom_id']}" if lost.get("dom_id") else (f"#{lost['ancestor_ids'][0]} {lost.get('tag')}" if lost.get("ancestor_ids") else lost.get("tag") or "?")
            key = element_key(element) if element else f"{anchor}|{(lost.get('text') or '')[:40]}"
            if key in seen:
                continue
            seen.add(key)
            out.append(Observation(
                "RF-01", run["run_id"], profile["profile_id"], rec.get("snapshot_id"), None,
                [element["id"]] if element else [], key,
                {"name": "visible_share_at_320", "value": lost.get("visible_320"), "unit": "fraction", "threshold": 0.5, "comparator": ">=",
                 "visible_share_full": lost.get("visible_full"), "viewport_css_px": rec.get("width")},
                False, "P2",
                f"'{(lost.get('text') or anchor)[:30]}'이(가) 원래 폭에서는 보이지만 320 CSS px 폭(400 % 확대)에서는 상자에 잘려 {100 * (lost.get('visible_320') or 0):.0f}%만 보입니다(WCAG 1.4.10).",
                extra={"anchor_selectors": [anchor], "context_selectors": [f"#{a}" for a in lost.get("ancestor_ids") or [] if a]},
            ))
        page_overflow = scrolls or bool(rec.get("root_clips"))
        eligible = [off for off in rec.get("offenders") or [] if isinstance(off, dict)
                    and _right_edge(off) > width + REFLOW_TOLERANCE_PX and (page_overflow or off.get("fixed"))]
        listed = bool(eligible)
        if len(eligible) > REFLOW_GROUP_MAX:
            # A layout that does not reflow at all (a desktop-only page): one finding for
            # the screen, naming every box that sticks out, not one per box.
            # Keyed by the boxes too: another screen at the same URL is another finding.
            page_key = f"html|{_url_path(rec.get('url'))}|{','.join(sorted(o.get('selector') or '?' for o in eligible))[:160]}"
            if page_key in seen:
                continue
            seen.add(page_key)
            rights = [_right_edge(o) for o in eligible]
            names = [f"'{(o.get('text') or o.get('selector') or '')[:16]}'" for o in eligible[:3]]
            how = "가로 스크롤이 생기거나 화면 밖으로 잘립니다" if scrolls else "화면 밖으로 잘려 볼 수 없습니다"
            out.append(Observation(
                "RF-01", run["run_id"], profile["profile_id"], rec.get("snapshot_id"), None, [], page_key,
                {"name": "right_edge_css_px", "value": max(rights), "unit": "css_px", "threshold": width, "comparator": "<=",
                 "viewport_css_px": rec.get("width"), "page_scroll_width": rec.get("scroll_width"), "root_clips": bool(rec.get("root_clips")),
                 "offender_count": len(eligible), "in_fixed_bar": any(o.get("fixed") for o in eligible)},
                False, "P2",
                f"320 CSS px 폭(400 % 확대)에서 이 화면이 재배치되지 않습니다: 요소 {len(eligible)}개({', '.join(names)} 등)가 오른쪽으로 넘쳐 "
                f"가장 먼 끝이 {max(rights):.0f}px이고 {how}(WCAG 1.4.10).",
                extra={"anchor_selectors": [o["selector"] for o in eligible if o.get("selector")],
                       "context_selectors": sorted({f"#{a}" for o in eligible for a in o.get("ancestor_ids") or [] if a})},
            ))
            continue
        for off in eligible:
            element = None
            if off.get("dom_id") and snap:
                element = next((e for e in snap.get("elements", []) if e.get("dom_id") == off["dom_id"]), None)
            key = element_key(element) if element else f"{off.get('selector') or '?'}|{(off.get('text') or '')[:40]}"
            if key in seen:
                continue
            seen.add(key)
            box = off.get("box") or {}
            right = (box.get("x") or 0) + (box.get("w") or 0)
            how = ("고정 막대 안에서 화면 밖으로 밀려 스크롤로도 볼 수 없습니다" if off.get("fixed")
                   else "가로 스크롤이 생깁니다" if scrolls else "화면 밖으로 잘려 볼 수 없습니다")
            out.append(Observation(
                "RF-01", run["run_id"], profile["profile_id"], rec.get("snapshot_id"), None,
                [element["id"]] if element else [], key,
                {"name": "right_edge_css_px", "value": right, "unit": "css_px", "threshold": rec.get("client_width"), "comparator": "<=",
                 "viewport_css_px": rec.get("width"), "page_scroll_width": rec.get("scroll_width"), "root_clips": bool(rec.get("root_clips")),
                 "in_fixed_bar": bool(off.get("fixed"))},
                False, "P2",
                f"320 CSS px 폭(400 % 확대)에서 '{(off.get('text') or off.get('selector') or '')[:30]}'의 오른쪽 끝이 {right:.0f}px라 {how}(WCAG 1.4.10).",
                extra={"anchor_selectors": [off["selector"]] if off.get("selector") else [],
                       "context_selectors": [f"#{a}" for a in off.get("ancestor_ids") or [] if a]},
            ))
        exempt_right = rec.get("exempt_right")
        explained = isinstance(exempt_right, (int, float)) and (rec.get("scroll_width") or 0) <= exempt_right + REFLOW_TOLERANCE_PX
        if scrolls and not listed and not explained and f"page|{rec.get('url')}" not in seen:
            # The page scrolls sideways but no outermost element was located (the scan
            # is capped, or the cause is a pseudo-element or a box without text): report
            # the page itself, unless exempt content (a table, code, off-canvas) is what
            # makes it scroll.
            seen.add(f"page|{rec.get('url')}")
            out.append(Observation(
                "RF-01", run["run_id"], profile["profile_id"], rec.get("snapshot_id"), None, [], f"html|{_url_path(rec.get('url'))}",
                {"name": "page_scroll_width_css_px", "value": rec.get("scroll_width"), "unit": "css_px", "threshold": width, "comparator": "<=",
                 "viewport_css_px": rec.get("width"), "scan_capped": bool(rec.get("scan_capped"))},
                False, "P2",
                f"320 CSS px 폭(400 % 확대)에서 페이지 폭이 {rec.get('scroll_width')}px라 가로 스크롤이 생깁니다(WCAG 1.4.10). 넘치는 요소는 특정하지 못했습니다.",
                extra={"anchor_selectors": ["html"]},
            ))
    return out


def check_adaptation(run: dict, profile: dict, snapshots: dict | None = None) -> list[Observation]:
    """New clipping only, in an applied condition with matching capture receipts.

    The height ratio is a recorded experiment, with no WCAG/aspect-ratio verdict.
    The spacing result covers supported HTML text in the static copy only.
    """
    out: list[Observation] = []
    seen: set[tuple[str, str]] = set()
    for rec in run.get("adaptation") or []:
        if validate_adaptation(rec) or rec.get("status") != "measured":
            continue
        source = (snapshots or {}).get(rec["source_snapshot_id"])
        baseline = (snapshots or {}).get(rec["baseline_snapshot_id"])
        changed = (snapshots or {}).get(rec["snapshot_id"])
        if not source or not baseline or not changed:
            continue
        valid = all(s.get("run_id") == run.get("run_id") for s in (source, baseline, changed))
        valid = valid and source.get("device", {}).get("viewport_css") == rec["baseline_viewport_css"] and source["device"].get("dpr") == rec["dpr"]
        for snap, kind, viewport, condition in ((baseline, "baseline", rec["baseline_viewport_css"], None),
                                               (changed, rec["kind"], rec["viewport_css"], rec["condition"])):
            meta = snap.get("adaptation") or {}
            valid = valid and (meta.get("kind") == kind and meta.get("source_snapshot_id") == source["snapshot_id"]
                               and meta.get("condition") == condition and snap.get("device", {}).get("probe") == "adaptation"
                               and snap["device"].get("viewport_css") == viewport and snap["device"].get("dpr") == rec["dpr"])
        if not valid:
            continue
        check_id = "RF-02" if rec["kind"] == "text_spacing" else "RF-03"
        for loss in rec["lost"]:
            selector = loss["selector"]
            if (check_id, selector) in seen:
                continue
            seen.add((check_id, selector))
            element = next((e for e in changed.get("elements", []) if e.get("selector") == selector), None)
            fraction = loss["after"]["visible_fraction"]
            condition_text = "텍스트 간격을 늘린 복제 화면" if check_id == "RF-02" else f"높이를 {rec['viewport_css'][1]} CSS px로 줄인 복제 화면"
            out.append(Observation(
                check_id, run["run_id"], profile["profile_id"], changed["snapshot_id"], None,
                [element["id"]] if element else [], element_key(element) if element else f"{selector}|",
                {"name": "reachable_visible_fraction", "value": fraction, "unit": "fraction",
                 "baseline_value": loss["before"]["visible_fraction"], "reason": loss["reason"], "kind": loss["kind"],
                 "condition": rec["condition"], "baseline_viewport_css": rec["baseline_viewport_css"], "viewport_css": rec["viewport_css"],
                 "dpr": rec["dpr"], "source_snapshot_id": source["snapshot_id"], "baseline_snapshot_id": baseline["snapshot_id"],
                 "changed_snapshot_id": changed["snapshot_id"], "before": loss["before"], "after": loss["after"],
                 "geometry_tolerance_css_area": 0.25, "scroll_extent_rounding_css_px": 1,
                 "scope": "supported static HTML text" if check_id == "RF-02" else "experimental short-height clipping"},
                False, "P2", f"{condition_text}에서 '{selector}'의 내용이 잘려 {100 * fraction:.1f}%에 접근할 수 있습니다. 원래 조건에서는 전체가 보였습니다.",
                extra={"anchor_selectors": [selector], "context_selectors": [f"#{a}" for a in loss.get("ancestor_ids", [])]},
            ))
    return out


FOCUS_INDICATOR_MIN_PX = 4  # changed pixels (>= 24/255 per channel) inside the element box + 4 px


def _stop_element(stop: dict[str, Any], snapshot: dict[str, Any] | None) -> dict[str, Any] | None:
    """The snapshot element a focus stop landed on: same DOM id, else the best box overlap."""
    if not snapshot:
        return None
    elements = [e for e in snapshot.get("elements") or [] if e.get("source", "dom") == "dom"]
    if stop.get("dom_id"):
        hit = next((e for e in elements if e.get("dom_id") == stop["dom_id"] or e.get("selector") == f"#{stop['dom_id']}"), None)
        if hit:
            return hit
    b = stop.get("box") or {}
    best, score = None, 0.0
    for e in elements:
        eb = e.get("box") or {}
        ix = max(0.0, min(b.get("x", 0) + b.get("w", 0), eb.get("x", 0) + eb.get("w", 0)) - max(b.get("x", 0), eb.get("x", 0)))
        iy = max(0.0, min(b.get("y", 0) + b.get("h", 0), eb.get("y", 0) + eb.get("h", 0)) - max(b.get("y", 0), eb.get("y", 0)))
        inter = ix * iy
        union = b.get("w", 0) * b.get("h", 0) + eb.get("w", 0) * eb.get("h", 0) - inter
        iou = inter / union if union > 0 else 0.0
        if iou > score:
            best, score = e, iou
    return best if score >= 0.7 else None


def check_focus_walks(run: dict[str, Any], profile: dict[str, Any], snapshots: dict[str, dict[str, Any]] | None = None) -> list[Observation]:
    """Keyboard focus walk results recorded by the web driver (SM-05, SM-06).

    SM-05: focusing the element changes fewer than FOCUS_INDICATOR_MIN_PX pixels in and
    around its box and, when the driver compared it, in the whole viewport (an
    indicator drawn elsewhere passes, ACT oj04fd) (WCAG 2.4.7). SM-06: a painting fixed
    or sticky layer or a non-modal absolute dialog covers all nine sample points of the
    focused element (WCAG 2.4.11 AA). A layer the user opened is exempt when Escape
    reveals the element without moving focus (the 2.4.11 note; end-state walks only).
    Partly covered (2.4.12 AAA) is a hypothesis. A fully covered element is not also
    reported as SM-05. Each element is reported once with its worst result over the
    walks, tied to the snapshot element when the stop can be matched (DOM id or box
    overlap).

    The walks see the initial and end screens only. Focus probes the driver took
    before clicks (``step.focus_probe``: the clicked control focused with keyboard
    modality) add SM-05 evidence from the screens in between; a probe counts only
    when the control matched ``:focus-visible`` and did not scroll, and is never used
    for SM-06 (a covered control could not have been clicked).
    """
    walks = list(run.get("focus_walks") or [])
    # A Tab walk is the reference: a probe (script focus after an F24 key press, which
    # some focus-visible scripts do not treat as keyboard use) never overrides an
    # element a walk saw with an indicator.
    walk_ok = set()
    for walk in walks:
        for stop in walk.get("stops") or []:
            px = stop.get("indicator_px")
            anywhere = stop.get("indicator_any_px")
            best = max(v for v in (px, anywhere, -1) if isinstance(v, int))
            if best >= FOCUS_INDICATOR_MIN_PX and stop.get("selector"):
                walk_ok.add(stop["selector"])
    for step in run.get("steps") or []:
        probe = step.get("focus_probe")
        if (isinstance(probe, dict) and probe.get("focus_visible") is True and not probe.get("moved") and isinstance(probe.get("indicator_px"), int)
                and probe.get("selector") not in walk_ok):
            walks.append({"phase": "step", "snapshot_id": probe.get("snapshot_id"), "step_index": step.get("step_index"),
                          "stops": [{**probe, "obscured_fraction": None, "obscured_user_opened": None}]})
    worst: dict[str, dict[str, Any]] = {}
    for walk in walks:
        for stop in walk.get("stops") or []:
            sel = stop.get("selector") or "?"
            w = worst.setdefault(sel, {"stop": stop, "walk": walk, "covered": 0.0, "covered_walk": walk, "covered_by": None, "min_px": None,
                                       "user_opened": False, "revealed": 0})
            covered = stop.get("obscured_fraction")
            user_opened = walk.get("phase") == "end" and stop.get("obscured_user_opened") is True
            if user_opened and stop.get("escape_reveals") is True and isinstance(covered, (int, float)) and covered >= 0.999:
                w["revealed"] += 1  # the user can reveal it without moving focus: not obscured
                covered = 0.0
            if isinstance(covered, (int, float)) and covered > w["covered"]:
                w.update(covered=covered, covered_walk=walk, covered_by=stop.get("obscured_by"), user_opened=user_opened)
            px = stop.get("indicator_px")
            anywhere = stop.get("indicator_any_px")
            if isinstance(px, int) and isinstance(anywhere, int):
                px = max(px, anywhere)
            if stop.get("in_viewport") and isinstance(px, int) and (stop.get("obscured_fraction") or 0) < 0.999 and (w["min_px"] is None or px < w["min_px"]):
                w.update(min_px=px, stop=stop, walk=walk)
    out: list[Observation] = []
    for sel, w in worst.items():
        stop = w["stop"]
        name = (stop.get("name") or "")[:40]
        if w["covered"] > 0:
            snap = (snapshots or {}).get(w["covered_walk"].get("snapshot_id"))
            element = _stop_element(stop, snap)
            full = w["covered"] >= 0.999
            layer = w["covered_by"] or "고정 영역"
            if full and w["user_opened"]:
                text = f"사용자가 연 {layer}이(가) '{name or sel}'을(를) 완전히 가리고, Escape로도 초점을 옮기지 않고 드러낼 수 없습니다(WCAG 2.4.11)."
            elif full:
                text = f"키보드 포커스가 '{name or sel}'에 있을 때 {layer}이(가) 요소를 완전히 가립니다(WCAG 2.4.11)."
            else:
                text = f"키보드 포커스가 '{name or sel}'에 있을 때 {layer}이(가) 요소를 {w['covered'] * 100:.0f}% 가립니다(WCAG 2.4.12 AAA, 가설)."
            out.append(Observation(
                "SM-06", run["run_id"], profile["profile_id"], w["covered_walk"].get("snapshot_id"), None,
                [element["id"]] if element else [], element_key(element) if element else f"{sel}|{name}",
                {"name": "focus_obscured_fraction", "value": w["covered"], "unit": "fraction", "threshold": 1.0, "comparator": "<",
                 "by": w["covered_by"], "phase": w["covered_walk"].get("phase"), "criterion": "2.4.11" if full else "2.4.12",
                 "user_opened": w["user_opened"], "revealed_by_escape_walks": w["revealed"]},
                False, "P2" if full else "P3", text,
            ))
            if full:
                continue
        if w["min_px"] is not None and w["min_px"] < FOCUS_INDICATOR_MIN_PX:
            snap = (snapshots or {}).get(w["walk"].get("snapshot_id"))
            element = _stop_element(stop, snap)
            out.append(Observation(
                "SM-05", run["run_id"], profile["profile_id"], w["walk"].get("snapshot_id"), None,
                [element["id"]] if element else [], element_key(element) if element else f"{sel}|{name}",
                {"name": "focus_indicator_px", "value": w["min_px"], "unit": "px", "threshold": FOCUS_INDICATOR_MIN_PX, "comparator": ">=",
                 "phase": w["walk"].get("phase"), "local_px": stop.get("indicator_px"), "viewport_px": stop.get("indicator_any_px"),
                 "viewport_scale": stop.get("indicator_any_scale"), "step_index": w["walk"].get("step_index")},
                False, "P2",
                (f"키보드로 '{name or sel}'에 포커스를 주어도 화면에 표시가 생기지 않습니다(WCAG 2.4.7, 과업 {w['walk'].get('step_index')}단계 화면). "
                 "키보드 사용자는 지금 무엇을 누르게 되는지 모릅니다." if w["walk"].get("phase") == "step" else
                 f"Tab으로 '{name or sel}'에 포커스가 가도 화면에 표시가 생기지 않습니다(WCAG 2.4.7). 키보드 사용자는 현재 위치를 모릅니다."),
            ))
    return out


SNAPSHOT_CHECKS: tuple[Callable[[Context], list[Observation]], ...] = (
    check_reach,
    check_game_controls,
    check_target_size,
    check_touch_accuracy,
    check_pointer_separation,
    check_fitts_sequence,
    check_gaze,
    check_contrast,
    check_colour_only,
    check_text_size,
    check_choice_overload,
    check_semantics,
    check_focus_management,
)


# Checks reported as hypotheses to review, not as defects. Evidence (dev suites, 53 seeded
# defects, and round-1 adjudication of 68 findings, kappa 0.72): GZ-01 and GZ-04 found no
# defect that no other check found and were judged valid in 0/6 and 1/6 sampled cases;
# PC-05 found no unique defect and judges split (1 valid, 3 split). They stay computed
# and listed under "hypotheses" (docs/validation/experiments/decisions.md).
# PT-05 (Fitts ID > 6 bits) has no normative threshold and produced no finding on the
# development suites (STF-22).
# GM-06 is registered but emits nothing until a press-rate sweep exists (GQA-13); it
# stays in this set so that a future rule starts as a hypothesis.
HYPOTHESIS_CHECKS = frozenset({"GZ-01", "GZ-04", "PC-05", "PT-05", "GM-06"})

# Checks that read no profile attribute: one verdict per snapshot, reported as
# "profile-independent" instead of a k/n coverage (STF-08).
PROFILE_INVARIANT_CHECKS = frozenset({"TI-01", "PT-01", "PT-05", "PT-06", "PC-01", "PC-02", "CG-01", "CG-03", "GZ-03", "GM-05", "GM-06",
                                      "SM-01", "SM-02", "SM-03", "SM-04", "SM-05", "SM-06", "SM-07", "SM-08", "LY-01", "RF-01", "RF-02", "RF-03",
                                      "FM-02"})


def tier(check_id: str, measurement: dict[str, Any] | None = None) -> str:
    """``hypothesis`` for demoted checks and for persona notes nobody corroborated (STF-23)."""
    if check_id in HYPOTHESIS_CHECKS:
        return "hypothesis"
    if check_id == "PJ-01" and not (measurement or {}).get("corroborated"):
        return "hypothesis"  # `corroborated` is set only by swarm.aggregate from independent runs
    if check_id == "SM-06" and (measurement or {}).get("criterion") == "2.4.12":
        return "hypothesis"  # partly obscured is AAA (2.4.12), not a 2.4.11 failure (AUT-13)
    return "finding"


def applicable(check_id: str, profile: dict[str, Any], device: Any) -> bool:
    """Whether a check evaluates this profile at all (the coverage denominator).

    Most checks only emit failed observations, so the profiles a check tested cannot
    be read from its output. A profile counts as tested when the check reads it; the
    finding's differential condition is then computed against the tested profiles that
    did not trigger it (usability-evaluation-methods.md UEM-01).
    """
    if check_id == "TI-01":
        return False  # Its denominator comes only from recorded owner observations.
    attrs = profile.get("attributes", {})
    touch = getattr(device, "input", "touch") == "touch"
    grip = attrs.get("grip", "")
    if check_id in ("RH-01", "RH-02"):
        if not touch or grip.startswith("cradle") or grip not in reach.SUPPORTED_GRIPS:
            return False
        return not (grip.startswith("one_hand") and reach.tablet_like(reach.geometry_for_device(device)))
    if check_id == "GM-02":
        return touch and grip == "two_thumbs" and attrs.get("orientation") == "landscape"
    if check_id in ("PT-03", "PT-04", "GM-05"):
        return touch
    if check_id in ("PT-05", "PT-06"):
        return not touch
    # PC-03 (CVD) and PC-05 (bright sun) evaluate every profile: normal vision and indoor
    # profiles pass implicitly, so coverage reads e.g. 2/14 with the condition named.
    return True


def run_snapshot_checks(ctx: Context) -> list[Observation]:
    out: list[Observation] = []
    for check in SNAPSHOT_CHECKS:
        out.extend(check(ctx))
    return out


def check_task_integrity(run: dict[str, Any], profile: dict[str, Any], snapshots: dict[str, dict[str, Any]]) -> list[Observation]:
    """Authored comparisons on this execution, with no inference from labels or profile traits."""
    if profile["profile_id"] != run.get("profile_id") or run.get("status") != "completed":
        return []
    out = []
    for criterion in (run.get("success_detail") or {}).get("criteria", []):
        if criterion.get("kind") != "task_check" or criterion.get("passed") is None:
            continue
        snapshot = snapshots.get(criterion.get("snapshot_id"))
        if snapshot is None:
            continue
        passed = criterion["passed"]
        measurement = {key: criterion[key] for key in ("id", "selector", "property", "checkpoint", "result", "step_index", "snapshot_id", "severity", "consequence")}
        message = ("명시한 과업 값 검사를 통과했습니다." if passed else
                   f"명시한 과업 값이 {criterion['checkpoint']} 시점의 화면 상태와 일치하지 않습니다. {criterion['consequence']}")
        out.append(Observation(
            "TI-01", run["run_id"], profile["profile_id"], snapshot["snapshot_id"], criterion["step_index"],
            [criterion["element_id"]] if criterion.get("element_id") else [],
            f"{criterion['selector']}|{criterion['id']}", measurement, passed,
            None if passed else criterion["severity"], message,
            extra={"anchor_selectors": [criterion["selector"]], "scope": "authored criteria on the recorded owner execution; field values omitted", "impact_basis": "authored; comparison does not establish downstream harm"},
        ))
    return out


def iter_catalog() -> Iterable[CheckSpec]:
    return CATALOG.values()
