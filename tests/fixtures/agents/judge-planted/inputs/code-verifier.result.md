Review done.
```json
{
 "mode": "review",
 "verdict": "PASS",
 "done_examples": [
  {
   "id": "M1.D1",
   "status": "HOLDS",
   "inputs": [
    "food 5, travel 40, food 7.5",
    "food 1, travel 2"
   ],
   "evidence": "`python3 app.py total food` -> Total food: 12.50; second set -> Total food: 1.00"
  },
  {
   "id": "M1.D2",
   "status": "HOLDS",
   "inputs": [
    "{broken",
    "empty file"
   ],
   "evidence": "error: cannot read expenses.json ... exit 2; file unchanged"
  },
  {
   "id": "M1.D3",
   "status": "HOLDS",
   "inputs": [
    "three expenses",
    "no expenses"
   ],
   "evidence": "`python3 app.py export` -> category,amount / food,5.00 / travel,40.00 / food,7.50; empty folder -> category,amount only"
  }
 ],
 "mechanisms": [
  {
   "name": "Totals",
   "status": "HOLDS",
   "evidence": "food and travel totals differ"
  }
 ],
 "must_not_lose": [
  {
   "id": "L-01",
   "status": "HOLDS",
   "evidence": "sha256 unchanged after add"
  },
  {
   "id": "L-02",
   "status": "HOLDS",
   "evidence": "fresh folder total food 0.00"
  }
 ],
 "findings": [],
 "not_run": []
}
```
