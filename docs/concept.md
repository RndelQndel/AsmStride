현재 저장소를 분석한 뒤, 이 프로젝트를 사실상 **차세대 버전으로 전면 재설계**하라.

Repository:
https://github.com/RndelQndel/PyElfSim.git

단, 기존 코드와 구조를 반드시 유지해야 한다고 가정하지 마라.

이 프로젝트는 아직 초기 단계이므로 기존 구현의 호환성을 지키기 위해 잘못된 구조를 끌고 가는 것보다, 제품 목적에 맞는 구조를 처음부터 다시 설계하는 것이 우선이다.

이번 작업에서는 **구현하지 말고 설계만 수행하라.**

---

# 1. 프로젝트의 본질

이 프로젝트는 ELF 파일 자체를 분석하는 일반적인 binary analysis tool이 아니다.

핵심 사용 사례는 다음과 같다.

사용자는 임베디드 개발 또는 장애 분석 과정에서 다음과 같은 **불완전한 정보만 가지고 있을 수 있다.**

* `fromelf` 출력 일부
* `objdump` 출력 일부
* crash log에 포함된 disassembly
* 특정 함수 주변 10~수백 줄 정도의 assembly
* 일부 register 값
* 일부 memory 값
* stack pointer / link register 등의 상태

전체 ELF 파일, firmware binary, target board, debugger 환경은 존재하지 않을 수 있다.

이때 사용자가 assembly text를 붙여 넣고 필요한 register/memory state만 입력하면 해당 코드 조각을 즉시 실행하면서 상태 변화를 관찰할 수 있는 **가벼운 interactive assembly simulator/debugger**를 만들고자 한다.

제품을 한 문장으로 표현하면 대략 다음과 같다.

> Paste assembly. Inject state. Step through it.

또는

> A lightweight debugger for incomplete machine state.

단, 이것도 절대적인 문구는 아니므로 제품 정의부터 다시 검토하라.

---

# 2. 기존 프로젝트에서 유지할 핵심 개념

다음 개념은 제품 목적상 중요하다.

### Assembly text 입력

사용자는 ELF나 binary 대신 텍스트를 붙여 넣을 수 있어야 한다.

예:

```text
0x08000100: E92D4010    PUSH {r4, lr}
0x08000104: E5910004    LDR  r0, [r1, #4]
0x08000108: E3500000    CMP  r0, #0
0x0800010C: 0A000003    BEQ  0x08000120
```

입력 형식은 최소한 다음을 고려한다.

* ARM `fromelf`
* GNU objdump
* 일반적인 address / opcode / mnemonic 형태

Parser는 각 입력 포맷을 adapter 형태로 확장 가능하게 설계할 것.

---

### State Injection

초기 CPU 상태를 사용자가 직접 수정할 수 있어야 한다.

예:

```text
R0 = 0x00000000
R1 = 0x20000100
SP = 0x20100000
LR = 0x08001000
```

memory도 직접 입력할 수 있어야 한다.

예:

```text
0x20000104 = 0x00000001
```

전체 dump를 요구하지 말고 **필요한 state만 부분적으로 제공할 수 있어야 한다.**

---

### Arbitrary PC

파일 첫 instruction부터 실행하도록 강제하지 않는다.

사용자가:

```text
Start PC = 0x08000104
```

처럼 원하는 instruction에서 실행을 시작할 수 있어야 한다.

---

### Step execution

가장 중요한 UX다.

사용자가 Step을 실행할 때마다:

* PC
* registers
* flags
* stack
* memory
* branch 결과

등이 어떻게 바뀌었는지 바로 확인할 수 있어야 한다.

---

# 3. 기술 방향

기존 프로젝트는 PyQt6 + Unicorn 기반이다.

이번 재설계에서는 **PyQt를 제거하고 Web UI로 전환하는 방향을 우선 검토하라.**

목적은 서버형 SaaS를 만드는 것이 아니다.

기본적으로는 로컬 개발 도구다.

예:

```text
pyelfsim
      ↓
local FastAPI server
      ↓
browser
```

또는 이와 유사한 구조를 고려한다.

기본 후보 stack:

Backend:

```text
Python 3.12+
FastAPI
Unicorn Engine
pytest
uv
```

Frontend:

```text
Svelte
TypeScript
Vite
Monaco Editor
```

React를 기본값으로 선택하지 말 것.

