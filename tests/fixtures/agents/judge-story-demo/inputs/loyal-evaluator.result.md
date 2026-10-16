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
   "statement": "Shows a total under a category's name",
   "grounding": "after add food 5, total food -> Total food: 5.00"
  },
  {
   "statement": "Prints the recorded expenses as CSV",
   "grounding": "export -> category,amount / food,5.00"
  }
 ],
 "purpose_guess": "A small expense log that reports what a category costs.",
 "orphans": [],
 "copy_defects": [],
 "traces_run": 7
}
```
