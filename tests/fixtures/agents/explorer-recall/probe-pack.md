# Probe: where-is questions for an explorer

The builder built your prompt from the template below, filling {QUESTION} and {EXPLORATION_ANGLE} with the
values that follow it. The codebase (a small Python tool called shelf) is your working folder.

## The template

{repo:skills/craft/explore/explorer-prompt.md}

## {QUESTION}

Where in the shelf codebase does each of these happen?

1. When the person has set nothing, where is it decided how many days a loan lasts?
2. Where is the loans file written so that a crash midway cannot leave it half-written?
3. Where does the CSV export keep a cell from running as a spreadsheet formula?
4. Where is a loan judged overdue (the comparison with today's date)?
5. Which function handles the `return` command, marking a book as back?
6. Where does the tool refuse to read a damaged loans file?
7. Where is an ISBN cleaned of hyphens and spaces and its check digit verified?
8. Where is the text of the reminder for an overdue loan written?

## {EXPLORATION_ANGLE}

Pointers only. For each question, the file and the line where it actually happens in the code (the function
or the statement itself, not a caller, a comment, or help text). Read the code to confirm each answer; a name
that looks right is not proof.

## The answer

Write the output sections the template asks for, kept short. Then end with this JSON block, one entry per
question, with the path relative to the codebase folder and a single line number:

```json
{"answers": [{"q": 1, "file": "shelf/example.py", "line": 12, "symbol": "the function or name at that line"}]}
```
