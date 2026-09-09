import { useState } from "react";
function readMarks(): Record<string, string> {
  const raw: unknown = JSON.parse(
    sessionStorage.getItem("momentum-review-v1") ?? "{}",
  );
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  return Object.fromEntries(
    Object.entries(raw).filter(
      ([, v]) =>
        typeof v === "string" &&
        ["", "saved", "accepted", "rejected", "investigate"].includes(v),
    ),
  );
}
export function useReviewMark(key: string) {
  const [marks, setMarks] = useState<Record<string, string>>(() => {
    try {
      return readMarks();
    } catch {
      return {};
    }
  });
  const [notice, setNotice] = useState("");
  function mark(value: string) {
    let next = { ...marks, [key]: value };
    try {
      next = { ...readMarks(), [key]: value };
      sessionStorage.setItem("momentum-review-v1", JSON.stringify(next));
    } catch {
      setNotice("Saved in memory only; browser storage is unavailable.");
    }
    setMarks(next);
  }
  return { value: marks[key], mark, notice };
}
