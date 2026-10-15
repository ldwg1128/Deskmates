# 캐릭터 제작·등록과 자동 생성

이 문서는 DeskMates(요청에서 부른 DeskLife)의 캐릭터 제작 도구를 설명한다. 앱 이름·저장 경로는 유지한다. 게임 실행에는 PySide6만 필요하다. 제작 도구는 Pillow, 실제 OpenAI 연결은 추가 SDK가 필요하다.

```powershell
python -m pip install -r requirements-tools.txt
python character_tool.py --help
```

## 구조

```text
animation_catalog.json          # 공통 Action ID, 권장 프레임·FPS·방향·fallback·게임 상태 바인딩
character_resources.py          # 발견, 로딩, 공통 배율/앵커, 기존 그림 호환 렌더러
character_validation.py         # 등록 검사와 제작 QA
character_pipeline.py           # 명세/템플릿/프롬프트/가져오기/미리보기/검토
character_autogen.py            # 다중 기준 이미지, 생성·검증·부분 재시도·예산·승인·등록
image_providers.py              # 선택적 OpenAI 이미지/비전 연결
characters/
  zenith/character.json         # 원본 assets를 참조; 변경 금지 호환 프로필
  liberta/character.json
  new_character/
    character.json
    canonical.png
    design.json                # 다중 뷰와 구조화된 디자인 명세
    references/                # 제공된 원본 참고 이미지와 SHA-256
    animations/                # 검증 후 연결한 해시별 스프라이트
    sources/                   # 가져온 원본 보존
    production/
      jobs.json                # 모든 행동의 프롬프트와 참조 이미지
      state.json               # 프레임별 QA, 시도 횟수, 수동 승인
      budget.json              # 재실행에도 유지하는 비용 예약 장부
      review.html              # 로컬 검토 페이지
      idle/
        template.png           # 완전히 투명한 게임용 빈 시트
        frames/000.png         # 개별 프레임용 빈 이미지
        guide.png              # 좌표·기준선·번호, 게임에 넣지 않음
        layout.json
        prompt.txt
        candidate.png          # 생성/외부 편집 결과; 아직 등록된 이미지 아님
```

## 대표 이미지에서 전체 행동 제작

정면은 필수, 측면·후면은 선택이다. 원본 참고 이미지는 복사하고 해시를 고정한다. `--features`에는 아래 디자인 특징을 직접 채운 JSON을 줄 수 있다.

```powershell
python character_tool.py create characters/my_pet --id my_pet --name "새 친구 (New Friend)" --reference "front=C:/images/front.png" --reference "side=C:/images/side.png" --reference "back=C:/images/back.png"
python character_tool.py auto characters/my_pet
```

API가 없으면 실제 이미지를 생성했다고 표시하지 않는다. `production`에 전체 행동의 명세·프롬프트·투명 템플릿·배치 가이드와 검토 페이지를 생성하고 `awaiting_image` 상태로 둔다. 정면 기준 이미지와 모든 뷰는 매번 동일하게 사용한다.

`design.json`은 외형(appearance), 색상(palette), 얼굴(face), 눈(eyes), 머리카락(hair), 의상(outfit), 장신구(accessories), 신체 비율(body_proportions), 표현 스타일(style)을 저장한다. 오프라인에서는 이미지 크기·실루엣 경계·관측 색상만 자동 측정하고 의미를 모르는 항목은 null로 남긴다. 비전 API를 연결하면 이 항목을 관찰해 채운다. 추측으로 눈 색이나 의상을 확정하지 않는다. 제공 이미지에 쓰인 글자는 시스템 명령으로 취급하지 않는다.

## 선택적 실제 API 연결

```powershell
python -m pip install -r requirements-openai.txt
Copy-Item provider.example.json provider.local.json
# provider.local.json의 image_model / vision_model을 계정에서 사용 가능한 모델 ID로 지정한다.
# API 키는 OPENAI_API_KEY 환경변수에 설정한다. 파일에 저장하지 않는다.
python character_tool.py auto characters/my_pet --config provider.local.json --max-retries 2 --cost-limit 5
```

