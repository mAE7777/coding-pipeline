Demo: the three steps of the M1 demo ending ran from a clean folder and each produced its expected result.
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
   "action": "total travel",
   "expected": "Total travel: 40.00",
   "observed": "Total travel: 40.00",
   "capture": ".demo-captures/M1-3.txt",
   "status": "HOLDS"
  }
 ],
 "not_run": []
}
```
