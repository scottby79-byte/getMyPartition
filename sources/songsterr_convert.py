"""Convert Songsterr note JSON into a PyGuitarPro Song (-> .gp5 file).

Songsterr's note model maps remarkably cleanly onto Guitar Pro because it *is*
derived from the GP format: bend/tremolo positions are 0-60, bend values use
25-per-quarter-tone, durations are note-value + dots + an exact fraction, and
string indices run high-to-low just like GP. This module does the mapping and
leans on PyGuitarPro to emit a valid binary .gp5.
"""
from __future__ import annotations

from fractions import Fraction

import guitarpro as gp
from guitarpro import models as m

WHOLE = m.Duration.quarterTime * 4  # ticks in a whole note (3840)
MAX_GP_STRINGS = 7  # GP5's per-beat string bitmask only has room for 7 strings

# Music symbols and typography that aren't in cp1252 (the GP5 string encoding).
_SYMBOLS = {
    "♯": "#", "♭": "b", "♮": "", "‘": "'", "’": "'",
    "“": '"', "”": '"', "–": "-", "—": "-", "…": "...",
    " ": " ", "′": "'", "″": '"',
}


def _clean(s):
    """Coerce text to something the cp1252-based GP5 writer can encode."""
    if not s:
        return s
    s = "".join(_SYMBOLS.get(c, c) for c in s)
    return s.encode("cp1252", "replace").decode("cp1252")

# --- small lookup tables -------------------------------------------------

DYNAMICS = {
    "ppp": m.Velocities.pianoPianissimo, "pp": m.Velocities.pianissimo,
    "p": m.Velocities.piano, "mp": m.Velocities.mezzoPiano,
    "mf": m.Velocities.mezzoForte, "f": m.Velocities.forte,
    "ff": m.Velocities.fortissimo, "fff": m.Velocities.forteFortissimo,
}

SLIDES = {
    "shift": m.SlideType.shiftSlideTo,
    "legato": m.SlideType.legatoSlideTo,
    "downwards": m.SlideType.outDownwards,
    "upwards": m.SlideType.outUpwards,
    "above": m.SlideType.intoFromAbove,
    "below": m.SlideType.intoFromBelow,
    "belowlegato": m.SlideType.legatoSlideTo,
    "belowshift": m.SlideType.shiftSlideTo,
}

TRIPLET_FEEL = {"off": m.TripletFeel.none, "8th": m.TripletFeel.eighth,
                "16th": m.TripletFeel.sixteenth}


# Plain (undotted, untupleted) note values, longest first -- a clean dyadic
# basis used to decompose durations GP5 can't store as a single beat.
_BINARY_UNITS = [(Fraction(WHOLE, v), v) for v in (1, 2, 4, 8, 16, 32, 64, 128)]


def _single_duration(target, value, dots) -> "m.Duration | None":
    """A single GP Duration that exactly equals ``target`` ticks, or None.

    Songsterr gives note value + dots + the exact length fraction, so we solve
    the tuplet with exact rationals. This nails even septuplets/odd tuplets,
    which ``Duration.fromTime`` (a float/log heuristic) cannot."""
    for dotted in ([True, False] if dots else [False, True]):
        base = Fraction(WHOLE, value) * (Fraction(3, 2) if dotted else 1)
        tup = m.Tuplet.fromFraction(target / base)  # ratio = times/enters
        if tup.isSupported():
            d = m.Duration(value=value, isDotted=dotted, tuplet=tup)
            if Fraction(d.time) == target:
                return d
    return None


def _durations(beat: dict) -> list:
    """One or more GP Durations summing to the beat's exact length.

    Returns a single duration when GP5 can represent the beat directly; when it
    can't (double dots, odd sums), it splits into plain note values to be tied
    together -- which is how GP5 itself notates such rhythms."""
    num, den = beat["duration"]
    target = Fraction(num, den) * WHOLE
    value = beat.get("type", 4)
    dots = beat.get("dots", 0) or (1 if beat.get("dotted") else 0)

    single = _single_duration(target, value, dots)
    if single is not None:
        return [single]

    # Greedy decomposition over plain note values (works for any dyadic length).
    out, rem = [], target
    for ticks, v in _BINARY_UNITS:
        while rem >= ticks:
            out.append(m.Duration(value=v))
            rem -= ticks
    if rem == 0 and out:
        return out

    try:
        return [m.Duration.fromTime(int(target))]
    except Exception:
        return [m.Duration(value=value, isDotted=bool(dots))]


def _make_bend(bend: dict) -> m.BendEffect:
    pts = []
    for p in bend.get("points", []):
        pts.append(m.BendPoint(
            position=round(p.get("position", 0) * m.BendEffect.maxPosition / 60),
            value=round(p.get("tone", 0) / 25),
        ))
    return m.BendEffect(type=m.BendType.bend,
                        value=round(bend.get("tone", 0) / 25), points=pts)


