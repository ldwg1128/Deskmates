# 세이르 (Seir): 제작 체크리스트

리소스 연결: 22/22 (100.0%). 파일 유효성은 validate로 별도 검사한다.

Canonical Reference: canonical.png

| 완료 | 행동 / Action ID | 필수 | 프레임 | 원본 셀 | 제작 셀 | FPS | 반복 | 방향 | 파일 |
|---|---|---|---|---|---|---|---|---|---|
| [x] | 대기 / idle | 필수 | 4 | [[384, 384]] | [384, 384] | 5.556 | loop | front | animations/idle-91214119d651.png |
| [x] | 오른쪽 걷기 / right | 선택 | 8 | [[384, 384]] | [384, 384] | 9.524 | loop | right | animations/right-dbbe72c9f80b.png |
| [x] | 왼쪽 걷기 / left | 선택 | 8 | [[384, 384]] | [384, 384] | 9.524 | loop | left | animations/right-dbbe72c9f80b.png |
| [x] | 인사 / wave | 선택 | 4 | [[384, 384]] | [384, 384] | 5.556 | once | front | animations/wave-cf2b6a6ac121.png |
| [x] | 제자리 점프 / jump | 선택 | 4 | [[384, 384]] | [384, 384] | 6.667 | once | front | animations/jump-ca885ade363c.png |
| [x] | 고개 숙이기 / bow | 선택 | 4 | [[384, 384]] | [384, 384] | 5.882 | once | front | animations/bow-953ecc6cfe1a.png |
| [x] | 수줍음 / shy | 선택 | 4 | [[384, 384]] | [384, 384] | 5.263 | once | front | animations/shy-61ffbd166989.png |
| [x] | 생각하기 / think | 선택 | 4 | [[384, 384]] | [384, 384] | 4.545 | once | front | animations/think-6d55f7430431.png |
| [x] | 고개 기울이기 / tilt | 선택 | 4 | [[384, 384]] | [384, 384] | 5.263 | once | front | animations/tilt-ff519724abb9.png |
| [x] | 배고픔 / hungry | 선택 | 4 | [[384, 384]] | [384, 384] | 2.222 | loop | front | animations/hungry-401b43a6fbce.png |
| [x] | 커서 바라보기 / gaze | 선택 | 16 | [[384, 384]] | [384, 384] | 0 | loop | clockwise from up, 16 directions | animations/gaze-b28b96fedccb.png |
| [x] | 드래그·낙하·착지 / motion | 선택 | 6 | [[384, 384]] | [384, 384] | 0 | once | inverted to upright | animations/motion-523ee26f7d34.png |
| [x] | 테두리 코너 점프 / corner | 선택 | 4 | [[384, 384]] | [384, 384] | 6.667 | once | right, rotated by game | animations/corner-b4e84d1aef4d.png |
| [x] | 빵 받기·먹기·만족 / feeding | 선택 | 4 | [[384, 384]] | [384, 384] | 4.545 | once | front | animations/feeding-a6d217664242.png |
| [x] | 빵 거절 / refusal | 선택 | 4 | [[384, 384]] | [384, 384] | 4.545 | once | front | animations/refusal-71ba87972369.png |
| [x] | Sit on a window ledge / window_sit | 선택 | 4 | [[384, 384]] | [384, 384] | 5 | loop | front | animations/window_sit-41a1f1e37f2f.png |
| [x] | Hold window corner / ledge_struggle | 선택 | 4 | [[384, 384]] | [384, 384] | 8 | loop | left | animations/ledge_struggle-0d09f31dd96d.png |
| [x] | Sleep / sleep | 선택 | 4 | [[384, 384]] | [384, 384] | 2 | loop | front | animations/sleep-290d7398ddba.png |
| [x] | Annoyed wake / wake_annoyed | 선택 | 4 | [[384, 384]] | [384, 384] | 4 | once | front | animations/wake_annoyed-b0d714c3d767.png |
| [x] | Catch the cursor / cursor_grab | 선택 | 4 | [[384, 384]] | [384, 384] | 5 | once | right | animations/cursor_grab-66ca33d3478f.png |
| [x] | Kick a ball / kick | 선택 | 4 | [[384, 384]] | [384, 384] | 6 | once | right | animations/kick-b964b74184fe.png |
| [x] | Secret snack / secret_snack | 선택 | 4 | [[384, 384]] | [384, 384] | 4 | once | front | animations/secret_snack-0764b859eb7c.png |

## idle
standing, breathing, blink
기준 위치: [192, 376]; 접촉점: None; fallback: None; Existing state duration is retained. Walking on edges and Liberta walking use distance cadence, not time FPS.

