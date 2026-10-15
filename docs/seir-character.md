# 세이르 (Seir) 제작·등록

첨부된 정면·측면 전신, 표정4종, 게임 SD 캡처를 시각적으로 분석해 기존 데스크톱 펫에 어울리는 SD 캐릭터로 제작했다. 첨부 이미지의 글자나 소품을 프로그램 명령으로 취급하지 않았다. 이름은 사용자 요청대로 **세이르 (Seir)**, ID는 `seir`다.

## 외형 기준

올리브빛 금색의 종아리까지 오는 긴 머리와 앞머리, 머리 위·뒤쪽의 큰 보라색 리본과 늘어진 꼬리, 자주빛 눈, 밝은 피부와 수줍은 표정을 핵심으로 잡았다. 남색 재킷·스커트, 흰 프릴 셔츠와 작은 목 리본, 금색 단추, 분홍 목걸이형 명찰, 어두운 스타킹과 검은 구두를 유지했다. 검은 숄더백에는 작은 분홍·보라색 토끼 장식을 달았다.

상호작용에서 양손을 사용할 수 있도록 우산은 가방에 수납한 디자인으로 정리했고 드론은 독립 게임 오브젝트로 추가하지 않았다. 구조화된 분석은 `characters/seir/design.json`, 고정 기준 그림은 `characters/seir/canonical.png`에 있다. 동작 제작 중에는 실제 대기 프레임에서 자른 `references/standing-proportions.png`도 비율 참고로 사용했다. 기본 캐릭터는 계속 리베르타이며 세이르로 자동 변경하지 않는다.

## 완성 리소스

| 행동 | Action ID | 프레임 |
|---|---|---|
| 대기·인사·점프·인사 bow·수줍음·생각·고개 기울이기 | idle, wave, jump, bow, shy, think, tilt | 각4 |
| 수평 측면 걷기 | right, left | 각8; 왼쪽은 같은 시트의 반전 |
| 커서 시선 | gaze | 16; 위에서 시계 방향 |
| 드래그·회전·낙하·착지 | motion | 6 |
| 테두리 코너 점프 | corner | 4 |
| 배고픔·먹기·배불러 거절하기 | hungry, feeding, refusal | 각4 |
| 창에 앉기·세로면 매달리기 | window_sit, ledge_struggle | 각4 |
| 잠들기·귀찮아하며 깨기 | sleep, wake_annoyed | 각4 |
| 커서 잡기·공 차기·몰래 간식 | cursor_grab, kick, secret_snack | 각4 |

총 **22개 리소스 / 110프레임**이며 누락이나 대체 그림 없이 연결했다. 프레임 수는 세이르 메타데이터로 정의하므로 카탈로그의 권장 기본 수와 달라도 된다. 게임의 기존 상태 전환 시간은 유지한다. 프레임은384×384이며 기준 신체 높이는300px, 일반 발 기준은(192,376)이다. 동작마다 공통 배율을 사용하며 같은 동작 안에서 개별 프레임의 몸을 따로 확대하지 않는다. 점프는 프레임 배치로 상승·하강을 표현하고 먹기는 발 기준을 맞춘다. 창 앉기의 접촉점은(192,296), 오른쪽 세로면을 왼쪽으로 보고 매달리는 손 접촉점은(64,164)다. 왼쪽 가장자리는 반전한다.

`profile.horizontal_walk=true`로 수평 이동과 이동 거리 기반 발 동작을 선택한다. 이 설정은 특정 캐릭터 ID를 검사하지 않는 일반 manifest 기능이다. 드래그 물리 그림의 방향은 `profile.motion_angles=[0,0,180,180]`으로 정의했다. 게임 핵심 파일 `desktop_pet.py`에 세이르 분기를 추가하지 않았다. 기존 두 캐릭터의 JSON·PNG도 수정하지 않았다.

## 이미지 생성과 검토

내장 **image_gen 도구**를 사용했다. 실제 생성 프롬프트는 `characters/seir/prompts/*.txt`, 원본 파일 이름과 저장 위치는 `generation.json`에 기록했다. `.codex/generated_images`의 출력 원본을 남기고 프로젝트의 `sources/`에도 복사했다. 런타임 그림은 `animations/{action}-{hash}.png`로 가져와 등록했다. 모든 애니메이션에는 현재 이미지 해시와 기준 그림 해시에 연결된 검토 기록이 있다.

