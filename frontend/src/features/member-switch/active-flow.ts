import { z } from "zod";

export const RUN_LOCATOR_KEY = "codex-lb.member-switch-run-id.v2";
export const AUTH_ENROLLMENT_LOCATOR_KEY = "codex-lb.member-auth-enrollment-id.v1";
const LEGACY_KEYS = ["codex-lb.active-member-switch-flow.v1", "codex-lb.member-switch-operation-id",
  "codex-lb.member-auth-handoff-id", "codex-lb.member-auth-browser-operation-id",
  "codex-lb.member-auth-replacement-drain.v1", "codex-lb.member-switch-blocking-start"];

// Browser storage is a locator, never the source of phase, ownership, or permission.
export function readRunLocator(): string | null {
  try {
    const parsed = z.uuid().safeParse(window.localStorage.getItem(RUN_LOCATOR_KEY));
    return parsed.success ? parsed.data : null;
  } catch { return null; }
}
export function writeRunLocator(id: string | null): void {
  try {
    if (id === null) window.localStorage.removeItem(RUN_LOCATOR_KEY);
    else window.localStorage.setItem(RUN_LOCATOR_KEY, z.uuid().parse(id));
  } catch { /* Active runs remain discoverable from the server without this hint. */ }
}
export function readAuthEnrollmentLocator(): string | null {
  try {
    const parsed = z.uuid().safeParse(window.localStorage.getItem(AUTH_ENROLLMENT_LOCATOR_KEY));
    return parsed.success ? parsed.data : null;
  } catch { return null; }
}
export function writeAuthEnrollmentLocator(id: string | null): void {
  try {
    if (id === null) window.localStorage.removeItem(AUTH_ENROLLMENT_LOCATOR_KEY);
    else window.localStorage.setItem(AUTH_ENROLLMENT_LOCATOR_KEY, z.uuid().parse(id));
  } catch { /* Active enrollments remain discoverable from the server without this hint. */ }
}
export function hasLegacyMemberFlow(): boolean {
  try {
    return LEGACY_KEYS.some((key) => window.localStorage.getItem(key) !== null || window.sessionStorage.getItem(key) !== null);
  } catch { return true; }
}