## right
side walk, contact / passing / opposite contact / passing
기준 위치: [192, 376]; 접촉점: None; fallback: idle; Existing state duration is retained. Walking on edges and Liberta walking use distance cadence, not time FPS.

## left
side walk left
기준 위치: [192, 376]; 접촉점: None; fallback: idle; Existing state duration is retained. Walking on edges and Liberta walking use distance cadence, not time FPS.

## wave
raise hand, wave, return
기준 위치: [192, 376]; 접촉점: None; fallback: idle; Existing state duration is retained. Walking on edges and Liberta walking use distance cadence, not time FPS.

## jump
crouch, rise, apex, descend, stand
기준 위치: [192, 376]; 접촉점: None; fallback: idle; Existing state duration is retained. Walking on edges and Liberta walking use distance cadence, not time FPS.

## bow
stand, bow, hold, return
기준 위치: [192, 376]; 접촉점: None; fallback: idle; Existing state duration is retained. Walking on edges and Liberta walking use distance cadence, not time FPS.

## shy
hands near chest, shy expression
기준 위치: [192, 376]; 접촉점: None; fallback: idle; Existing state duration is retained. Walking on edges and Liberta walking use distance cadence, not time FPS.

## think
hand near chin, thinking
기준 위치: [192, 376]; 접촉점: None; fallback: idle; Existing state duration is retained. Walking on edges and Liberta walking use distance cadence, not time FPS.

## tilt
head tilt, return
기준 위치: [192, 376]; 접촉점: None; fallback: idle; Existing state duration is retained. Walking on edges and Liberta walking use distance cadence, not time FPS.

## hungry
hold stomach, rub stomach, hungry expression, return
기준 위치: [192, 376]; 접촉점: None; fallback: idle; 4*.45s; initial hunger6..10s then12..20s, scheduled at action boundary.

## gaze
up then clockwise, 16 evenly spaced directions
기준 위치: [192, 376]; 접촉점: None; fallback: idle; 16 directional slots clockwise from up; cursor selection, not time playback.

## motion
hanging inverted, tuck, extend, airborne upright, landing crouch, recover
기준 위치: [192, 376]; 접촉점: None; fallback: idle; Physics phases: drag; falling progress <.16, <.48, <.84, >=.84; landing .48s: airborne <.06, crouch <.28, recover.

## corner
takeoff, airborne, landing, recover
기준 위치: [192, 376]; 접촉점: None; fallback: idle; Route corner .6s, four equally spaced phase slots; rotates inward 90 degrees.

## feeding
catch bread, bite, chew, satisfied
기준 위치: [192, 376]; 접촉점: None; fallback: idle; feed_drop .65s (look until .85 progress), catch frame0; eat1.6s alternating1/2 each.22s; happy frame3 .85s.

## refusal
accept bread, shake head left, shake head right, offer bread back
기준 위치: [192, 376]; 접촉점: None; fallback: idle; 2.8s: shake frames1/2 every.22s until1.3s; offer frame3 for remaining1.5s.

## window_sit
feet dangling, left leg swing, right leg swing, settle
기준 위치: [192, 376]; 접촉점: [192, 296]; fallback: idle; DesktopInteractions owns scheduling and completion; explicit user input retains priority.

## ledge_struggle
left-facing side profile, hands fixed to vertical window edge at face height, body outside to the right; strained grip, bent legs kick backward, slip and tighten grip, flail; mirror for the left edge
기준 위치: [192, 376]; 접촉점: [64, 164]; fallback: idle; DesktopInteractions owns scheduling and completion; explicit user input retains priority.

## sleep
curl up asleep, breathe in, breathe out, rest
기준 위치: [192, 376]; 접촉점: None; fallback: idle; DesktopInteractions owns scheduling and completion; explicit user input retains priority.

## wake_annoyed
rub eye, yawn, frown, wake
기준 위치: [192, 376]; 접촉점: None; fallback: shy; DesktopInteractions owns scheduling and completion; explicit user input retains priority.

## cursor_grab
reach at waist height, close hands, grasp, hold
기준 위치: [192, 376]; 접촉점: None; fallback: wave; DesktopInteractions owns scheduling and completion; explicit user input retains priority.

## kick
prepare, lift knee, extend kicking foot, recover
기준 위치: [192, 376]; 접촉점: None; fallback: jump; DesktopInteractions owns scheduling and completion; explicit user input retains priority.

## secret_snack
take cookie from pocket, check nobody sees, bite, satisfied
기준 위치: [192, 376]; 접촉점: None; fallback: think; DesktopInteractions owns scheduling and completion; explicit user input retains priority.
