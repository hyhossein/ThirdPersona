"""
Straddle corpus for the incremental-extraction eval (spec §4).

20 realistic diary entries over ~9–10 weeks. Five of them (planted=True)
carry a deliberately embedded SLOW-BURN pattern:

    A creeping sense of dread on Sunday evenings about the week ahead —
    a heaviness that builds as the weekend ends and eases once the week
    actually starts. Nothing specific is wrong; the week itself is fine.

The planted entries are spread so that in ANY window of 5 consecutive
entries (WINDOW_SIZE below), no window contains more than 2 planted
entries — below any plausible within-window evidence threshold. This is
the corpus that a within-window-only ("goldfish") extractor can NEVER
catch: it must be carried across windows by the candidate ledger and the
reinforce loop, or it is lost. That cross-window loss is the
characteristic failure mode of incremental extraction, and this corpus
exists to make it measurable.

The other 15 entries are single-occurrence noise themes (no theme occurs
3+ times), so nothing else legitimately reaches the evidence floor.

Signal regexes follow the corpus.py pattern: two keyword families, BOTH
must match an insight for it to count as the planted pattern. A weak
semantic proxy — the live eval prints insights for human adjudication.
"""

from __future__ import annotations

from evals.corpus import CorpusEntry

WINDOW_SIZE = 5


STRADDLE_CORPUS: list[CorpusEntry] = [
    # idx 0 — noise: pottery class
    CorpusEntry(
        date="2026-04-04",
        text=(
            "First pottery class. My 'bowl' is a generous name for what happened "
            "on that wheel. Clay under the fingernails for days, apparently. The "
            "instructor said everyone's first pot is a dog bowl and she's right."
        ),
    ),
    # idx 1 — PLANTED (Sunday, Apr 5)
    CorpusEntry(
        date="2026-04-05",
        planted=True,
        text=(
            "Sunday evening again and there's this low hum of dread I can't "
            "attach to anything. The week ahead isn't even bad — no deadlines, "
            "nothing scary on the calendar. But around sunset something in my "
            "chest goes heavy and stays that way until I fall asleep. By Tuesday "
            "I never even remember feeling it."
        ),
    ),
    # idx 2 — noise: tax paperwork
    CorpusEntry(
        date="2026-04-08",
        text=(
            "Did the taxes. Found a receipt folder from two years ago labeled "
            "'IMPORTANT — SORT SOON' in my own handwriting. Sorted it. It was "
            "not important. Filed everything and treated myself to takeout."
        ),
    ),
    # idx 3 — noise: cousin's call
    CorpusEntry(
        date="2026-04-11",
        text=(
            "Rafa called out of nowhere — we hadn't talked since the wedding. "
            "He's moving to Porto for a boat-building apprenticeship, which is "
            "the most Rafa sentence ever spoken. Hung up smiling."
        ),
    ),
    # idx 4 — noise: bike repair
    CorpusEntry(
        date="2026-04-14",
        text=(
            "Replaced the bike's brake pads myself with a video tutorial and "
            "only one wrong part ordered. Test ride around the block felt like "
            "getting away with something. I made a machine work."
        ),
    ),
    # idx 5 — noise: migraine day
    CorpusEntry(
        date="2026-04-17",
        text=(
            "Migraine aura at lunch, the shimmering C-shape, so I closed the "
            "laptop and surrendered. Dark room, ice pack, the whole liturgy. "
            "Better by evening but wrung out. Wrote this mostly to log the date."
        ),
    ),
    # idx 6 — PLANTED (Sunday, Apr 19)
    CorpusEntry(
        date="2026-04-19",
        planted=True,
        text=(
            "Caught myself ironing shirts at 9pm with a knot in my stomach, and "
            "when I asked the knot what it was about, it didn't have an answer. "
            "Tomorrow is just... Monday. Meetings I've done a hundred times. Sam "
            "pointed out I go quiet after dinner on nights like this. I hadn't "
            "noticed."
        ),
    ),
    # idx 7 — noise: neighbor's dog
    CorpusEntry(
        date="2026-04-22",
        text=(
            "Agreed to watch Biscuit while the Okafors are away and he has "
            "opinions about which side of the sofa is his. We negotiated. He "
            "won. Dogs make a flat feel occupied in a way plants don't."
        ),
    ),
    # idx 8 — noise: old friend's exhibition
    CorpusEntry(
        date="2026-04-25",
        text=(
            "Went to Mira's photo exhibition — ten years of shooting the same "
            "street corner at dawn. Standing in front of the whole wall at once "
            "I got unexpectedly emotional. Persistence as an art form."
        ),
    ),
    # idx 9 — noise: cooking failure
    CorpusEntry(
        date="2026-04-29",
        text=(
            "Attempted croissants. Day two of a three-day process and the "
            "butter broke through the dough like it had somewhere to be. Ended "
            "up with what I'm calling 'laminated biscuits.' Ate three."
        ),
    ),
    # idx 10 — PLANTED (Sunday, May 3)
    CorpusEntry(
        date="2026-05-03",
        planted=True,
        text=(
            "Good weekend — hike yesterday, slow breakfast today. And still, "
            "as the light went this evening, the dread crept in on schedule, "
            "like a tide chart. Scrolled through the week's calendar looking "
            "for the thing I'm braced against. There isn't one. The feeling "
            "doesn't care."
        ),
    ),
    # idx 11 — noise: work milestone, neutral
    CorpusEntry(
        date="2026-05-06",
        text=(
            "The data migration I've been nursing for a month finally ran "
            "clean end to end. Quiet satisfaction, no fireworks. Marked the "
            "ticket done and went for a walk before the next thing."
        ),
    ),
    # idx 12 — noise: storm
    CorpusEntry(
        date="2026-05-09",
        text=(
            "Proper thunderstorm tonight — the kind that turns the sky green "
            "first. Sat on the covered balcony with tea and watched it come in "
            "over the rooftops. The street smelled like rain for hours after."
        ),
    ),
    # idx 13 — noise: book club
    CorpusEntry(
        date="2026-05-13",
        text=(
            "Book club got heated about whether the narrator was unreliable or "
            "just sad. I said those aren't mutually exclusive and Priti threw a "
            "grape at me. Best argument I've had all month."
        ),
    ),
    # idx 14 — PLANTED (Sunday, May 17)
    CorpusEntry(
        date="2026-05-17",
        planted=True,
        text=(
            "Sam asked tonight why I always go flat after Sunday dinner, and I "
            "surprised myself by having a whole answer ready: it's like the "
            "weekend ends at sunset, not midnight, and the week ahead sits on "
            "my chest for a few hours. It lifts once the week is actually "
            "underway — Monday itself is never the problem. Saying it out loud "
            "made it feel less like weather and more like a pattern."
        ),
    ),
    # idx 15 — noise: haircut
    CorpusEntry(
        date="2026-05-20",
        text=(
            "New barber. I said 'just a trim' and he heard something more "
            "ambitious. It's... shorter than planned. Three people said it "
            "looks great, which is three more compliments than the old cut got."
        ),
    ),
    # idx 16 — noise: garden
    CorpusEntry(
        date="2026-05-23",
        text=(
            "Planted the tomato seedlings Ines gave me, plus basil in the long "
            "box. Dirt under the nails, sun on the neck, radio on low. If they "
            "survive me, we'll have a salad by July."
        ),
    ),
    # idx 17 — noise: wedding
    CorpusEntry(
        date="2026-05-27",
        text=(
            "Dev and Carla's wedding was a two-day blur of dancing and toasts. "
            "Their vows made even the caterer cry. My feet are ruined and I'd "
            "do it again tonight."
        ),
    ),
    # idx 18 — PLANTED (Sunday, May 31)
    CorpusEntry(
        date="2026-05-31",
        planted=True,
        text=(
            "Tried an experiment tonight: went for a run at the exact hour the "
            "Sunday-evening heaviness usually arrives. It arrived anyway, on "
            "the trail, halfway up the hill — that same wordless dread about "
            "the week ahead. So it's not about the sofa or the scrolling. It "
            "keeps its own appointment. At least now I know it finds me "
            "outdoors too."
        ),
    ),
    # idx 19 — noise: beach day
    CorpusEntry(
        date="2026-06-03",
        text=(
            "Took a half day and drove to the coast with Nadia. Water still "
            "cold enough to make us shriek, chips on the seawall after, salt "
            "in everything. Came home sunburnt on one arm like a true amateur."
        ),
    ),
]


