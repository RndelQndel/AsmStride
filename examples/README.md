# ArmStride 예시 데이터 가이드 (Example Scenarios)

이 디렉터리는 ArmStride에서 바로 테스트해볼 수 있는 6가지 대표적인 시나리오 예시 데이터를 제공합니다.
웹 UI(`http://127.0.0.1:8000`)의 **"Program input"** 영역에 직접 붙여넣거나, **"Read local text file"** 버튼을 통해 파일을 직접 불러와 실행해 볼 수 있습니다.

---

## 1. 크래시 로그 분석 (`01_crash_log_analysis.txt`)
* **목적**: 실제 임베디드 펌웨어 충돌 로그(타임스탬프, 레지스터 덤프 접두사 등)에서 순수 명령어만 추출하여 스텝 실행
* **입력 설정**:
  * Input: `Disassembly import`
  * Mode: `ARM`
  * Format: `auto` 또는 `generic`
* **테스트 절차**:
  1. 파일을 로드하면 상단의 `[00:01:23.450] CRASH:`, `REGS:` 메타데이터 라인 2개가 "Ignored lines"로 안전하게 처리되고, 6개 명령어가 로드됩니다.
  2. R1 레지스터에 초기값 `0x0000000A` (10)을 입력합니다.
  3. **Step**을 누르며 `MOV r0, #5`, `ADD r1, r0, r1` (R1이 15가 됨)을 진행합니다.
  4. `CMP r1, #16` 스텝 후 플래그(N/Z/C/V) 변화를 확인하고, `BEQ` 명령어가 Not Taken으로 fallthrough되는 과정을 관찰합니다.

---

## 2. 조건부 분기 검사 (`02_branch_inspection.s`)
* **목적**: `CMP` 결과에 따른 조건부 분기(`BEQ`, `BGT`)의 Taken/Not-taken 결과 및 플래그 변화 검증
* **입력 설정**:
  * Input: `Assembly source`
  * Mode: `ARM`
  * Base address: `0x1000`
* **테스트 절차**:
  1. 소스를 로드합니다.
  2. **실험 A (Equal)**: R0 = `5`, R1 = `5`로 설정 후 **Step** 진행 -> `BEQ`가 Taken으로 판정되어 `equal_target`(`0x1014`)로 즉시 점프하는 것을 확인합니다.
  3. **Reset**을 누른 후 **실험 B (Greater)**: R0 = `10`, R1 = `3`으로 설정 후 **Step** 진행 -> `BEQ`는 Fallthrough, `BGT`가 Taken으로 판정되어 `greater_target`(`0x1020`)으로 점프하는 것을 관찰합니다.

---

## 3. 스택 프롤로그 및 에필로그 (`03_stack_prologue_epilogue.s`)
* **목적**: PUSH/POP 및 SP 연산에 따른 합성 스크래치 스택(`0x200F0000`–`0x20100000`)의 동작과 레지스터 복원 관찰
* **입력 설정**:
  * Input: `Assembly source`
  * Mode: `ARM`
  * Base address: `0x1000`
* **테스트 절차**:
  1. 소스를 로드합니다. 초기 SP는 `0x20100000`입니다.
  2. **Step** (`push {r4, r5, lr}`) 실행: SP가 `0x200FFFF4`로 12바이트 감소하고, 스택 테이블에 기록된 단어들이 하이라이트됩니다.
  3. **Step** (`sub sp, sp, #8`): 로컬 변수 영역 8바이트 확보.
  4. 로컬 변수 쓰기(`STR`) 및 읽기(`LDR`) 스텝을 거치며 Stack 뷰의 데이터 변화를 확인합니다.
  5. 마지막 `pop {r4, r5, pc}` 실행 시 PC가 복원된 후, 코드 영역 외부이므로 `stop_reason: pc_not_loaded`로 안전하게 멈추는 것을 확인합니다.

---

## 4. 부분 메모리 폴트 및 상태 복구 (`04_partial_memory_fault.txt`)
* **목적**: 알 수 없는 메모리(Unknown memory) 접근 시의 원자적 롤백(Atomic rollback)과 메모리 주입 후 재시도 검증
* **입력 설정**:
  * Input: `Disassembly import`
  * Mode: `ARM`
  * Format: `generic`
* **테스트 절차**:
  1. 텍스트를 로드합니다.
  2. R1 레지스터를 `0x20000000`으로 수정합니다.
  3. **Step** (`LDR r0, [r1, #4]`) 클릭:
     * `0x20000004` 주소가 알 수 없는 상태이므로 `unmapped_memory_access` 에러와 함께 중단됩니다.
     * 모든 레지스터와 머신 상태가 변경 전 상태로 완벽히 복원(Rollback)됩니다.
  4. **Memory 패널**에서:
     * Patch address: `0x20000004`
     * Patch type: `32-bit word (little-endian)`
     * Input: `0x12345678` 입력 후 **Apply memory patch** 클릭.
  5. 다시 **Step**을 클릭하면 직전 실패했던 명령어가 정상 실행되어 R0에 `0x12345678`이 적재됩니다.
  6. **Reset**을 누르면 주입했던 메모리(`0x20000004`)는 Baseline으로 보존되고 CPU 실행 변경 사항만 초기화되는 것을 확인합니다.