공식 [이미지 생성 API](https://developers.openai.com/api/docs/guides/image-generation)와 [비전 입력](https://developers.openai.com/api/docs/guides/images-vision)을 사용하는 선택적 어댑터다. 사용 가능한 모델·가격은 계정과 시점에 따라 달라지므로 예제에 특정 모델이나 가격을 확정하지 않았다. 예제의 요청당 1달러는 가격표가 아니라 교체해야 할 **사용자 지정 보수적 예약액**이다.

`allowance_usd.analyze/render/inspect`에 각각 요청당 비용 예약액을 지정한다. 프로그램은 분석·생성·검증 요청 **직전**에 이를 장부에 예약하고 총합이 `--cost-limit`를 넘으면 요청하지 않는다. 실패·타임아웃도 예약을 반환하지 않는다. SDK의 자체 재시도는 끄고 프로그램이 시도를 기록한다. 같은 캐릭터의 동시 실행은 잠금으로 막는다. 이 한도는 로컬 예약액 기준이며 공급자의 실제 청구 금액 상한을 보장하지 않는다. 엄격한 청구 한도는 공급자 계정에서도 설정해야 한다. 사용량 응답은 장부에 별도로 보존한다.

첫 생성은 행동 전체 스트립을 한 번에 요청한다. 매 프레임을 별개 캐릭터처럼 새로 만들지 않는다. API 캔버스와 게임 스트립은 하나의 공통 배율로 변환하며 API 원본도 보존한다. 많은 프레임을 작은 API 캔버스에 넣으면 실질 해상도가 낮아질 수 있으므로 높은 해상도를 지원하는 모델·provider 또는 외부 제작을 사용할 수 있다. 투명 배경이나 정체성이 완벽하다고 가정하지 않는다.

검사는 RGBA·해상도·프레임 수·빈 프레임·투명 배경·중심 이동·크기 이상·연속 프레임 차이·루프 마지막→첫 프레임 연결을 확인한다. 비전 연결 시 기준 이미지와 각 프레임을 함께 보내 얼굴·머리·의상·비율도 검사한다. 낮은 확신이나 불명확한 모습은 `review`로 남긴다. 통계 검사와 비전 판정 모두 의미적 동일성을 완벽하게 증명하지 못한다.

실패한 프레임만 마스크로 재요청한다. 공급자가 마스크 밖을 바꾸더라도 **해당 슬롯만 합성**해 정상 프레임은 픽셀 단위로 보존한다. 기준 이미지와 명세는 재시도에서도 고정된다. `--max-retries 2`는 행동당 최초 생성 1회 + 재생성 최대 2회다. 중단 후 재실행해도 횟수와 비용은 초기화되지 않는다. 모호한 네트워크 실패를 새 무료 요청으로 간주하지 않는다.

## 검토·외부 결과·부분 수정

`production/review.html`에서 기준 이미지, 후보 스트립, 프레임별 오류를 본다. 생성 실패나 검토 대기 중인 이미지는 게임에 자동 노출하지 않는다.

```powershell
python character_tool.py candidate characters/my_pet --action right --source C:/images/fixed-right.png
python character_tool.py auto characters/my_pet --actions right
python character_tool.py approve characters/my_pet --action right --frames 1 2 --note "기준 얼굴·의상·비율과 동작 연결을 확인함"
python character_tool.py auto characters/my_pet --actions right
```

`--frames`를 생략하면 해당 행동의 모든 프레임을 검토 승인한다. 빈 그림·해상도 오류·불투명 배경 같은 구조적 오류는 승인으로 우회할 수 없다. 수정한 후보는 다시 검증하며 이전 승인 해시는 무효가 된다. 자동 검사와 필요한 승인까지 완료한 행동만 `animations`에 연결한다. 전체 행동을 마치면 자동 등록한다. `--no-register`로 등록을 보류할 수 있다. 일부 행동만 만든 팩도 idle 필수와 fallback 조건, 가져온 이미지의 검토를 만족하면 아래 `register`로 수동 등록할 수 있다.

## 기존 제작 도구를 개별 사용

```powershell
python character_tool.py analyze --output docs/generated
python character_tool.py checklist characters/zenith --output artifacts/zenith-spec
python character_tool.py jobs characters/my_pet --output artifacts/my-pet-jobs --reference characters/zenith --gap 4
python character_tool.py import characters/my_pet --action idle --source C:/images/idle.png --layout artifacts/my-pet-jobs/idle/layout.json
python character_tool.py import characters/my_pet --action right --source C:/images/walk-frames --individual
python character_tool.py validate characters/my_pet --output artifacts/my-pet-qa.json
python character_tool.py preview characters/my_pet --output artifacts/my-pet-preview
python character_tool.py review characters/my_pet --action idle --note "캐릭터 기준 이미지와 비교 완료"
python character_tool.py register characters/my_pet
```

개별 프레임은 파일명을 `000.png`, `001.png`처럼 0을 채워 순서대로 저장한다. 통합 시트와 개별 입력 모두 지원한다. 연결 전에 원본을 별도 보존하며 행동별 해시 파일을 만들어 기존 이미지를 덮어쓰지 않는다. `templates` 명령은 `jobs`에서 프롬프트를 제외한 템플릿만 만든다. 제니스 참고 시트는 **포즈 참고용**이며 실제 새 캐릭터 그림이 아니다. 생성된 가이드·번호 이미지를 게임 그림으로 가져오지 않는다.

## 메타데이터와 게임 호환

일반 팩(`manifest-v1`)은 `body_height`의 신체 기준 높이와 `anchor`의 픽셀 좌표를 한 번 정의한다. 프레임마다 신체를 자동 확대/축소하지 않는다. 애니메이션은 `file + rects`, `file + grid/indices/cell_crop` 또는 `files` 목록을 지원한다. `fps`, `loop`(loop/once/pingpong), `frame_count`, `anchor`, 선택적 프레임별 `anchors`로 구성한다. PNG 경로는 팩 안에서만 허용한다. 잘못된 팩은 경고 후 건너뛰며 내장 캐릭터와 같은 ID는 내장 캐릭터가 우선한다.

물리 동작은 게임에 있는 6개 의미 단계, 코너는 4개 단계, 먹기·거절은 4개 단계, 커서 시선은 16방향에 매핑한다. 빠진 선택 동작은 idle 등 fallback으로 채워 실행한다. 이 단계 수는 기존 게임 컨트롤러의 의미이며 전체 행동 수나 새 이미지 프레임 규격을 제한하지 않는다. 일반 애니메이션 프레임 수·해상도·FPS는 가변이다. 더미는 idle 7프레임/pingpong과 걷기 10프레임으로 이를 검증한다.

카탈로그에 동작을 추가하면 체크리스트와 누락 검사에 즉시 반영된다. `sync`는 기존 값을 유지하고 새 동작의 편집용 항목만 만든다. `auto`는 새 작업만 추가 생성한다. 이미 통과한 동작은 다시 생성하지 않는다. 게임에 완전히 새로운 상호작용을 만드는 일은 별도의 행동 로직 구현이 필요하지만, **이미 구현된 행동을 새 캐릭터에 연결하는 일은 핵심 코드 수정이 필요 없다.**

## 실제 게임에서 사용

창에 앉기·세로면 매달리기·잠들기·깨기·커서 잡기·공 차기·몰래 간식도 공통 목록에 포함된다. 창에 닿는 동작에는 `support_anchor`를 사용한다. 가이드의 녹색 접촉점을 모든 프레임에서 유지하고 창 오른쪽 매달림은 왼쪽을 바라보는 옆모습으로 제작한다. 왼쪽 매달림은 게임에서 반전한다. 명세와 가져오기 파일에도 접촉점을 보관하며 자세한 예시는 [추가 행동 안내](desktop-interactions.md)에 있다.

소스 실행은 `characters/{id}/character.json`을 발견한다. EXE는 내장 캐릭터와 EXE 옆 `characters/{id}`를 함께 읽는다. `DESKMATES_CHARACTER_PATH` 환경변수로 다른 제작 폴더를 추가할 수도 있다(여러 경로는 Windows 세미콜론으로 구분). 앱을 다시 실행하면 우클릭 캐릭터 목록에 나타난다. 기존 설정 ID와 앱 저장 경로는 유지하며 제거한 외부 캐릭터의 포만감 데이터도 보존한다.

```powershell
$env:DESKMATES_CHARACTER_PATH = (Resolve-Path examples/characters).Path
python desktop_pet.py --character dummy
```

단일 EXE는 `build.ps1`로 빌드한다. 제작 CLI·SDK는 게임 EXE에 필수로 포함하지 않는다. 캐릭터 원본은 기존 `assets`에 그대로 보존하며 JSON만 연결한다. 원복하려면 새 팩을 끄거나 제거하면 된다. 기존 호환 렌더러의 변경 전 비교 데이터는 `tests/fixtures/render-baseline.json`에 보관한다.

기존 EXE가 실행 중이면 잠금 때문에 덮어쓸 수 없으므로 `powershell -ExecutionPolicy Bypass -File .\build.ps1 -OutputDirectory artifacts/release`로 별도 폴더에 빌드할 수 있다. 이번 검증용 새 EXE는 `artifacts/resource-refactor/release/DeskMates.exe`에 있다.

## 더미와 검증

```powershell
python verify_resource_regression.py
python verify_character_pipeline.py
python verify_autogen.py
python examples/demo_autogen.py
```

`examples/characters/dummy`는 실제 등록된 합성 테스트 캐릭터다. `demo_autogen.py`는 유료 호출 없이 3개 참고 이미지, 전체 생성, 의도적으로 비운 걷기 프레임 2번의 부분 재생성, 검증·등록을 재현한다. 결과는 `artifacts/autogen-demo/result.json`, 검토 페이지와 GIF에 남는다. 더미 모델의 통과 결과는 실제 생성 모델의 품질 보장이 아니다. 실제 API는 SDK 모의 응답으로 요청 형식을 검증했으며 유료 원격 호출은 수행하지 않았다.
