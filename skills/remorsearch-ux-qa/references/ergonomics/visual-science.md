# 시각 인간공학: 근거와 측정 범위

시선·독서·화면 크기 대응·인간공학 모델을 해석할 때 이 문서를 참고합니다.
출처 검토는 2026-10-02에 마쳤습니다. 입력 기하를 측정했어도 모델 출력은 추정으로 남습니다.
제품을 수정할지 판단할 때는 대리 지표 점수보다 재현한 과제 실패를 우선합니다.

## 시선과 시각적 주의

UI의 시선은 과제, 시작 위치, 관찰 시간, 인터페이스 종류에 따라 달라집니다.
[UEyes](https://userinterfaces.aalto.fi/ueyeschi23/)와
[MobileHCI 2020](https://arxiv.org/html/2101.09176v1)은 실험실에서 정적 스크린샷을 관찰했습니다.
이 결과만으로 결제 과제를 수행하는 개인의 주의를 확인할 수 없습니다.
[Task-driven webpage saliency](https://openaccess.thecvf.com/content_ECCV_2018/html/Quanlong_Zheng_Task-driven_Webpage_Saliency_ECCV_2018_paper.html)는
과제에 따른 주의와 과제 없이 살펴본 시각적 특징을 구분합니다.

여러 캡처 요소가 같은 시각 영역을 나타내면 한 번만 셉니다. 독립적인 조작 요소는 구분합니다.
잘린 요소의 전체 DOM 상자를 보이는 면적으로 사용하지 않습니다.
시선 표집에는 실제 보이는 기하 정보를 사용하고, 정보가 없으면 한계를 기록합니다.
마지막 클릭·탭·키보드 초점 위치는 조작의 기준점입니다. 실제 관측한 eye fixation으로 보고하지 않습니다.
시작 가정, 눈의 투영 위치, 물리적 축척, 관찰 거리, 모델 버전을 기록합니다.
Monte Carlo의 hit 비율은 모의 경로를 설명합니다. 사람이 글자를 보거나 이해할 확률로 확정할 수 없습니다.
모의 fixation 네 번에 보편적인 지속시간을 적용할 수 없습니다.

[HCEye](https://arxiv.org/html/2404.14232v3)는 젊은 성인에서 인지 부하가 정적 강조와 동적 강조에
미치는 영향이 다르다고 보고했습니다. 이 결과로 나이·저시력·인지 부하에 공통 배수를 적용할 수 없습니다.
기존 인지 가능성 구간과 계수는 해당 과제·집단에서 보정하기 전까지 민감도 분석용 정책으로 취급합니다.
F-pattern, Z-pattern, Gutenberg diagram, golden ratio를 보편적인 통과 규칙으로 사용하지 않습니다.

## 화면 비율·확대·글자

가용 창의 폭과 높이를 각각 기록합니다. 좁은 브라우저 창, page zoom, pinch zoom,
크기를 바꾼 스크린샷은 서로 다른 변환입니다. 창 크기를 바꿔도 패널 크기는 유지합니다.
패널과 캡처의 대응을 알 때만 CSS px를 물리 크기로 변환하고, 그 외에는 가정을 기록합니다.
[CSSOM View](https://www.w3.org/TR/2025/WD-cssom-view-1-20250916/)는 layout viewport와
visual viewport를 구분합니다. [Android 화면 크기 대응 지침](https://developer.android.com/develop/adaptive-apps/guides/use-window-size-classes)은
가용 창의 크기를 사용합니다. 해당 dp 경계값을 웹의 준수 기준으로 적용하지 않습니다.

크기를 바꾼 뒤 내용과 조작 요소를 확인하며 아래쪽 경계와 고정 영역의 겹침도 검사합니다.
일반 스크롤로 도달할 수 있는 내용은 손실로 세지 않습니다. 정적 복제 화면으로 JavaScript의
resize 처리를 재현하거나 대체 조작 요소의 작동을 확인할 수는 없습니다.
검사 조건과 캡처를 기록하고, 실패했거나 완료하지 못한 검사는 미확인 범위로 남깁니다.

[WCAG 1.4.12](https://www.w3.org/WAI/WCAG22/Understanding/text-spacing.html)는 사용자가 글자 간격을
바꿔도 내용과 기능을 유지하는지 검사합니다. 적용값은 글자 크기 대비 줄 높이 최소 1.5배,
문단 뒤 간격 2배, 자간 0.12배, 어간 0.16배입니다. 해당 언어에 적용되는 속성을 함께 바꾸고,
기존 값이 더 크면 줄이지 않습니다. 기본 간격이 좁다는 사실만으로 이 조항의 실패를 판단하지 않습니다.
실제 잘림, 겹침, 접근할 수 없게 된 내용을 확인합니다.

[WCAG 1.4.10](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)은 세로 스크롤 콘텐츠의
폭 320 CSS px, 가로 스크롤 콘텐츠의 높이 256 CSS px에서 재배치를 다룹니다.
2차원 배치가 필요한 콘텐츠에는 해당 예외를 검토합니다. 320 px viewport는
1280 px viewport를 400% 확대한 것과 동등하지만, 실제 브라우저 확대를 수행했다는 증거는 아닙니다.
[SC 1.4.8](https://www.w3.org/WAI/WCAG22/Understanding/visual-presentation.html)은 AAA이며
한 줄 80자, CJK 40자 이내 등으로 표현을 조정할 수 있는 수단을 다룹니다.
기본 줄 길이가 길다는 사실만으로 AA 실패를 판단하지 않습니다.

## 글자 측정값과 출처의 지표 맞추기

CSS 글자 크기는 em을 나타내며 실제 글리프 높이를 직접 측정한 값으로 사용할 수 없습니다.
[Legge와 Bigelow](https://pmc.ncbi.nlm.nih.gov/articles/PMC3428264/)는 연속 독서의 임계 글자 크기를
x-height로 다룹니다. [한국어 독서 실험](https://legge.psych.umn.edu/sites/legge.psych.umn.edu/files/files/media/he18_korean_reading_speed-_effects_of_print_size_and_retinal_eccentricity.pdf)은
특정 글꼴과 시야각 정의, RSVP 과제, 젊은 성인 여섯 명을 사용했습니다.
해당 읽기 속도를 toast 메시지나 고령 사용자에게 적용하지 않습니다.

[NASA-STD-3001 Vol. 2](https://standards.nasa.gov/node/237) Rev F, 2026-07-14는
우주 비행용 디스플레이 요구사항에 대문자 높이를 사용합니다.
[XAG 101](https://learn.microsoft.com/en-us/xbox/accessibility/xbox-accessibility-guidelines/101)은
게임 텍스트에서 ascender부터 descender까지 렌더링된 body 높이를 사용합니다.
[Apple typography](https://developer.apple.com/design/human-interface-guidelines/typography)는
플랫폼 point를 사용합니다. 이 지표들과 CSS em 측정값이 동등하다고 간주할 수 없습니다.
측정한 글리프 지표, 글꼴, 축척, 관찰 거리를 명시합니다.
글리프나 물리 축척을 보정하지 못했다면 그 한계를 기록하고, ISO·NASA·XAG·WCAG 인증으로 표시하지 않습니다.

## 시간과 운동 모델의 해석

[WCAG 2.2.1](https://www.w3.org/WAI/WCAG22/Understanding/timing-adjustable.html)은 같은 정보나 기능을
시간 제한 없이 이용하는 대체 경로를 허용합니다. 버튼이 사라졌다는 사실만으로 모든 접근의
유효기간이 끝났다고 판단하지 않습니다. 같은 기록과 빌드에서 만료 뒤의 대체 경로를 확인합니다.
이름이나 존재 여부만으로는 충분하지 않습니다. 모델로 계산한 읽기 시간과 관측한 과제 접근을 구분합니다.

[FFitts](https://www3.cs.stonybrook.edu/~xiaojun/pdf/FFitts.pdf)는 관측한 터치 종점의 분산과
따로 보정한 손가락의 부정확성을 사용합니다. 명목 목표 너비를 관측한 종점 SD로 사용하지 않습니다.
[Ng 등](https://eprints.gla.ac.uk/117068/1/117068.pdf)은 짐을 든 조건에서 터치 오차의 평균 절대 거리
변화를 보고했습니다. 해당 백분율을 축별 SD의 배수로 적용하지 않습니다.
나이·파지·이동성 요인을 결합한 계수는 함께 미치는 영향을 측정하기 전까지 가정으로 남깁니다.

## 평가

개발용·보정용·평가용 held-out 입력을 구분합니다. recall, 오탐 후보, 조건 식별을 함께 측정합니다.
모든 지적을 억제한 결과를 개선으로 보고하지 않습니다. 실패한 과제 실행과 원래 임계값을 보존합니다.
구현 전후를 비교할 때는 같은 입력을 사용합니다. 학습 전에 데이터셋의 좌표 대응, 잘라낸 영역,
타임스탬프, 학습·테스트 포함 여부를 확인합니다.
적은 스크린샷을 평가한 결과로 사람의 과제 성공을 검증했다고 할 수 없습니다.