---

## 5. Thumb & Thumb-2 혼합 인코딩 (`05_thumb2_mixed_widths.s`)
* **목적**: 16비트 Thumb 명령어(2바이트)와 32비트 Thumb-2 명령어(4바이트)의 연속 실행 및 PC 전진 관찰
* **입력 설정**:
  * Input: `Assembly source`
  * Mode: `Thumb / Thumb-2`
  * Base address: `0x2000`
* **테스트 절차**:
  1. 소스를 로드합니다.
  2. Code view에서 각 명령어의 크기를 확인합니다:
     * `movs r0, #10`: 2바이트 (`0x2000` -> `0x2002`)
     * `adds r1, r0, #5`: 2바이트 (`0x2002` -> `0x2004`)
     * `movw r2, #0x1234`: 4바이트 (`0x2004` -> `0x2008`)
     * `movt r2, #0x5678`: 4바이트 (`0x2008` -> `0x200c`)
  3. **Step**을 누를 때마다 PC가 2바이트 또는 4바이트 단위로 정확하게 증가하는 것을 확인합니다.

---

## 6. Fromelf 디스어셈블리 덤프 (`06_fromelf_disassembly.txt`)
* **목적**: ARM `fromelf` 포맷 특유의 섹션 헤더, `$a.0` 심볼 행, ASCII 문자 컬럼(`....`) 자동 필터링 검증
* **입력 설정**:
  * Input: `Disassembly import`
  * Mode: `ARM`
  * Format: `auto` 또는 `fromelf`
* **테스트 절차**:
  1. 텍스트를 로드합니다.
  2. 섹션 메타데이터와 심볼 라인이 Ignored lines로 계산되고, ASCII 열은 무시되며 순수 opcode만 파싱되어 실행 이미지로 구성됩니다.
  3. 루프(`SUBS r1, r1, #1` -> `BNE`)를 스텝 실행하며 합계(`ADD r0, r0, r1`) 계산 과정을 관찰합니다.

---

## 7. RISC-V RV32I 산술 루프 및 트랩 (`07_riscv_arithmetic_loop.s`)
* **목적**: RISC-V RV32I 기본 정수 연산, 의사 명령어(`li`), 로컬 레이블 분기(`blt`), 및 환경 트랩(`ebreak`) 관찰
* **입력 설정**:
  * Architecture: `RISC-V (RV32I)`
  * Input: `Assembly source`
  * Mode: `RV32I`
  * Base address: `0x1000`
* **테스트 절차**:
  1. 소스를 로드합니다.
  2. 우측 레지스터 패널에서 `x0`–`x31` 32개 정수 레지스터와 ABI 이름(`zero`, `ra`, `sp`, `a0`–`a7`, `t0`–`t6` 등)이 표시되고, ARM 전용 CPSR 및 플래그(NZCV)가 숨겨진 것을 확인합니다.
  3. `x0 (zero)` 레지스터는 수정이 비활성화(Locked)되어 있고 영구히 0으로 고정됩니다.
  4. **Run**을 클릭하면 루프를 반복 실행하다가 `ebreak` 명령어에서 깔끔한 디버거 트랩(`stop_reason: breakpoint_trap`)으로 중단되는 것을 관찰합니다. `a0`에는 누적합이 기록됩니다.

---

## 8. RISC-V RV32I 스택 및 부호/영 확장 메모리 연산 (`08_riscv_memory_stack.s`)
* **목적**: 하향식 스크래치 스택(`0x200F0000`–`0x20100000`, 초기 SP=`0x20100000`) 프레임 할당, 바이트/하프워드 부호 확장(`lb`/`lh`)과 영 확장(`lbu`/`lhu`)의 차이 관찰
* **입력 설정**:
  * Architecture: `RISC-V (RV32I)`
  * Input: `Assembly source`
  * Mode: `RV32I`
  * Base address: `0x1000`
* **테스트 절차**:
  1. 소스를 로드합니다. 초기 `sp`(`x2`)는 `0x20100000`입니다.
  2. **Step** (`addi sp, sp, -16`): `sp`가 `0x200FFFF0`으로 16바이트 감소합니다.
  3. **Step** (`sw t0, 0(sp)`): `0x000080F0`이 스택에 저장됩니다.
  4. **Step** (`lb a0, 0(sp)`): 최상위 비트가 1인 바이트 `0xF0`가 부호 확장되어 `a0`에 `0xFFFFFFF0`으로 적재됩니다.
  5. **Step** (`lbu a1, 0(sp)`): 동일한 바이트 `0xF0`가 영 확장되어 `a1`에 `0x000000F0`으로 적재됩니다.
  6. **Step** (`lh a2, 0(sp)`): `0x80F0`가 부호 확장되어 `a2`에 `0xFFFF80F0`으로 적재됩니다.
  7. **Step** (`lhu a3, 0(sp)`): `0x80F0`가 영 확장되어 `a3`에 `0x000080F0`으로 적재됩니다.
  8. **Step** (`lw a4, 0(sp)`): 전체 32비트 워드 `0x000080F0`가 정확히 적재됩니다.
  9. 프레임 해제(`addi sp, sp, 16`) 후 복귀(`ret`)를 완료합니다.
