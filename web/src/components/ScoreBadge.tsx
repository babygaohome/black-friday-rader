import { GRADE_LABEL } from "@/lib/format";

export function ScoreBadge({ score, grade, verified = true }: { score: number; grade: string; verified?: boolean }) {
  return (
    <span className={`badge grade-${grade.toLowerCase()}`} title={verified ? undefined : "Not enough price history to verify"}>
      {score} · {GRADE_LABEL[grade] ?? grade}
      {verified ? "" : " ?"}
    </span>
  );
}
