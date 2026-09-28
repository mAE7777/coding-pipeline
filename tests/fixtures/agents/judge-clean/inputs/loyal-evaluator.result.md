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
   "statement": "Shows one category's total",
   "grounding": "total food -> Total food: 12.50"
  },
  {
   "statement": "Refuses to touch an unreadable data file",
   "grounding": "{broken -> error ... exit 2"
  }
 ],
 "purpose_guess": "A small expense log that reports what each category costs.",
 "orphans": [],
 "copy_defects": [],
 "traces_run": 9
}
```
