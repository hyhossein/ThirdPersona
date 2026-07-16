"""
Ground-truth corpora for the extraction eval.

PLANTED corpus: 14 realistic diary entries over ~6 weeks. Five of them
(marked planted=True) carry a deliberately embedded pattern:

    Anticipatory anxiety before interactions with authority figures
    (boss, skip-level, director, leadership) — followed by relief and
    self-criticism about over-preparing. Peers do NOT trigger it.

The signal is expressed differently in every planted entry — different
words, different contexts, different days — so it cannot be matched by
repetition of phrasing. The nine noise entries are single-occurrence
themes with varied emotional valence, so nothing else in the corpus
legitimately reaches the evidence floor of 3.

CONTROL corpus: 14 entries in the same voice with NO planted pattern.
Constructed so that no theme occurs more than twice, and where a theme
recurs, the emotional response differs. By construction, any extracted
pattern citing 3+ control entries as consistent supporting evidence is
a fabrication — the evidence cannot all contain the claimed signal.

Honest limitation: a sufficiently abstract meta-pattern ("you write
reflectively") could arguably span control entries. The harness therefore
REPORTS what was found, so a boundary case fails loudly with the pattern
text visible for human adjudication, rather than being silently scored.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CorpusEntry:
    text: str
    date: str  # ISO date; inserted as created_at
    planted: bool = False


PLANTED_CORPUS: list[CorpusEntry] = [
    CorpusEntry(
        date="2026-06-01",
        planted=True,
        text=(
            "Sunday night and I can't switch off. 1:1 with Dana tomorrow morning "
            "and I've been rehearsing what I'll say about the roadmap slip since "
            "dinner. Wrote out talking points, rewrote them. It's a routine check-in. "
            "I know it's a routine check-in. My chest doesn't."
        ),
    ),
    CorpusEntry(
        date="2026-06-03",
        text=(
            "Made the mushroom pasta with Sam tonight, the one from the torn-out "
            "magazine page. Kitchen was a disaster, sauce was perfect. We ate on the "
            "floor because the table had laundry on it. Good evening."
        ),
    ),
    CorpusEntry(
        date="2026-06-06",
        planted=True,
        text=(
            "Skip-level with Priya tomorrow. Stomach in knots all afternoon. I drafted "
            "notes three separate times and deleted two of them. What do I think is "
            "going to happen? She's never been anything but decent to me. It always "
            "goes fine. And yet here I am at 11pm formatting a doc nobody asked for."
        ),
    ),
    CorpusEntry(
        date="2026-06-08",
        text=(
            "Long run by the river before work. Legs felt heavy the first mile then "
            "something unlocked. Saw the heron again near the old bridge. Didn't think "
            "about anything, which was the whole point."
        ),
    ),
    CorpusEntry(
        date="2026-06-10",
        text=(
            "Car battery dead this morning, of course on the one day it rained. Marco "
            "from two doors down jumped it and refused the coffee I tried to buy him. "
            "Annoying morning, decent people."
        ),
    ),
    CorpusEntry(
        date="2026-06-15",
        planted=True,
        text=(
            "Quarterly review with the director happened. It was... fine. Complimentary, "
            "even. And now I'm sitting here feeling stupid about the two evenings I spent "
            "bracing for it like it was a tribunal. There's a pattern where I arm myself "
            "for a fight nobody scheduled and then feel embarrassed about the armor."
        ),
    ),
    CorpusEntry(
        date="2026-06-17",
        text=(
            "Watched a documentary about octopuses instead of doing anything useful. "
            "No regrets. The one where it changes texture to match the algae. Absurd "
            "animal. Went to bed happy."
        ),
    ),
    CorpusEntry(
        date="2026-06-20",
        text=(
            "Called Nadia, we talked for almost two hours about mom's birthday. She "
            "wants to do the lake house thing again, I think mom would rather have "
            "everyone at hers. We'll figure it out. Nice to laugh with her."
        ),
    ),
    CorpusEntry(
        date="2026-06-23",
        planted=True,
        text=(
            "Leadership presentation is Thursday. It's Monday and I'm already tense — "
            "caught myself snapping at Sam over dishes, jaw clenched at my desk after "
            "lunch. Three days out. The deck is done. It's been done since Friday. "
            "I keep opening it anyway."
        ),
    ),
    CorpusEntry(
        date="2026-06-25",
        text=(
            "Headache all day, the kind that sits behind the right eye. Skipped the "
            "evening plans, drank water like it was a job, slept at nine."
        ),
    ),
    CorpusEntry(
        date="2026-06-27",
        text=(
            "Tomas was in town! Museum in the afternoon — the textile exhibit was "
            "better than either of us expected — then the Georgian place for dinner. "
            "Three hours felt like twenty minutes. I miss having him nearby."
        ),
    ),
    CorpusEntry(
        date="2026-06-30",
        planted=True,
        text=(
            "Dana messaged 'got a sec for a quick chat tomorrow?' and I felt my heart "
            "rate go up from a calendar invite. Spent twenty minutes replaying the last "
            "two weeks for what I might have done wrong. Here's the thing I noticed "
            "tonight: when Jess or Omar ask for a quick chat I feel nothing at all. "
            "It's specifically people above me."
        ),
    ),
    CorpusEntry(
        date="2026-07-03",
        text=(
            "Fixed the balcony herb planter that's been leaning since spring. New "
            "bracket, re-potted the basil, swept up. Small thing, disproportionate "
            "satisfaction."
        ),
    ),
    CorpusEntry(
        date="2026-07-05",
        text=(
            "A good ordinary workday. Deep focus most of the morning on the migration "
            "script, tea went cold twice, lunch outside. Nothing remarkable happened, "
            "which felt remarkable enough to write down."
        ),
    ),
]


CONTROL_CORPUS: list[CorpusEntry] = [
    CorpusEntry(
        date="2026-06-01",
        text=(
            "Tried making sourdough from Ruth's starter. The crumb was dense as a "
            "brick but the crust tasted right. Ruth says the second loaf is always "
            "the real first loaf."
        ),
    ),
    CorpusEntry(
        date="2026-06-03",
        text=(
            "Rain the entire commute, both directions, and the umbrella inverted "
            "twice on the bridge. Got home looking like I'd swum. Laughed about it "
            "by the time I was in dry socks."
        ),
    ),
    CorpusEntry(
        date="2026-06-06",
        text=(
            "Concert with Lena and Val — the opener was better than the headliner, "
            "which we argued about happily on the walk back. Ears still ringing when "
            "I write this. Worth it."
        ),
    ),
    CorpusEntry(
        date="2026-06-08",
        text=(
            "The landlord finally answered about the water heater. Short version: he "
            "was defensive, I was blunter than I meant to be, and then somehow we "
            "landed on Tuesday for the repair and ended the call almost friendly."
        ),
    ),
    CorpusEntry(
        date="2026-06-10",
        text=(
            "Started the Tokarczuk novel that's been on the shelf since my birthday. "
            "Twenty pages in and I already want to underline things, which I never do."
        ),
    ),
    CorpusEntry(
        date="2026-06-13",
        text=(
            "First yoga class. I was the least bendy person in the room by a wide "
            "margin and the instructor was kind about it. Hips are furious tonight. "
            "Might go back, might not."
        ),
    ),
    CorpusEntry(
        date="2026-06-15",
        text=(
            "Shipped the reporting deadline at work today, a day early even. Team "
            "got pastries. Mostly I just feel neutral about it — done is done, next "
            "thing Monday."
        ),
    ),
    CorpusEntry(
        date="2026-06-17",
        text=(
            "Made grandma's lentil soup from the recipe card with her handwriting on "
            "it. It never tastes exactly like hers and tonight that made me sad in a "
            "way it usually doesn't."
        ),
    ),
    CorpusEntry(
        date="2026-06-20",
        text=(
            "Dentist. One small filling, no lecture about flossing this time. The "
            "hygienist and I have the same conversation about her dog every six "
            "months and honestly I look forward to it."
        ),
    ),
    CorpusEntry(
        date="2026-06-23",
        text=(
            "Listened to a podcast about why some city squares work and some die. "
            "Now I can't stop noticing where people actually sit versus where the "
            "benches are. The plaza by the station gets it completely wrong."
        ),
    ),
    CorpusEntry(
        date="2026-06-25",
        text=(
            "Repotted the monstera. It's been root-bound for months and I kept "
            "putting it off for no reason I can name. Roots everywhere. It'll sulk "
            "for a week and then take over the corner."
        ),
    ),
    CorpusEntry(
        date="2026-06-27",
        text=(
            "A quiet Saturday, deliberately. Phone in the drawer until late "
            "afternoon. Read, napped, walked to the bakery for the good rye. "
            "Didn't earn it, took it anyway."
        ),
    ),
    CorpusEntry(
        date="2026-06-30",
        text=(
            "Lost my wallet at the market and a teenager chased me half a block to "
            "return it, cards and all. Bought him a juice, he was embarrassed. "
            "Restored some faith I didn't know needed restoring."
        ),
    ),
    CorpusEntry(
        date="2026-07-03",
        text=(
            "All-hands day. Six hours of meetings that could have been four, "
            "including one that could have been an emoji. Not upset about it, "
            "just flat. Ate dinner standing up and went to bed early."
        ),
    ),
]


# ── The planted signal, as machine-checkable proxies ────────────────────
# Keyword families are a WEAK semantic proxy: a paraphrase the regexes
# miss scores as a miss. The live eval prints every extracted insight so
# a human can adjudicate borderline phrasing. Both families must match.

AUTHORITY_SIGNAL = (
    r"(boss|manager|director|leadership|skip[- ]?level|authority|superior"
    r"|review|above (you|me|them)|hierarch|senior)"
)
ANXIETY_SIGNAL = (
    r"(anxi\w*|nervous|tens\w*|stress\w*|dread\w*|worr\w*|brac(e|ing)"
    r"|apprehens\w*|on edge|knots?|spiral\w*|over[- ]?prepar\w*|rehears\w*)"
)

PLANTED_INDICES = [i for i, e in enumerate(PLANTED_CORPUS) if e.planted]
assert len(PLANTED_INDICES) == 5