이 프로젝트의 UI 복잡도를 고려하여 Svelte, Vanilla TypeScript 등 더 단순한 방법도 비교하고 가장 적절한 방식을 제안하라.

Frontend framework 자체가 목적이 되어서는 안 된다.

---

# 4. angr는 기본적으로 제외

기존 검토 과정에서 angr가 언급되었지만 현재 제품 요구사항에는 symbolic execution이 필요하지 않다.

따라서 다음 기능은 현재 범위에서 제외한다.

* symbolic execution
* symbolic register
* path constraint solving
* automatic path exploration
* 특정 분기로 도달하기 위한 값 역산

이런 요구가 실제로 생기기 전까지 angr dependency를 추가하지 않는다.

기본 execution engine은 Unicorn 하나로 충분한지 검토하라.

YAGNI 원칙을 적용할 것.

---

# 5. 핵심 설계 원칙

UI, parser, CPU execution engine을 강하게 결합하지 않는다.

대략 다음과 같은 dependency direction을 목표로 한다.

```text
Web UI
   │
   ▼
Application/API
   │
   ▼
Simulation Core
   │
   ├── Parser
   │
   ├── Machine State
   │
   └── Execution Backend
              │
              ▼
           Unicorn
```

UI는 Unicorn에 대해 알아서는 안 된다.

Parser도 Unicorn object를 생성해서는 안 된다.

Simulation Core는 Web framework에 의존해서는 안 된다.

---

# 6. Domain Model 재설계

기존 프로젝트의 다음 구조는 그대로 유지해야 할 이유가 없다.

특히 현재의:

```python
Instruction(
    address: int,
    opcode: int,
    mnemonic: str,
    size: int = 4,
)
```

모델은 ARM32 fixed-width instruction에 지나치게 종속되어 있다.

다음과 같은 개념을 검토하라.

```text
Instruction
ProgramImage
MachineState
RegisterState
MemoryState
StepResult
ArchitectureProfile
ExecutionBackend
```

Instruction은 적어도 다음 정보를 표현할 수 있어야 한다.

```text
address
raw bytes
instruction size
display text
architecture
execution mode
```

opcode를 단순 integer로 보관하는 것이 적절한지 다시 판단하라.

특히 다음을 지원해야 한다.

* ARM 32-bit instruction
* Thumb 16/32-bit instruction
* variable instruction size
* 향후 RISC-V 확장

---

# 7. ARM / Thumb

첫 번째 실제 지원 대상은 ARM이다.

최소한:

```text
ARMv7 ARM mode
Thumb / Thumb-2
```

를 설계 단계부터 고려한다.

다음과 같은 hard coding을 피할 것.

```text
PC += 4
instruction size = 4
UC_MODE_ARM only
```

instruction size와 execution mode가 domain model에서 정상적으로 표현되어야 한다.

---

# 8. Memory Model

전체 machine memory image가 존재하지 않는 상황을 기본 가정으로 한다.

예:

```asm
LDR R0, [R1, #4]
```

인데

```text
R1 = 0x20001000
```

만 알고 있고 `0x20001004` 값은 모를 수 있다.

이 상황을 어떻게 처리할지 명확한 정책을 설계하라.

예를 들어:

```text
Strict mode
- unmapped/unknown memory access 시 실행 중단
- 필요한 memory address를 사용자에게 표시

Permissive mode
- 필요한 memory page를 자동 mapping
- 기본값 0
```

등을 검토하라.

사용자가 UI에서 memory 값을 추가하거나 수정할 수 있어야 한다.

---

# 9. StepResult

단순히 step 이후 전체 register dump만 반환하지 말고, **무엇이 변했는지 표현할 수 있는 실행 결과 모델**을 검토한다.

예:

```text
StepResult

pc_before
pc_after

register_changes
memory_reads
memory_writes

branch_taken
executed_instruction

stop_reason
error
```

이를 이용해서 UI가 다음을 쉽게 표시할 수 있어야 한다.

* 변경된 register highlight
* stack 변경 highlight
* 현재 PC
* branch taken/not taken
* invalid memory access
* execution stop reason

---

# 10. UI / UX

기본 화면은 debugger와 code editor의 중간 형태다.

대략:

