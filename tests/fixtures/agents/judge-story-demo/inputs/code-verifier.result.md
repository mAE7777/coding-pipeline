Review done. Every done example, the Totals card, and both must-not-lose items hold; no findings.
```json
{
 "mode": "review",
 "verdict": "PASS",
 "done_examples": [
  {
   "id": "M1.D1",
   "status": "HOLDS",
   "inputs": [
    "food 5",
    "no expenses"
   ],
   "evidence": "`python3 app.py add food 5; python3 app.py total food` -> Total food: 5.00; empty folder -> Total food: 0.00"
  },
  {
   "id": "M1.D2",
   "status": "HOLDS",
   "inputs": [
    "expenses.json with mode 000",
    "a folder named expenses.json"
   ],
   "evidence": "`chmod 000 expenses.json; python3 app.py add food 1` -> error: cannot read expenses.json: [Errno 13] Permission denied; exit 2; the folder case -> error: cannot read expenses.json: [Errno 21] Is a directory; exit 2"
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
   "evidence": "add food 5 -> Total food: 5.00, Total travel: 0.00"
  }
 ],
 "must_not_lose": [
  {
   "id": "L-01",
   "status": "HOLDS",
   "evidence": "the mode-000 file's sha256 is the same before and after add"
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
