/** The exact text the patient sends from WhatsApp to link their number (to the lab's number). */
export function linkInstruction(code: string, _labNumber: string): string {
  return `LINK ${code}`;
}
