export type Mode = 'arm' | 'thumb';
export type Flag = 'n' | 'z' | 'c' | 'v';
export interface Register { value: number; origin: 'default' | 'user' | 'execution' }
export interface Change<T> { before: T; after: T }
export interface ITContext {
  block_index: number;
  block_total: number;
  condition: string;
  passed: boolean;
}
export interface StepResult {
  status: 'executed' | 'failed'; step_seq: number;
  instruction: { address: number; size: number; source_line: number | null } | null;
  pc_before: number; pc_after: number; condition_passed: boolean | null;
  executed?: boolean;
  it_context?: ITContext | null;
  register_changes: Record<string, Change<number>>;
  cpsr_change: Change<number> | null; flag_changes: Partial<Record<Flag, Change<boolean>>>;
  memory_reads: { address: number; size: number; bytes: string }[];
  memory_writes: { address: number; size: number; before_bytes: string; after_bytes: string }[];
  branch: { kind: string; condition: string | null; taken: boolean; target: number | null; fallthrough: number } | null;
  stop_reason: string | null;
  error: { code: string; restored: boolean; context: Record<string, unknown> } | null;
}
export interface Breakpoint {
  address: number;
  mode: Mode;
}
export interface State {
  session_id: string; status: 'empty' | 'ready' | 'stopped' | 'unavailable';
  profile: string | null; mode: Mode | null; baseline_pc: number | null; step_seq: number;
  registers: Record<string, Register>; cpsr: Register | null; flags: Record<Flag, boolean> | null;
  pc: number | null; stack: { base: number; size: number } | null;
  regions: { base: number; size: number; kind: string; permissions: string }[];
  last_step: StepResult | null;
  breakpoints?: Breakpoint[];
}
export interface Diagnostic {
  code: string; severity: string; message: string; line: number | null;
  source_text: string; context: Record<string, unknown>;
}
export interface Instruction {
  address: number; bytes: string; size: number; source_line: number | null;
  source_text: string; display_text: string; decoded_text: string; feature_exclusion: string | null;
  mode?: Mode;
}
export interface DataRegion {
  address: number;
  size: number;
  bytes: string;
  source_line: number | null;
}
export interface Program {
  profile: string; mode: Mode; format: string; source_text: string;
  instructions: Instruction[];
  data_regions?: DataRegion[];
  diagnostics: Diagnostic[]; instruction_count: number; ignored_line_count: number;
}
export interface RunResult {
  start_step_seq: number;
  end_step_seq: number;
  steps_committed: number;
  steps_executed: number;
  stop_reason: string;
  elapsed_ms: number;
  breakpoint_hit: number | null;
  last_step?: StepResult | null;
  last_step_result?: StepResult | null;
}
export interface RunResponse {
  run_result: RunResult;
  state: State;
}
export interface StopResponse {
  signaled: boolean;
}
interface LoadCommon { text: string; mode: Mode; stack?: { base: number; size: number } }
export type LoadRequest = LoadCommon & (
  { input_kind: 'assembly'; base_address: number } |
  { input_kind: 'disassembly'; format: 'auto' | 'fromelf' | 'objdump' | 'generic'; encoding: 'auto' | 'words' | 'bytes' }
);
export interface ErrorEnvelope {
  error: { code: string; message: string; context: Record<string, unknown> };
  diagnostics?: Diagnostic[]; preview?: Instruction[];
}
export class ApiError extends Error {
  constructor(public status: number, public detail: ErrorEnvelope) { super(detail.error.message); }
}

export async function request<T>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch(`/api/sessions${path}`, {
    method, cache: 'no-store', signal: AbortSignal.timeout(15000),
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = response.status === 204 ? (null as T) : await response.json();
  if (!response.ok) throw new ApiError(response.status, result);
  return result as T;
}

export const hex = (value: number | null) => value === null ? '—' : `0x${value.toString(16).padStart(8, '0')}`;
export function uint32(text: string): number {
  const value = text.trim();
  if (!/^(?:0x[0-9a-f]+|[0-9]+)$/i.test(value) || Number(value) > 0xffffffff)
    throw new Error('Enter an unsigned 32-bit decimal or 0x hexadecimal value.');
  return Number(value);
}