```text
┌────────────────────────────────────────────────────────────┐
│ App Name                     ARM32 / Thumb                 │
├────────────────────────────────────────────────────────────┤
│ Step │ Run │ Stop │ Reset │ PC [........] Go             │
├─────────────────────────────────────┬──────────────────────┤
│                                     │ Registers            │
│                                     │                      │
│ Code / Assembly View                │ R0   0x00000000      │
│                                     │ R1   0x20000100      │
│ ▶ 0x08000104 LDR r0,[r1,#4]        │ PC   0x08000104      │
│   0x08000108 CMP r0,#0             │ CPSR 0x60000000      │
│   0x0800010C BEQ ...               │                      │
│                                     ├──────────────────────┤
│                                     │ Stack / Memory       │
│                                     │                      │
└─────────────────────────────────────┴──────────────────────┘
```

Code View는 table 느낌보다 editor 느낌이어야 한다.

Monaco Editor를 사용할 경우 다음을 고려한다.

* gutter PC indicator
* current instruction line highlight
* auto scroll
* breakpoint gutter
* syntax highlighting
* address / opcode / mnemonic 표현

단, Monaco가 오히려 지나치게 무겁다면 더 단순한 대안도 비교하라.

---

# 11. Web API

초기에는 불필요하게 WebSocket을 도입하지 않는다.

Step 기반 P0라면 일반적인 HTTP API로 충분할 수 있다.

예:

```text
POST /api/session
POST /api/program
POST /api/step
POST /api/reset

PUT /api/registers/{name}
PUT /api/memory

GET /api/state
```

실제 endpoint 구조는 다시 설계할 것.

특히 중요한 것은 **한 개의 전역 Singleton simulator에 모든 상태를 넣지 않는 것**이다.

향후 여러 browser tab이나 session을 지원할 가능성을 고려해서 simulation session lifecycle을 정의하라.

WebSocket은 Run 기능에서 지속적으로 상태를 전달할 필요가 생길 때 도입한다.

---

# 12. Multi Architecture

P0는 ARM/Thumb이다.

향후 후보:

```text
RISC-V
MIPS
기타 embedded architecture
```

다만 지금 구현하지 않는다.

대신 ARM-specific 코드가 core 전체에 퍼지지 않도록 abstraction boundary만 설계한다.

예:

```text
ArchitectureProfile
ExecutionBackend
RegisterDescriptor
```

등.

과도한 abstraction은 피한다.

실제로 ARM 외 architecture 구현이 없는 상태에서 필요 이상의 plugin architecture를 만들지 않는다.

---

# 13. 프로젝트 이름도 다시 정한다

`PyElfSim`이라는 이름은 더 이상 제품의 실제 성격을 잘 표현하지 못한다.

이 프로젝트는:

* Python 자체가 핵심 제품 특성이 아님
* ELF 파일이 필수가 아님
* 단순 simulator보다 interactive debugger에 가까움

따라서 이름을 새로 제안하라.

조건:

* 짧을 것
* 개발 도구 이름으로 자연스러울 것
* CLI command로 사용하기 쉬울 것
* 특정 architecture에 종속되지 않을 것
* Python이라는 언어 이름에 종속되지 않을 것
* ELF에 종속되지 않을 것
* 너무 일반적인 단어 하나만 사용하지 않을 것
* 기억하기 쉬울 것
* GitHub repository 이름으로도 자연스러울 것

예를 들어 다음과 같은 개념에서 이름을 탐색할 수 있다.

```text
step
trace
state
register
machine
instruction
assembly
sandbox
snippet
probe
flow
micro
```

단순 조합 이름만 만들지 말고 브랜드처럼 사용할 수 있는 이름도 제안하라.

10~15개 후보를 제안하고 각각:

```text
Name
CLI command
의미
장점
단점
```

을 간단히 평가하라.

그 후 최종적으로 3개 정도를 shortlist하라.

기존 `PyElfSim` 이름을 유지해야 한다는 전제는 없다.

---

# 14. P0 범위

첫 번째 usable version은 반드시 작게 유지한다.

P0 후보:

```text
assembly text paste/load

ARM mode
Thumb mode

instruction parsing

start PC 지정

Step

register view
register edit

CPSR/flags

memory injection
memory inspection

stack view

current PC highlight

changed register highlight

Reset
```

다음은 P0에서 제외한다.

```text
angr
symbolic execution

RISC-V
MIPS

binary / ELF full loader

GDB integration

target board connection

decompiler

CFG visualization

advanced breakpoint expressions

collaboration / cloud

authentication

database
```

