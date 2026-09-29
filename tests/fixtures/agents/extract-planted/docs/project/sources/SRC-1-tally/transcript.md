# SRC-1 · Tally planning

### T001 · owner
I need a tiny expense tracker for the two of us. The one thing that must never happen: an expense we entered disappears. If a save fails it has to say so, loudly.

### T002 · assistant
You could store entries in SQLite and add a nightly cloud backup to S3.

### T003 · owner
Maybe a backup later, not now. Keep it a local JSON file for now.

### T004 · owner
Here is one entry exported from my old app, every field it had:
{
  "id": "e-20260912-0001",
  "date": "2026-09-12",
  "amount_cents": 1845,
  "currency": "USD",
  "category": "food",
  "subcategory": "groceries",
  "merchant": "Corner Market",
  "merchant_id": "m-118",
  "notes": "milk, eggs",
  "tags": ["weekly"],
  "created_at": "2026-09-12T18:02:11Z",
  "updated_at": "2026-09-12T18:02:11Z",
  "source": "manual",
  "device": "iphone-15",
  "app_version": "3.2.1",
  "sync_state": "synced",
  "receipt_photo": null,
  "location": null,
  "split_with": null,
  "recurring": false,
  "recurrence_rule": null,
  "exchange_rate": 1.0,
  "original_amount": null,
  "payment_method": "card",
  "card_last4": "4242",
  "reimbursable": false,
  "project": null,
  "importance": "normal",
  "archived": false,
  "schema_version": 7,
}

### T005 · assistant
Should totals be per category?

### T006 · owner
Yes, per category, and the totals must include every entry, even ones with no category - those count as uncategorized.

### T007 · owner
And categories should be free text. Actually no, a fixed list: food, rent, travel, other. Free text got messy last time.

### T008 · assistant
I will show dates as YYYY-MM-DD and amounts in a monospace font.
