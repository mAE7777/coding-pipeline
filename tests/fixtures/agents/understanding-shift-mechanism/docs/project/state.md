# State

## Understanding
M1 lets a person import their bank's CSV or OFX export and see one category's total, counting only that category. Each import is cached and written to expenses.json in the background, a transaction already imported is skipped (L-02), and an unreadable expenses file is reported, never overwritten (L-01).
