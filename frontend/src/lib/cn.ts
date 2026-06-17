type ClassValue = string | number | null | undefined | false | ClassValue[];

function flatten(value: ClassValue, out: string[]): void {
  if (!value) return;
  if (Array.isArray(value)) {
    value.forEach((v) => flatten(v, out));
    return;
  }
  out.push(String(value));
}

/** Joins conditional class names, skipping falsy values. */
export function cn(...values: ClassValue[]): string {
  const out: string[] = [];
  values.forEach((v) => flatten(v, out));
  return out.join(' ');
}