def _make_tremolo(tb: dict) -> m.BendEffect:
    pts = []
    for p in tb.get("points", []):
        pts.append(m.BendPoint(
            position=round(p.get("position", 0) * m.BendEffect.maxPosition / 60),
            value=round(p.get("tone", 0) / 25),
        ))
    return m.BendEffect(type=m.BendType.dive,
                        value=round(tb.get("tone", 0) / 25), points=pts)


def _harmonic(note: dict):
    h = note.get("harmonic")
    if h == "natural":
        return m.NaturalHarmonic()
    if h == "artificial":
        return m.ArtificialHarmonic()
    if h == "pinch":
        return m.PinchHarmonic()
    if h == "tapped":
        fret = note.get("harmonicFret")
        return m.TappedHarmonic(fret=int(fret) if fret else None)
    return None


def _free_string(desired, used, n, reassign):
    """Pick a free GP string for a note. GP needs one note per string per beat,
    so on a collision we either reassign to the nearest open string (drums) or
    drop the note (fretted instruments, where a clash means it doesn't fit)."""
    if 1 <= desired <= n and desired not in used:
        return desired
    if not reassign:
        return None
    for off in range(1, n + 1):
        for cand in (desired - off, desired + off):
            if 1 <= cand <= n and cand not in used:
                return cand
    return None


def _note(sn: dict, beat: dict, gp_string: int, velocity: int, drum: bool,
          tie: bool = False) -> m.Note:
    note = m.Note(beat=None)
    note.value = int(sn.get("fret", 0))
    note.string = gp_string
    note.velocity = velocity
    if tie:
        # Continuation of a split beat: ring the same note on, no re-articulation.
        note.type = m.NoteType.tie
        return note
    if sn.get("tie"):
        note.type = m.NoteType.tie
    elif sn.get("dead"):
        note.type = m.NoteType.dead
    else:
        note.type = m.NoteType.normal

    e = note.effect
    if sn.get("hp"):
        e.hammer = True
    if sn.get("staccato"):
        e.staccato = True
    if sn.get("ghost"):
        e.ghostNote = True
    if sn.get("vibrato") or sn.get("wideVibrato"):
        e.vibrato = True
    acc = sn.get("accentuated")
    if acc == 1:
        e.accentuatedNote = True
    elif acc == 2:
        e.heavyAccentuatedNote = True
    if "slide" in sn:
        st = SLIDES.get(sn["slide"])
        if st:
            e.slides = [st]
    if "bend" in sn and isinstance(sn["bend"], dict):
        e.bend = _make_bend(sn["bend"])
    harm = _harmonic(sn)
    if harm is not None:
        e.harmonic = harm
    if sn.get("trill"):
        # Songsterr gives no trill fret; approximate a whole-step trill.
        e.trill = m.TrillEffect(fret=note.value + 2, duration=m.Duration(value=16))
    # beat-scoped articulations Songsterr stores once but GP wants per-note
    if beat.get("palmMute"):
        e.palmMute = True
    if beat.get("letRing"):
        e.letRing = True
    return note


def _drum_string_map(part: dict) -> dict:
    """Map Songsterr drum 'string' lines (can be fractional/negative) to GP
    string slots 1..6, high line -> string 1."""
    seen = set()
    for meas in part.get("measures", []):
        for v in meas.get("voices", []):
            for b in v.get("beats", []):
                for n in b.get("notes", []):
                    if "string" in n and not n.get("rest"):
                        seen.add(n["string"])
    ordered = sorted(seen, reverse=True)  # higher value = higher staff line
    return {s: min(i + 1, 6) for i, s in enumerate(ordered)}


def _is_percussion(track_meta: dict, part: dict) -> bool:
    if track_meta.get("instrumentId") == 1024:
        return True
    name = (track_meta.get("instrument") or "").lower()
    return "drum" in name or "percussion" in name


