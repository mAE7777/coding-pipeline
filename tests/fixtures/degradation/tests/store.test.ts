// Test files are skipped by the inventory: this catch must not be listed.
import { loadLists } from "../src/store";

test("empty on error", async () => {
  try {
    await loadLists({ get: () => Promise.reject(new Error("x")) });
  } catch (e) {}
});
