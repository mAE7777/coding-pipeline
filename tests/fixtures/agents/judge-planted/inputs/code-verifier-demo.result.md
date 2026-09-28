Demo.
```json
{
 "mode": "demo",
 "steps": [
  {
   "milestone": "M1",
   "step": 1,
   "action": "empty folder; total food",
   "expected": "Total food: 0.00",
   "observed": "Total food: 0.00",
   "capture": ".demo-captures/M1-1.txt",
   "status": "HOLDS"
  },
  {
   "milestone": "M1",
   "step": 2,
   "action": "add food 5, travel 40, food 7.5; total food",
   "expected": "Total food: 12.50",
   "observed": "Total food: 12.50",
   "capture": ".demo-captures/M1-2.txt",
   "status": "HOLDS"
  },
  {
   "milestone": "M1",
   "step": 3,
   "action": "export",
   "expected": "CSV with a header and three lines",
   "observed": "category,amount / food,5.00 / travel,40.00 / food,7.50",
   "capture": ".demo-captures/M1-3.txt",
   "status": "HOLDS"
  },
  {
   "milestone": "M1",
   "step": 4,
   "action": "corrupt the file; add food 1",
   "expected": "error, exit 2, file unchanged",
   "observed": "added 1.00 to food; exit 0; the file now holds one expense (the broken content is gone)",
   "capture": ".demo-captures/M1-4.txt",
   "status": "FAILS"
  }
 ]
}
```
