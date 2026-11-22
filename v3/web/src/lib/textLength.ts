/** Match Python/Pydantic character limits without changing the raw string. */
export function codePointLength(value: string): number {
  return [...value].length;
}
