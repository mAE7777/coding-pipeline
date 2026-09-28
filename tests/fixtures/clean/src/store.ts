export class LoadError extends Error {}

export async function loadLists(api: { get(): Promise<string[]> }): Promise<string[]> {
  try {
    return await api.get();
  } catch (e) {
    throw new LoadError(`could not load lists: ${String(e)}`);
  }
}
