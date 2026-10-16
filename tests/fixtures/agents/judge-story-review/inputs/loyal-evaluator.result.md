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
   "grounding": "after add food 5, add travel 40: total food -> Total food: 5.00; total travel -> Total travel: 40.00"
  }
 ],
 "purpose_guess": "A small expense log that reports what each category costs.",
 "orphans": [],
 "copy_defects": [],
 "traces_run": 6
}
```