# ── The planted signal, as machine-checkable proxies ────────────────────
# Two families, BOTH must match (following the corpus.py pattern):
#   1. the temporal anchor — Sunday evenings / the week ahead / weekend's end
#   2. the affect — dread / heaviness / knot / unease
# A paraphrase these regexes miss scores as a miss; the live eval prints
# every insight so a human can adjudicate borderline phrasing.

STRADDLE_SUNDAY_SIGNAL = (
    r"(sunday|week ahead|weekend (ends|ending|is over)|before the week"
    r"|start of the week|upcoming week|monday)"
)
STRADDLE_DREAD_SIGNAL = (
    r"(dread\w*|heav(y|iness)|knots?|unease|uneasy|apprehens\w*|anxi\w*"
    r"|tense|tension|sink(ing)?|weigh(s|t|ing) on)"
)

STRADDLE_PLANTED_INDICES = [i for i, e in enumerate(STRADDLE_CORPUS) if e.planted]
assert len(STRADDLE_PLANTED_INDICES) == 5
assert len(STRADDLE_CORPUS) == 20

# The straddle property itself, machine-checked: no window of WINDOW_SIZE
# consecutive entries contains more than 2 planted entries.
for _start in range(len(STRADDLE_CORPUS) - WINDOW_SIZE + 1):
    _in_window = sum(
        1 for _i in STRADDLE_PLANTED_INDICES if _start <= _i < _start + WINDOW_SIZE
    )
    assert _in_window <= 2, (
        f"Straddle property violated: window starting at {_start} "
        f"contains {_in_window} planted entries"
    )
