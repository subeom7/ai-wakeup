# ai-wakeup

**한도가 풀리면, 멈춘 AI 작업을 다시 깨우세요.**

Claude Code와 Codex CLI의 **기존 세션을 지정한 시각에 다시 실행**하는 로컬 도구입니다. 서버를 운영하거나 API 키를 새로 등록할 필요 없이, 이미 설치한 공식 CLI를 호출하는 방식입니다. 기존 환경변수에 API 키가 설정되어 있다면 해당 CLI의 과금 경로에 영향을 줄 수 있으므로 확인해야 합니다.

> **0.1.0a1 실험용 알파입니다.** 지금 버전은 세션 ID와 재개 시각을 직접 등록하는 예약 실행기입니다. 이미 열린 모든 세션의 한도 초과를 알아서 감지하는 unsnooze 대체 완성품은 아닙니다. 운영체제별 CI 결과는 [Actions](https://github.com/subeom7/ai-wakeup/actions/workflows/ci.yml)에서 확인할 수 있습니다. CI는 가짜 에이전트를 사용하며, 사용자 PC의 터미널 동작과 로그인한 Claude·Codex의 실제 재개는 별도 검증이 필요합니다.

## 먼저 실행해 보기

준비물은 **Python 3.11 이상과 pip**, 그리고 아래 clone 명령에 사용할 **Git**입니다. 모의 데모에는 Claude·Codex 설치나 AI 계정이 필요하지 않습니다.

처음 내려받는 경우, 프로젝트를 저장할 상위 폴더에서 PowerShell을 열고 순서대로 실행하세요.

```powershell
git clone https://github.com/subeom7/ai-wakeup.git
cd ai-wakeup
py -m pip install .
py -m ai_wakeup demo
py -m ai_wakeup --help
```

`pip install .`의 `.`은 **현재 폴더의 프로젝트를 설치한다**는 뜻입니다. 소스를 내려받는 명령이 아니므로, `README.md`와 `pyproject.toml`이 있는 `ai-wakeup` 폴더로 먼저 이동해야 합니다.

**이미 clone했다면** 해당 폴더에서 `py -m pip install .`부터 실행하세요. 기존 폴더 안에 다시 clone할 필요는 없습니다. **Git 없이 설치하려면** 이 저장소의 **Code → Download ZIP**으로 내려받아 압축을 풀고, `pyproject.toml`이 있는 폴더에서 터미널을 여세요. 위의 `git clone`과 `cd ai-wakeup` 두 줄을 건너뛰고 설치·데모·도움말 명령부터 실행하면 됩니다.

Linux/macOS에서는 `py` 대신 `python3`를 사용하세요. 설치 없이 소스 폴더에서 모듈을 직접 실행할 수도 있습니다.

`demo`는 **가짜 에이전트로 실행 흐름만 검증**합니다. API 요청, 사용량 소모, 실제 프로젝트 변경은 하지 않습니다. 설치 없이 소스 폴더에서 `py -m ai_wakeup demo`를 실행해도 됩니다.

이 소스는 아직 PyPI에 게시하지 않았습니다. 출처를 확인하지 않고 `pip install ai-wakeup`으로 동명의 패키지를 설치하지 마세요.

## 실제 세션 예약

먼저 공식 CLI에 로그인하고, 이어갈 세션의 **전체 UUID**를 확인합니다. 같은 세션을 실행 중인 대화형 창과 다른 예약 실행기를 정리한 다음 등록합니다. **unsnooze와 ai-wakeup에 같은 세션을 동시에 맡기면 안 됩니다.** 이 도구가 외부 실행기를 자동으로 찾아서 중지해 주지는 않습니다.

```powershell
py -m ai_wakeup doctor
```

아래 UUID와 경로는 예시이므로 본인의 값으로 바꾸세요. `--after 4h`는 직접 지정한 4시간 뒤이며, 자동으로 확인한 리셋 시각이 아닙니다.

```powershell
py -m ai_wakeup schedule codex `
  --session "0199a213-81c0-7800-8aa1-bbab2a035a53" `
  --cwd "C:\work\your-project" `
  --after 4h `
  --allow-edits

py -m ai_wakeup preview
py -m ai_wakeup start
py -m ai_wakeup status
```

Claude는 `schedule claude`로 바꿉니다. 정확한 시각은 `--after` 대신 `--at "2026-09-30T01:15:00+09:00"`처럼 **실제 미래 날짜와 시간대**를 입력하세요. 예시 날짜를 그대로 재사용하지 마세요.

예약 등록만으로 실행기가 시작되지는 않습니다. `start`는 백그라운드 실행기를 명시적으로 시작합니다. 로그인 자동 실행이나 PC 절전 방지는 설정하지 않습니다. PC가 켜져 있고 인터넷에 연결되어 있어야 합니다. 실행한 터미널을 닫은 뒤 다른 창에서 `status`로 실행기가 살아 있는지 확인하세요. Windows의 실제 터미널 종료/프로세스 유지 동작은 추가 검증이 필요합니다. 별도 창에서 `py -m ai_wakeup worker`를 계속 열어두는 방식도 있습니다.

## 권한과 결과를 구분합니다

기본값은 Codex의 `read-only`와 Claude의 `plan`입니다. **코드 수정을 맡기려면 `--allow-edits`를 명시**해야 합니다. 이 경우 각각 `workspace-write`, `acceptEdits`로 호출하지만, 모든 명령이나 네트워크 작업을 자동 승인하지는 않습니다. Claude의 plan 모드와 Codex의 읽기 전용 샌드박스는 같은 보안 경계가 아닙니다.

기본 재개 지시문에는 기존 작업 범위 준수, 배포·게시·push·과금 변경 금지 등을 넣었습니다. 필요하면 `--prompt` 또는 UTF-8 `--prompt-file`로 바꿀 수 있습니다. 지시문 자체가 보안 장치는 아니며, 실제 CLI의 설정·훅·권한을 확인해야 합니다. 모델은 `--model`로 지정할 수 있지만, 과거 TUI의 모든 설정을 자동 복원한다고 보장하지 않습니다.

`completed`는 **한 번의 응답/작업 턴이 정상 종료됐다는 뜻**이지, 전체 프로젝트가 완성됐다는 의미가 아닙니다. 성공 형식이 불분명하거나 권한 거부가 있으면 확인이 필요한 상태로 남깁니다.

## 상태, 로그, 중지

```powershell
py -m ai_wakeup status
py -m ai_wakeup logs <JOB_ID>
py -m ai_wakeup logs <JOB_ID> --stream stderr
py -m ai_wakeup cancel <JOB_ID>
py -m ai_wakeup stop
```

예약은 SQLite에 저장됩니다. 기본 재시도는 최초 실행 포함 3회이며, 명확하게 인식한 공급자 한도 오류만 재시도합니다. 기본 대기 간격은 15분에서 늘어나고, 한 번의 실행은 1시간 제한, 예약 유효 기간은 예정 시각으로부터 24시간입니다. 로그인 오류나 알 수 없는 종료를 무조건 반복하지 않습니다.

실행 중 프로그램이 비정상 종료됐다면 `needs_review`로 남깁니다. 같은 작업 폴더의 다른 예약도 확인 전에는 실행하지 않습니다. 로그, 변경된 파일, 남아 있는 프로세스를 직접 확인한 후에만:

```powershell
py -m ai_wakeup resolve <JOB_ID> --acknowledge-stopped
```

이 명령은 예약을 닫을 뿐 다시 실행하지 않습니다. 외부 터미널·다른 상태 폴더·다른 예약 실행기의 중복 실행까지 차단하지는 못합니다.

## 개인정보와 현재 한계

상태는 기본적으로 `~/.ai-wakeup`에 저장됩니다. 프롬프트와 로그에 코드·경로·민감한 출력이 들어갈 수 있고 암호화되어 있지 않습니다. 원본 로그를 공개 이슈에 그대로 올리지 마세요. 인증 토큰을 추출하거나 업그레이드·계정 전환·한도 우회를 수행하는 기능은 없습니다. 공식 CLI가 기존 인증과 환경변수를 그대로 사용합니다.

현재 미구현: 기존 TUI/IDE 세션 자동 감지, 리셋 날짜 자동 추출, Claude StopFailure 훅 설치, 셸 래퍼, GUI, 로그인 자동 시작, 원격 제어. `doctor`도 실행 파일과 버전만 확인하며 로그인·잔여량·세션 존재를 확인하지 않습니다.

테스트 및 설계 상세는 [VALIDATION.md](docs/VALIDATION.md), [ARCHITECTURE.md](docs/ARCHITECTURE.md), [ROADMAP.md](docs/ROADMAP.md)를 참고하세요. 라이선스는 [MIT](LICENSE)입니다.
