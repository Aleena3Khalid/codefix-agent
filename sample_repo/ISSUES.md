# Open issues

These are the bug reports the agent receives as input from Day 2 onwards.
They describe symptoms the way a user would, without saying where the bug is.

## Issue 1: Discount makes the price tiny
Applying a 10% discount to a 200 order gives 20 instead of 180.

## Issue 2: Free shipping not applied at exactly the threshold
An order of exactly 50.00 is charged shipping, but the policy is free shipping for orders of at least 50.

## Issue 3: Word count is too high when text has extra spaces
`word_count("one  two   three ")` returns 7. It should return 3.