최초 먹기 모음에서 붙은 두 포즈와 일부 비율 차이를 발견했다. 부분 대체 후보를 만든 뒤, 동작 안의 일관성을 높이도록 최종 `hungry-v3.png`, `feeding-v3.png`, `refusal-v3.png`를 대기 프레임 참조로 다시 제작했다. 초기 결과는 원본 기록으로 보관하고 게임에는 최종 스트립을 연결한다. 물리 시트는 투명도 수정 요청도 거쳤다. 배경의 숨은 RGB·극저알파 잔여물과 분리된 표시선이 게임에 섞이지 않도록 실제 캐릭터 성분과 가까운 경계만 추출했다. 원본 자체는 바꾸지 않았다.

게임 상태 모음에서 첫 시선 시트의 머리·몸 비율 차이도 확인해, 대기 프레임을 직접 참조하는16방향 `gaze-raw-v2.png`로 교체했다. 기준 이미지에서의 외형 분석과 실제 게임에서의 비율 검토를 별도로 수행한 사례다.

최종 구조 검사에는 오류·누락이 없다. 시선에 대한 마지막→첫 프레임 차이 통계 경고1건은 검토했다. 이 동작은 FPS0으로 커서 방향에 따라16개 그림 중 하나를 선택하며 시간 순서로 반복 재생하지 않으므로, 걷기처럼 루프 연결 조건을 적용하지 않는다. 걷기 루프에는 해당 경고가 없다.

`tools/prepare_seir.py`가 연결 성분별 포즈를 분리하고 발·손 위치를 맞춰 등록한다. 재포장에만 Pillow·NumPy·SciPy가 필요하며 게임과 EXE에는 필요 없다. 원본 좌표, 성분 번호, 공통 배율, 이동량과 유효 경계는 `sources/packing-layout-v1.json`에 있다. 제작 체크리스트는 `specification/checklist.md`, 전체 규격은 `specification/specification.json`에 자동 출력한다. 통계 검사는 외형의 완전한 동일성을 증명하지 않으므로 기준 그림·시트·실제 렌더링도 함께 확인했다.

```powershell
python tools/prepare_seir.py
python character_tool.py validate characters/seir --output artifacts/seir/resource-qa.json
python character_tool.py preview characters/seir --output artifacts/seir/animations
python character_tool.py checklist characters/seir --output characters/seir/specification
python verify_seir.py
```

GIF는 `artifacts/seir/animations/`, 게임 상태 모음은 `artifacts/seir/game-preview.png`, 추가 행동 모음은 `artifacts/seir/desktop-play/all-interactions-preview.png`에 생성한다. 이 파일들은 검토용이며 실행 파일에는 포함하지 않는다.

## 실행·빌드·검증

소스는 `python desktop_pet.py --character seir`, EXE는 **`dist/DeskMates.exe`**로 실행한다. 기존 사용자는 앱을 다시 실행한 후 **우클릭 → 캐릭터 전환 → 세이르 (Seir)**를 고르면 된다. 공통 행동 설정·크기·산책 방향은 유지하고 먹은 개수는 캐릭터별로 저장한다.

`build.ps1`는 `tools/stage_runtime_characters.py`로 등록 JSON·연결된 그림·기준 그림만 새 빌드 폴더에 복사해 단일 EXE에 포함한다. 제작 원본·템플릿·프롬프트의 불필요한 중복은 제외한다. 기존 빌드 폴더를 지우거나 실행 중인 사용자 앱을 종료하는 동작은 추가하지 않았다.

`verify_seir.py`는 실제 발견·메뉴 선택,22개/110프레임, 좌우 반전,64/160/320/400px, 수평 걷기, 기존 제스처·시선·배고픔·먹기·거절, 드래그·중력·착지, 양방향 테두리, 캐릭터 전환·설정 복원과 런타임 패키징을 검사한다. 추가 행동의 기존 통합 검사도 세이르에 재사용해 창 좌우 매달림·닫힘·이동·최소화,30분 수면·깨기, 커서 접근/이탈, 공 드래그/차기, 희귀 간식 계수/취소와 실제 Windows 창 버퍼를 확인한다.
