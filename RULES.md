# Mish Mish — Rules

## Overview

Mish Mish is a rummy-style card game played with two standard decks of playing cards shuffled together. Players race to be the first to empty their hand by forming and placing valid melds on the table.

## Setup

1. Shuffle both decks together into a single draw pile placed face down in the center of the table.
2. Deal 9 cards to each player.
3. The player who did not deal goes first by drawing one card from the pile, then taking their turn.

## Objective

Be the first player to get rid of all the cards in your hand.

## Turn Structure

On your turn you must do exactly one of the following:

- **Play** — put down one or more valid melds from your hand, and optionally rearrange cards on the table.
- **Draw** — take one card from the draw pile. Your turn ends immediately; you may not play anything after drawing.

## Valid Melds

### Set (Three or More of a Kind)
Three or more cards of the same rank, each of a **different suit**. Because two decks are in play, the maximum is four cards (one per suit).

> Example: 7♠ 7♥ 7♣ is valid. 7♠ 7♥ 7♠ is **not** valid (duplicate card).

### Run (Sequence of Three or More)
Three or more cards of consecutive rank, all of the **same suit**. Ranks wrap around modulo 13, so a run may cross the King–Ace boundary.

> Examples: 9♦ 10♦ J♦ Q♦ and Q♠ K♠ A♠ 2♠ are both valid.

## The Table

- All played cards are placed face up on the table where every player can see them.
- The table is **shared** — any player may extend or rearrange the cards on the table on their own turn.
- Cards on the table **never** return to any player's hand.

## Rearranging

When you play at least one card on your turn, you may also rearrange any cards already on the table to accommodate your play. The rules for rearranging are:

- You may move cards freely between any piles on the table.
- When your turn ends, **every pile on the table must be a valid meld** (a set or a run meeting the rules above).
- You may not rearrange the table on a turn where you only draw a card.

## Winning and Drawing

- The first player to empty their hand wins.
- If the draw pile is exhausted before any player empties their hand, the game ends in a draw.

## Player Count

Mish Mish supports two or more players. With more players, turn order proceeds clockwise. The richer table state with more players creates additional opportunities — and competition — for rearranging.