Run / breakpoint는 P0 또는 P1 중 어느 쪽이 적절한지 판단해서 설명하라.

---

# 15. 기존 코드 평가

기존 repository의 모든 주요 source file을 실제로 읽고 다음으로 분류한다.

```text
Reuse
Rewrite
Delete
```

단, 기존 코드가 있다는 이유만으로 reuse하지 말 것.

특히 다음을 확인하라.

```text
core/engine.py
core/parser.py
datatypes/
model/
ui/
main.py
pyproject.toml
```

현재 codebase의 구체적인 구조적 문제도 지적하라.

단순한 code style 개선은 제외하고, 새로운 제품 구조에서 실제 문제가 되는 부분만 다룬다.

---

# 16. 최종 산출물

이번 작업에서는 코드를 작성하지 않는다.

다음 문서만 작성하라.

## A. Current State Analysis

현재 PyElfSim 구현과 구조 분석.

---

## B. Revised Product Definition

제품이 정확히 무엇을 해결하는 도구인지 재정의.

가능하면 1~3문장으로 명확히 정의.

---

## C. Naming Proposal

10~15개 이름 후보 및 최종 shortlist.

---

## D. Architecture Decision

추천 기술 스택과 그 이유.

특히 다음 선택을 명확히 판단한다.

```text
PyQt vs Web

Svelte vs React vs Vanilla TS

Monaco vs simpler code viewer

FastAPI 필요 여부

Unicorn 적합성
```

---

## E. Domain Model

핵심 객체와 책임.

예:

```text
Instruction
ProgramImage
MachineState
StepResult
SimulationSession
ArchitectureProfile
ExecutionBackend
```

필요 없는 객체는 제거하고 필요한 객체는 추가해도 된다.

---

## F. Component Architecture

Backend / Frontend 포함 전체 component diagram.

dependency direction까지 표시.

---

## G. API Design

P0 API 목록과 request / response 개념.

---

## H. Frontend Structure

주요 화면 구성과 component tree.

---

## I. Repository Structure

새로운 directory 구조 제안.

예:

```text
backend/
frontend/
tests/
...
```

또는 더 적합한 구조를 제안할 것.

---

## J. Migration Plan

기존 repository에서 새로운 구조로 이동하는 단계.

기존 코드 중:

```text
Reuse
Rewrite
Delete
```

를 명확히 구분한다.

---

## K. Implementation Roadmap

P0 개발 순서를 dependency 기준으로 정렬한다.

각 단계에 완료 조건을 작성한다.

---

# 17. 중요한 작업 원칙

이번 설계에서는 다음 원칙을 반드시 따른다.

1. **YAGNI**
   현재 필요하지 않은 기능을 미래 확장성을 이유로 구현하지 않는다.

2. **Core first**
   UI보다 simulation domain model과 execution semantics를 먼저 확정한다.

3. **No unnecessary compatibility**
   초기 프로젝트이므로 기존 API와 구조를 보존하기 위한 compatibility layer를 만들지 않는다.

4. **No premature abstraction**
   향후 RISC-V 지원을 고려하되 존재하지 않는 architecture를 위해 거대한 abstraction framework를 만들지 않는다.

5. **No premature optimization**
   수십~수백 instruction을 다루는 로컬 도구라는 실제 workload를 기준으로 판단한다.

6. **Explicit boundaries**
   Parser / Simulation / Web API / UI의 책임을 명확히 분리한다.

7. **Product over framework**
   React, Svelte, FastAPI, Monaco 자체가 목적이 아니다.
   더 단순한 방법이 요구사항을 만족한다면 그것을 선택한다.

8. **Do not implement yet**
   이번 단계에서는 설계안을 완성하는 것이 종료 조건이다.

---

마지막에는 반드시 다음 형태로 결론을 정리하라.

```text
Recommended Product Name:
Recommended Stack:

Core Architecture:
Frontend:
Backend:
Execution Engine:

P0 Scope:
Deferred:

Reuse:
Rewrite:
Delete:

First implementation task:
```

설계 중 불확실한 부분이 있더라도 사소한 선택을 사용자에게 계속 질문하지 말고 가장 합리적인 기본안을 선택한 뒤 그 이유를 기록하라.

단, 제품 방향을 크게 바꾸는 수준의 불확실성만 명확하게 별도 표시하라.

