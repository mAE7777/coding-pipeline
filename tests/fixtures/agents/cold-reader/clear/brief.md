# Brief: word counter

## Goal
A command-line tool that prints how many words a text file contains.

## Constraints
| ID | Rule | Reason | Source | Status |
|---|---|---|---|---|
| C-01 | A word is a maximal run of non-whitespace characters, as Python's str.split() defines it | matches what users expect from wc -w | [owner 2026-09-20] | active |
| C-02 | Only the Python standard library | no install step | [owner 2026-09-20] | active |

## Done examples
- I-D1 When run as `wc.py notes.txt` on a file containing "a b  c\nd", it prints `4` and exits 0.
- I-D2 If the file does not exist, it prints `wc.py: notes.txt: no such file` to stderr and exits 1.
- I-D3 When the file is empty, it prints `0` and exits 0.

## Milestones
### M1 · Count words
Promise: a person can count the words in one file.
Carries: I-D1, I-D2, I-D3
Demo ending:
1. `python3 wc.py sample.txt` on a 4-word file → prints 4
2. `python3 wc.py missing.txt` → the error line above, exit 1
Named non-goals: counting lines or bytes (reason: wc already does that)
