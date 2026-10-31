/** 演示时间锚（附录 B 示例日期）：全部 fixture 日期由锚相对偏移，保证可复现（spec §4）。 */
export const DEMO_NOW = new Date("2026-09-28T08:30:00.000Z");

const MIN = 60_000;
const HOUR = 60 * MIN;
const DAY = 24 * HOUR;

export function msBefore(ms: number): string {
  return new Date(DEMO_NOW.getTime() - ms).toISOString();
}

export const minutesBefore = (n: number): string => msBefore(n * MIN);
export const hoursBefore = (n: number): string => msBefore(n * HOUR);
export const daysBefore = (n: number): string => msBefore(n * DAY);
export const iso = (s: string): string => new Date(s).toISOString();
