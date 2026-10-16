# tally

A small expense notebook for the terminal.

    python3 app.py add food 5        record an expense
    python3 app.py total food        what food has cost so far
    python3 app.py export            every expense as CSV
    python3 app.py undo              made a mistake? remove the expense you added last
    python3 app.py import march.csv  bring in your bank's CSV export in one go

Your expenses stay in expenses.json in the current folder. If that file is ever damaged, tally refuses to
touch it and tells you so.
