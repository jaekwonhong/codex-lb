import { beforeEach, describe, expect, it } from "vitest";
import { hasLegacyMemberFlow, readRunLocator, RUN_LOCATOR_KEY, writeRunLocator } from "./active-flow";
describe("server run locator", () => {
  beforeEach(() => { localStorage.clear(); sessionStorage.clear(); });
  it("stores only a UUID, not ownership or local phase", () => {
    const id = crypto.randomUUID(); writeRunLocator(id);
    expect(localStorage.getItem(RUN_LOCATOR_KEY)).toBe(id);
    expect(readRunLocator()).toBe(id);
    writeRunLocator(null); expect(readRunLocator()).toBeNull();
  });
  it("does not turn legacy state into a new run or delete it", () => {
    localStorage.setItem("codex-lb.active-member-switch-flow.v1", "legacy");
    expect(hasLegacyMemberFlow()).toBe(true);
    expect(readRunLocator()).toBeNull();
    expect(localStorage.getItem("codex-lb.active-member-switch-flow.v1")).toBe("legacy");
  });
  it("never uses malformed locator content as a run URL", () => {
    localStorage.setItem(RUN_LOCATOR_KEY, "../other-route"); expect(readRunLocator()).toBeNull();
  });
});
