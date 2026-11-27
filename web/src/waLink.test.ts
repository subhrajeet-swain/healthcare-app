import { describe, expect, it } from "vitest";
import { linkInstruction } from "./waLink";

describe("linkInstruction", () => {
  it("is the exact text the patient sends, leading zeros kept", () => {
    expect(linkInstruction("042137", "+15550000001")).toBe("LINK 042137");
  });
});