def build_song(meta: dict, parts: list) -> m.Song:
    song = m.Song()
    song.title = _clean(meta.get("title", ""))
    song.artist = _clean(meta.get("artist", ""))
    song.subtitle = ""
    song.tab = "Downloaded from Songsterr"

    # --- tempo (initial + mid-song changes) ------------------------------
    # Songsterr keeps tempo automation per track but it's identical across
    # tracks; each entry is {measure, position, bpm, type}. Positions are at
    # the measure start and bpm is quarter-note referenced (type 4).
    tempo_events = {}  # measure index -> (bpm, visible)
    for part in parts:
        if part and isinstance(part.get("automations"), dict):
            for t in part["automations"].get("tempo", []) or []:
                meas = t.get("measure")
                if meas is not None:
                    tempo_events.setdefault(meas, (t.get("bpm"), t.get("visible", True)))
    init = tempo_events.get(0, (120, True))[0]
    try:
        song.tempo = int(round(float(init)))
    except (TypeError, ValueError):
        song.tempo = 120

    tracks_meta = meta.get("tracks", [])
    n_measures = max((len(p["measures"]) for p in parts if p), default=1)

    # --- measure headers (shared across tracks) --------------------------
    # Use the most-detailed track for signatures/markers/repeats, carrying the
    # last seen time signature forward.
    ref = max((p for p in parts if p), key=lambda p: len(p["measures"]), default=None)
    song.measureHeaders = []
    cur_sig = (4, 4)
    for i in range(n_measures):
        hdr = m.MeasureHeader(number=i + 1)
        sm = ref["measures"][i] if (ref and i < len(ref["measures"])) else {}
        if "signature" in sm:
            cur_sig = tuple(sm["signature"])
        num, den = cur_sig
        hdr.timeSignature = m.TimeSignature(numerator=num,
                                            denominator=m.Duration(value=den))
        if "marker" in sm:
            hdr.marker = m.Marker(title=_clean(sm["marker"].get("text", "Section")) or "Section")
        if sm.get("doubleBarline"):
            hdr.hasDoubleBar = True
        if sm.get("repeatStart"):
            hdr.isRepeatOpen = True
        if "repeat" in sm:
            try:
                hdr.repeatClose = int(sm["repeat"])
            except (TypeError, ValueError):
                pass
        if "alternateEnding" in sm:
            ae = sm["alternateEnding"]
            hdr.repeatAlternative = ae if isinstance(ae, int) else 0
        if "tripletFeel" in sm:
            hdr.tripletFeel = TRIPLET_FEEL.get(sm["tripletFeel"], m.TripletFeel.none)
        song.measureHeaders.append(hdr)

    # --- tracks ----------------------------------------------------------
    song.tracks = []
    for ti, part in enumerate(parts):
        tmeta = tracks_meta[ti] if ti < len(tracks_meta) else {}
        track = m.Track(song, number=ti + 1)
        track.name = _clean(tmeta.get("name") or tmeta.get("instrument")
                            or f"Track {ti + 1}") or f"Track {ti + 1}"
        drum = _is_percussion(tmeta, part or {})
        track.isPercussionTrack = drum

        tuning = (part or {}).get("tuning") or tmeta.get("tuning") or [64, 59, 55, 50, 45, 40]
        if drum:
            track.strings = [m.GuitarString(i + 1, 0) for i in range(6)]
            track.channel.channel = 9
            track.channel.effectChannel = 9
            track.channel.instrument = 0
        else:
            tuning = tuning[:MAX_GP_STRINGS]  # GP5 supports at most 7 strings
            track.strings = [m.GuitarString(i + 1, v) for i, v in enumerate(tuning)]
            inst = tmeta.get("instrumentId", 24)
            track.channel.instrument = inst if isinstance(inst, int) and inst < 128 else 24
        track.fretCount = (part or {}).get("frets", 24)

        drum_map = _drum_string_map(part) if drum else {}
        n_strings = len(track.strings)

        track.measures = []
        for mi, hdr in enumerate(song.measureHeaders):
            measure = m.Measure(track, hdr)
            measure.voices = []
            smeas = part["measures"][mi] if (part and mi < len(part["measures"])) else None
            _fill_measure(measure, smeas, hdr, drum, drum_map, n_strings)
            track.measures.append(measure)
        song.tracks.append(track)

    _apply_tempo_changes(song, tempo_events)
    return song


def _apply_tempo_changes(song, tempo_events):
    """Write mid-song tempo changes as GP mix-table changes on the first beat
    of each measure. The tempo applies globally; we only show the marking on
    the first track so it isn't drawn once per staff."""
    for meas_idx, (bpm, visible) in tempo_events.items():
        if meas_idx == 0:  # the initial tempo lives in the song header
            continue
        try:
            bpm = int(round(float(bpm)))
        except (TypeError, ValueError):
            continue
        for ti, track in enumerate(song.tracks):
            if meas_idx >= len(track.measures):
                continue
            voice = track.measures[meas_idx].voices[0]
            if not voice.beats:
                continue
            beat = voice.beats[0]
            if beat.effect.mixTableChange is None:
                beat.effect.mixTableChange = m.MixTableChange()
            beat.effect.mixTableChange.tempo = m.MixTableItem(value=bpm, duration=0)
            beat.effect.mixTableChange.hideTempo = not (bool(visible) and ti == 0)


