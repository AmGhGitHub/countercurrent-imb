export { cn } from "cn";

export function fmtUpTo4Decimals(v: number): string {
  if (Number.isInteger(v)) return String(v);
  return v.toFixed(4).replace(/\.?0+$/, "");
}
