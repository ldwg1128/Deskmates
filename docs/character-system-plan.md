# 캐릭터 리소스 및 제작 파이프라인 작업 계획

기준: 기존 DeskMates(사용자 요청의 DeskLife), Windows/PySide6. 앱 이름과 저장 경로는 이번 작업에서 바꾸지 않는다.

1. 현재 구현을 분석하고 원본 PNG SHA-256과 동일 행동 시퀀스의 프레임·좌표를 기록한다.
2. 행동 카탈로그, 캐릭터 manifest, 리소스 로더를 분리한다. 기존 두 캐릭터는 호환 프로필로 기존 픽셀·크기·속도를 보존한다.
3. 카탈로그를 기준으로 명세서·체크리스트·프롬프트·배치 가이드·투명 템플릿·참고 시트·GIF를 생성한다. AI 실행은 선택적 provider로 분리하고 기본은 외부 결과 가져오기다.
4. 등록 검증, 누락 fallback, 파일/프레임/정렬/루프/기준 이미지 검사와 검토 승인 기록을 구현한다.
5. 별도 폴더에 더미 캐릭터를 등록해 동일 게임 로직에서 모든 행동을 재생한다. 기존 회귀 검증과 실행파일 빌드까지 수행한다.

추가 요청 반영: 다중 참고 이미지의 구조화된 디자인 명세, 선택적 이미지/비전 API, 프레임별 검증·부분 재생성, 재시도·비용 예약 장부, 수동 승인 페이지, 누락 행동의 추가 생성까지 구현한다. 단계별 결과는 [검증 보고서](regression-results.md), 사용 방법은 [제작 안내](character-authoring.md)에 기록한다.

각 단계는 독립 모듈·명령으로 검증한다. 기존 assets는 이동·수정하지 않는다. 작업 전 코드와 비교 데이터는 artifacts/resource-refactor에 보존한다. 명세의 행동 수·해상도는 가변이며 Codex 8×9 형식이나 9개 상태에 묶지 않는다.

## 조사한 설계와 재사용 범위

공식 출처: [hatch-pet](https://github.com/openai/skills/blob/main/skills/.curated/hatch-pet/SKILL.md), [sprite-pipeline](https://github.com/openai/plugins/blob/main/plugins/game-studio/skills/sprite-pipeline/SKILL.md), [상세 파이프라인](https://github.com/openai/plugins/blob/main/plugins/game-studio/references/sprite-pipeline.md). 조사일 2026-10-15. 이 두 스킬은 로컬에 설치되어 있지 않아 공식 원문을 조사했다. Codex 펫을 생성·설치하는 워크플로 자체를 실행하는 작업은 아니다.

| 참고 설계 | 이 프로젝트에 적용 | 그대로 가져오지 않는 부분 |
|---|---|---|
| hatch-pet: 기준 이미지에 연결된 행동별 작업 manifest, 프롬프트와 배치 가이드, 결정론적 추출·검증·미리보기 | Canonical Reference의 경로·해시·정체성 조건, 작업 상태, 외부 결과 가져오기, QA·검토 이력 | Codex 전용 상태 이름·192×208 셀·8×9 아틀라스·Codex 설치 경로 |
| sprite-pipeline: 승인된 게임 프레임 기준, 스트립 단위 제작, 공통 배율과 앵커, 미리보기 후 반영 | 동작 전체를 한 작업으로 요청, 선택적 첫 프레임 고정, 공통 배율 정규화, 안내 이미지와 게임 이미지 분리 | 브라우저 게임 전용 코드·고정 출력 크기 |

위 표는 공개 설계에서 선택한 원칙이다. 소스 코드를 복사하지 않고 DeskMates의 행동·자르기·회전 방식에 맞게 구현한다. 기준 얼굴·눈·머리카락·의상 일치는 픽셀 통계만으로 증명할 수 없으므로 자동 검사는 이상 징후로 보고하고 시각 검토 승인을 별도로 기록한다.
