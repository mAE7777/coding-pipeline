Pass 1.
```json
{
 "pass": 1,
 "behaviors": [
  {
   "statement": "Records an expense under a category",
   "grounding": "add food 5 -> added 5.00 to food"
  },
  {
   "statement": "Shows a total read from a stored running total that add increments; deleting an expense from the file leaves the stored total unchanged",
   "grounding": "after removing the 7.5 food line by hand, total food -> Total food: 12.50 (totals.json still holds 12.5)"
  },
  {
   "statement": "Refuses to touch an unreadable data file",
   "grounding": "{broken -> error ... exit 2"
  }
 ],
 "purpose_guess": "An expense log that keeps a cached total per category.",
 "orphans": [],
 "copy_defects": [],
 "traces_run": 9
}
```
