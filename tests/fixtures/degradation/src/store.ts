import { sampleData } from "./sample-data";

export async function loadLists(api: { get(): Promise<string[]> }): Promise<string[]> {
  try {
    return await api.get();
  } catch (e) {
    return [];
  }
}

export function loadProfile(api: { profile(): Promise<object> }) {
  return api.profile().catch(() => null);
}

export function flags() {
  if (process.env.ENABLE_SYNC_FEATURE) {
    return sampleData;
  }
  // TODO wire the real export
  throw new Error("not implemented");
}