def _fill_measure(measure, smeas, hdr, drum, drum_map, n_strings):
    full_rest_ticks = hdr.timeSignature.numerator * hdr.timeSignature.denominator.time
    voices_data = []
    if smeas and not smeas.get("rest"):
        voices_data = smeas.get("voices", [])

    # GP measures carry exactly Measure.maxVoices voices.
    for vi in range(m.Measure.maxVoices):
        voice = m.Voice(measure)
        voice.beats = []
        sv = voices_data[vi] if vi < len(voices_data) else None
        if sv is None or sv.get("rest") or not sv.get("beats"):
            if vi == 0:  # voice 0 always needs at least a full-measure rest
                voice.beats.append(_rest_beat(voice, full_rest_ticks))
            measure.voices.append(voice)
            continue
        _fill_voice(voice, sv, drum, drum_map, n_strings)
        measure.voices.append(voice)


def _rest_beat(voice, ticks):
    beat = m.Beat(voice)
    try:
        beat.duration = m.Duration.fromTime(ticks)
    except Exception:
        beat.duration = m.Duration(value=1)
    beat.status = m.BeatStatus.rest
    return beat


def _fill_voice(voice, sv, drum, drum_map, n_strings):
    pending_grace = None
    for sb in sv.get("beats", []):
        if sb.get("graceNote"):
            pending_grace = sb  # out-of-time: attach to the next real beat
            continue

        durations = _durations(sb)
        is_rest = sb.get("rest") or all(n.get("rest") for n in sb.get("notes", [{}]))

        # Resolve which (string, source-note) pairs this beat plays, once.
        placed = []
        if not is_rest:
            vel = DYNAMICS.get(sb.get("velocity"), m.Velocities.default)
            used = set()
            for sn in sb.get("notes", []):
                if sn.get("rest"):
                    continue
                if drum:
                    desired = drum_map.get(sn.get("string"), 1)
                else:
                    desired = int(sn.get("string", 0)) + 1
                gp_string = _free_string(desired, used, n_strings, reassign=drum)
                if gp_string is None:
                    continue  # out of range / collision -> can't represent in GP5
                used.add(gp_string)
                placed.append((gp_string, sn))
            if not placed:
                is_rest = True  # everything dropped -> rest, not an empty beat

        # A beat may span several GP durations (e.g. a double dot -> two tied
        # notes). The first carries the real notes/effects; the rest are ties.
        for di, dur in enumerate(durations):
            beat = m.Beat(voice)
            beat.duration = dur
            if is_rest:
                beat.status = m.BeatStatus.rest
            else:
                beat.status = m.BeatStatus.normal
                for gp_string, sn in placed:
                    note = _note(sn, sb, gp_string, vel, drum, tie=(di > 0))
                    note.beat = beat
                    beat.notes.append(note)
                if di == 0:
                    _apply_grace(beat, pending_grace)
                    pending_grace = None
            if di == 0:
                _apply_beat_effect(beat, sb)
            voice.beats.append(beat)
        pending_grace = None


def _apply_grace(beat, grace_sb):
    if not grace_sb or not beat.notes:
        return
    gnotes = [n for n in grace_sb.get("notes", []) if not n.get("rest")]
    if not gnotes:
        return
    gn = gnotes[0]
    transition = m.GraceEffectTransition.none
    if gn.get("hp"):
        transition = m.GraceEffectTransition.hammer
    elif "slide" in gn:
        transition = m.GraceEffectTransition.slide
    beat.notes[0].effect.grace = m.GraceEffect(
        fret=int(gn.get("fret", 0)),
        duration=grace_sb.get("type", 32) if grace_sb.get("type", 32) in (16, 32, 64) else 32,
        isDead=bool(gn.get("dead")),
        isOnBeat=(grace_sb.get("graceNote") == "onBeat"),
        transition=transition,
    )


def _apply_beat_effect(beat, sb):
    e = beat.effect
    if sb.get("vibrato") or sb.get("vibratoWithTremoloBar"):
        e.vibrato = True
    if sb.get("tapping"):
        e.slapEffect = m.SlapEffect.tapping
    if isinstance(sb.get("tremoloBar"), dict):
        e.tremoloBar = _make_tremolo(sb["tremoloBar"])
    ps = sb.get("pickStroke")
    if ps == "down":
        e.pickStroke = m.BeatStrokeDirection.down
    elif ps == "up":
        e.pickStroke = m.BeatStrokeDirection.up
    if sb.get("upStroke") or sb.get("brushStroke"):
        e.stroke = m.BeatStroke(direction=m.BeatStrokeDirection.up)
    # text + chord name (chord diagrams skipped; name shown as text)
    texts = []
    if isinstance(sb.get("chord"), dict) and sb["chord"].get("text"):
        texts.append(sb["chord"]["text"])
    if isinstance(sb.get("text"), dict) and sb["text"].get("text"):
        texts.append(sb["text"]["text"])
    if texts:
        beat.text = _clean("  ".join(texts))[:240]
