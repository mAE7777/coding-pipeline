# Intent

Status: draft

## Goal
Keep a record of expenses in a web page and see what the expenses shown cost.

## Identity and promise
The expense page that adds up what you are looking at. CANARY-WEBDEMO-7713

## Who
Persona (blind): an adult using a desktop browser.
Someone who notes spending by category and checks what one category costs.

## Load-bearing behavior
The total is the sum of the expenses the list shows, and an amount that is not a number is refused with a message.

## Done examples
- I-D1 When food and travel expenses exist and the list shows only food, the total is the sum of the food expenses. Example: food 5, travel 40, Show food -> "Total: 5.00"
- I-D2 If the amount is not a number, the page says so and adds nothing. Example: amount "abc" -> "Enter an amount like 12.50", the list unchanged

## Mechanism cards
### Totals
Purpose: the cost of what is shown, at a glance.
Observable guarantee: the total follows the Show choice and equals the sum of the listed amounts.
Rejected imitation: one grand total over every expense, whatever the list shows.
Discriminating probe: two categories with different amounts; showing each one gives a different total.

## Must not lose
- L-01 No expense appears that the person did not enter · check: a refused amount adds no row

## Design intent
none

## Assumptions
- A-01 one person, one browser tab, nothing kept between visits in M1 · signed 2026-10-01

## Re-freeze log
