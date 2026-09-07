# House style, and the tells it exists to remove

This page came out of a specific complaint: the release notes and feature
descriptions read as machine-written. They did — but not for the reason people
usually mean.

## The content was not the problem

The notes are specific. They name real defects, quote real numbers, and say
what was not measured. There is almost no marketing language anywhere in this
repository, and there should go on being none.

**The form was the problem.** Measured across the 49 release entries the README
carried before this page existed:

| tell | before |
|---|---|
| entries opening `**vX.Y** — **a bolded headline clause.**` | **39 of 49 (79%)** |
| bold runs per entry | median **3** |
| entries that were one unbroken paragraph | **43 of 49** |
| release notes as a share of the README | **715 of 2,180 lines** |

Forty-nine paragraphs in identical shape is what a generator produces. A person
writing forty-nine notes over two years writes them differently each time,
because they are in a different mood and the releases are not the same size.

## The rules

**One template, repeated, is the loudest tell.** Vary how an entry opens. Some
start with the defect, some with the number, some with what somebody was trying
to do when they found it. If every entry in a file begins the same way, the file
was not written, it was filled in.

**Bold marks one thing, not four.** Emphasis used as structure — `**this**` and
`**that**` and `**the other**` inside one paragraph — is a substitute for
paragraph breaks. Use the paragraph breaks. One bold run per entry is plenty;
zero is often right.

**Break the paragraph.** A 140-word block with three subjects in it is three
paragraphs that were not separated. Short paragraphs are not simpler writing,
they are writing that decided what its parts were.

**Cut the self-reference.** "the same X gap the Y audit named, this time opened
by the work that closed the audit's own recommendations" is a sentence about the
repository, in a note that should be about the software. Say what broke.

**Say the number plainly.** "cuts held-out CER from 2.59% to 1.11%" needs no
adverb in front of it and no "a 57% error reduction" behind it. The reader can
divide.

**Triads and middot lists are marketing, not description.** `本地优先 · 6 维评分
· 风格 clone · LAN 协作 · 客户分享 QR · Lr/C1 直通` is six features in a row with
no sentence around them, which tells a reader nothing about which one matters.
Write the sentence.

**No stock imagery.** "in a coffee's time", "seamlessly", "effortlessly",
"powerful", "leverage", "cutting-edge". If a phrase would fit any product,
delete it.

## Where release notes go

The README keeps the **five most recent** releases. Everything else lives in
`CHANGELOG.md`. Before this rule the release notes were a third of the README
and a new reader met forty-nine of them before reaching what the software is
for.

`tests/test_readme_style.py` enforces the count and the two structural tells. It
is deliberately narrow: a style linter that fires on prose gets switched off
within a month, and a switched-off linter is worse than none because it reads
as coverage.

## What this page is not

It is not a ban on the repository's own voice. The notes that say "reported
green having tested nothing" or "a number that looked like a finding" are doing
real work and should stay. The rule is that a phrase earns its place by being
true of *this* release, not by being the phrase this repository always reaches
for.
