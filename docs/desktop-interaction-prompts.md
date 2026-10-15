# 데스크톱 추가 동작 이미지 제작

경로: **내장 image_gen**, 참조 이미지 포함 신규 동작 생성, `transparent_background=true`. 외부 API나 유료 API 키를 사용하지 않았다. 생성된 파일은 원래 저장 위치에 보존하고 아래 프로젝트 경로에 복사했다. 공은 기존 도형 그리기 코드로 표시한다.

| 캐릭터 | 원본 생성 파일 (generated_images/01a138f9-f2ec-7333-bf78-382ae9b75cff 아래) | 프로젝트 보관 |
|---|---|---|
| 제니스 전체 추가 포즈 | exec-1f15d25b-6ccf-40d5-a96e-eac3f35e4128.png | characters/zenith/sources/desktop-interactions-raw-v1.png |
| 리베르타 전체 추가 포즈 | exec-99f2fe84-4706-480f-b83d-1009f9adb99a.png | characters/liberta/sources/desktop-interactions-raw-v1.png |
| 제니스 최종 옆모습 | exec-9369a836-d172-4a93-aa3a-228d7c04fa88.png | characters/zenith/sources/side-cling-raw-v2.png |
| 리베르타 최종 옆모습 | exec-a9b5fb81-c766-4939-87df-628e414f6524.png | characters/liberta/sources/side-cling-raw-v2.png |

## 전체 추가 포즈 제작 명세 / 재현 프롬프트

참조는 원본 대기 프레임이다. 제니스는 주황색 포니테일·보라색 눈·흰색/청록색 토끼 귀·하늘색 후드·노란 토끼 펜던트·짙은 치마·흰 신발을 유지한다. 리베르타는 분홍색 긴 웨이브 머리·검은 리본·붉은 눈·흰 칼라와 소매 및 프릴이 있는 검은 원피스·금색 허리 장식과 십자가·검은 신발을 유지한다.

```text
Create a transparent RGBA production sprite atlas of the attached canonical character.
Keep the identical face, eye color and shape, hair, costume, accessories, rendering style,
head size and anatomical proportions throughout. Do not independently resize frames.
Four sequential poses per action, four columns and seven action rows.
Requested canvas1536x2688;384x384cells. Full figure and transparent margins.
Row0: sit on an invisible window ledge, legs dangling, gently sway and blink.
Row1: struggle while hanging, tighten grip, kick legs, slip and recover.
Row2: curl up and sleep, slow breathing in and out, eyes closed.
Row3: wake reluctantly, rub eye, yawn, annoyed sleepy expression, recover.
Row4: side view facing right, approach cursor at waist height, reach, close hands,
      grasp an invisible tiny object and hold; no drawn cursor.
Row5: side view facing right, wind up, lift knee, extend foot to kick, recover;
      no ball in the sprite.
Row6: look around furtively, take a small cookie from a hidden pocket, bite, nibble happily.
No background, ground plane, visible window, text, grids or checkerboard.
Reference image controls identity; only the listed actions change.
```

위 내용은 생성 요구를 재현하도록 정리한 명세다. 실제 출력은948×1659였고 행 간격도 균등하지 않아 연결된 캐릭터 영역을 분리한 뒤 동작별 공통 위치 보정을 적용했다. 원본 알파와 픽셀을 보존하면서 다른 행의 팔다리가 셀에 섞이지 않도록 했다. `desktop-interactions-layout.json`에 원본 좌표·오프셋·SHA-256을 기록했다. 최종 실행용은256×320셀의4프레임 스트립이다.

## 최종・오른쪽 세로면용 옆모습

얼굴은 창을 향하고 손은 얼굴 높이에 고정하며 몸은 창 바깥에 둔다. 오른쪽에서는 왼쪽을 보는 원화를 사용하고 왼쪽에서는 게임에서 반전한다. 원화의 공통 배율을 사용해 각 프레임의 손을 같은 접촉점(32,120)에 맞춘다. 아래는 최종 생성에 전달한 프롬프트다.

### Zenith

```text
Production game asset, ONE horizontal four-frame strip, transparent background. Canonical character is the attached Zenith sprite. Preserve orange ponytail, violet eyes, white-and-cyan bunny ears, light blue hoodie, yellow rabbit pendant, dark skirt, white shoes and EXACT face/body proportions and delicate anime rendering. New animation: struggling while clinging to the RIGHT VERTICAL SIDE of a desktop window. Show a strict SIDE PROFILE facing LEFT in ALL four frames. The imaginary vertical wall is to her LEFT; both hands reach LEFT and grip the same small point on that vertical side at face/shoulder height. Her body hangs DOWN and to the RIGHT of her gripping hands, feet completely off the ground. No hands above her head as if hanging from a horizontal bar. Four sequential frames: strained grip, kicks bent legs backward, slips slightly and desperately tightens grip, legs flailing worried. Keep both gripping hands at the same pixel coordinate across frames. Keep same head size and anatomical scale across poses. Layout4 columns1 row,1536x512canvas, each384x512cell. Contact hand point local x96 y200, main torso to the RIGHT of x96; full figure including ears and feet fits with minimum32px transparent margins. Only the character, NO visible wall/window/ledge/floor, no text/grid/shadow/checkerboard. RGBA transparency. All four poses are the same character in left-facing side view, never front view, never hanging by hands overhead.
```

### Liberta

```text
Production game asset, ONE horizontal four-frame strip, transparent background. Canonical character is the attached Liberta sprite. Preserve salmon pink long wavy hair, large black bow, reddish eyes, black dress with white collar/cuffs and frilled hem, gold waist chains and cross, black shoes and EXACT face/body proportions and delicate anime rendering. New animation: struggling while clinging to the RIGHT VERTICAL SIDE of a desktop window. Strict SIDE PROFILE facing LEFT in ALL four frames. Imaginary vertical wall to her LEFT; both hands reach LEFT and grip the SAME small point at face/shoulder height. Body hangs DOWN and to the RIGHT of gripping hands, feet off ground. No overhead horizontal bar hanging. Four sequential frames: strained grip; bent legs kick backward; slight slip tightening grip; worried legs flail. Same pixel coordinate for hands and same head/body scale in every frame. Layout4 columns1row1536x512canvas,384x512cells. Hand contact local x96 y200, torso toRIGHT. Full figure with32px transparent margin. Only character, NO visible wall/window/ledge/floor, NO text/grid/shadow/checkerboard/motion lines/droplets. RGBA transparency. All four left-facing side view, never frontal.
```

실제 최종 출력은 두 캐릭터 모두2172×724였다. 포장 스크립트는 확인한 실제 크기를 검증하고 공통 배율(제니스0.4, 리베르타0.46)만 적용한다. 비율을 프레임마다 따로 바꾸지 않는다. 원본·접촉점·오프셋·배율·SHA-256은 `side-cling-layout-v2.json`에 남긴다. 최종 런타임 파일은 `characters/{zenith,liberta}/animations/ledge-struggle-side-v2.png`이다.
