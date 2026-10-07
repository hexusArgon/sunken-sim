import itertools
import math
import unittest
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from farm.protocol import (
    command_body,
    format_control,
    format_job,
    format_stop,
    parse_control,
    parse_int,
    parse_job,
    parse_progress,
    parse_stop,
    resolve_hero_spec,
    status_text,
)
from farm.runner import Board, add_one, note_finished
from farm.space import Piece, Space


def legal_sets(pieces: list[Piece], slots: int, must_amp: bool) -> list[tuple[str, ...]]:
    found: list[tuple[str, ...]] = []

    def walk(index: int, left: int, leg: bool, orb: bool, amp: bool, chosen: list[str]) -> None:
        if left == 0:
            if amp == must_amp:
                found.append(tuple(chosen))
            return
        if index == len(pieces):
            return
        walk(index + 1, left, leg, orb, amp, chosen)
        piece = pieces[index]
        if piece.amp:
            counts = [1] if not amp else []
            next_leg, next_orb, next_amp = leg, orb, True
        elif piece.kind == "leg":
            counts = [1] if not leg else []
            next_leg, next_orb, next_amp = True, orb, amp
        elif piece.kind == "orb":
            counts = [1] if not orb else []
            next_leg, next_orb, next_amp = leg, True, amp
        elif piece.kind == "stack":
            counts = list(range(1, left + 1))
            next_leg, next_orb, next_amp = leg, orb, amp
        else:
            counts = [1]
            next_leg, next_orb, next_amp = leg, orb, amp
        for count in counts:
            walk(index + 1, left - count, next_leg, next_orb, next_amp, chosen + [piece.code] * count)

    walk(0, slots, False, False, False, [])
    return found


class SpaceTest(unittest.TestCase):
    def test_combinations_match_lex_order(self) -> None:
        options = list("abcdef")
        space = Space(
            [Piece("A", "stack")],
            options,
            list("wxyz"),
            slots=1,
            picks_without=2,
            picks_with=2,
            glyph_picks=2,
        )
        got = [space._unrank_comb(index, options, 3) for index in range(math.comb(6, 3))]
        self.assertEqual(got, list(itertools.combinations(options, 3)))

    def test_every_index_is_one_legal_build(self) -> None:
        pieces = [
            Piece("A", "one"),
            Piece("L", "leg"),
            Piece("M", "one", amp=True),
            Piece("O", "orb"),
            Piece("S", "stack"),
        ]
        talents = list("abcdef")
        glyphs = list("wxyz")
        space = Space(
            pieces,
            talents,
            glyphs,
            slots=2,
            picks_without=2,
            picks_with=3,
            glyph_picks=2,
        )
        rows = []
        for must, picks in ((False, 2), (True, 3)):
            for items in legal_sets(pieces, 2, must):
                for talent in itertools.combinations(talents, picks):
                    for glyph in itertools.combinations(glyphs, 2):
                        rows.append((items, talent, glyph))
        self.assertEqual(space.total, len(rows))
        self.assertGreater(space.total, 0)
        decoded = [space.decode(index) for index in range(space.total)]
        self.assertEqual(len(set(decoded)), len(decoded))
        self.assertEqual(set(decoded), set(rows))
        self.assertEqual(len(space.decode(0)[0]), 2)

    def test_out_of_range(self) -> None:
        space = Space([Piece("S", "stack")], ["a", "b", "c"], ["x", "y"], slots=1, picks_without=1, picks_with=1, glyph_picks=1)
        with self.assertRaises(IndexError):
            space.decode(-1)
        with self.assertRaises(IndexError):
            space.decode(space.total)


class ProtocolTest(unittest.TestCase):
    def test_integers_and_ranges(self) -> None:
        self.assertEqual(parse_int("23_000_000"), 23000000)
        self.assertEqual(parse_int("1 000"), 1000)
        with self.assertRaises(ValueError):
            parse_int("23 миллиона")
        self.assertEqual(resolve_hero_spec(None, None), ("priest", "shadow"))
        self.assertEqual(resolve_hero_spec(None, "frost"), ("mage", "frost"))
        with self.assertRaises(ValueError):
            resolve_hero_spec("priest", "frost")

    def test_status_line_is_readable_and_parseable(self) -> None:
        text = status_text(
            worker="kivor",
            hero="priest",
            spec="shadow",
            pool="mixed",
            targets=5,
            start=23_000_000,
            end=1_000_000_000,
            done=1200,
            left=3000,
            best=12.34,
        )
        self.assertEqual(parse_progress(text), (1200, 3000))
        self.assertIn("лучший DPS 12.3", text)
        final = status_text(
            worker="kivor",
            hero="priest",
            spec="shadow",
            pool="mixed",
            targets=5,
            start=0,
            end=10,
            done=4,
            left=7,
            best=1,
            final=True,
            stopped=True,
        )
        self.assertIsNone(parse_progress(final))
        self.assertIn("остановлен", final)

    def test_job_roundtrip(self) -> None:
        job = {
            "id": "ab12",
            "worker": "kivor",
            "start": 23_000_000,
            "end": 10**15,
            "hero": "priest",
            "spec": "shadow",
            "pool": "mixed",
            "targets": 5,
            "channel": "1",
            "status": "2",
        }
        self.assertEqual(parse_job(format_job(job))["end"], 10**15)
        self.assertEqual(parse_stop(format_stop("ab12")), "ab12")
        control = parse_control(format_control("kivor", [{"channel": "1", "message": "2", "worker": "kivor"}]))
        self.assertEqual(control["leader"], "kivor")
        self.assertEqual(len(control["watch"]), 1)

    def test_command_fits_discord_limits(self) -> None:
        body = command_body("kivor")
        self.assertEqual(body["name"], "kivor")
        self.assertLessEqual(len(body["options"]), 25)

        def walk(node: dict) -> None:
            if "description" in node:
                self.assertGreaterEqual(len(node["description"]), 1)
                self.assertLessEqual(len(node["description"]), 100)
            for option in node.get("options") or []:
                walk(option)
            for choice in node.get("choices") or []:
                self.assertLessEqual(len(choice["name"]), 100)

        walk(body)


class BoardTest(unittest.TestCase):
    def test_top_ten_and_watermark(self) -> None:
        board = Board()
        for index in range(15):
            board.add({"dps": float(index), "chunk": index, "items": []})
        rows = board.rows()
        self.assertEqual(len(rows), 10)
        self.assertEqual(rows[0]["chunk"], 14)
        self.assertEqual(rows[-1]["chunk"], 5)
        ahead: set[int] = set()
        done = note_finished(0, ahead, 1)
        self.assertEqual((done, ahead), (0, {1}))
        done = note_finished(done, ahead, 0)
        self.assertEqual((done, ahead), (2, set()))
        self.assertEqual(note_finished(done, ahead, 1), 2)

    def test_process_pool_starts(self) -> None:
        context = get_context("spawn")
        with ProcessPoolExecutor(max_workers=2, mp_context=context) as pool:
            self.assertEqual(list(pool.map(add_one, [1, 2, 3])), [2, 3, 4])


class HistoryFlagTest(unittest.TestCase):
    def test_mage_can_skip_history(self) -> None:
        import inspect

        from sunken_sim.mage import simulate

        parameter = inspect.signature(simulate).parameters["use_history"]
        self.assertEqual(parameter.default, True)
        self.assertEqual(parameter.kind, inspect.Parameter.KEYWORD_ONLY)


if __name__ == "__main__":
    unittest.main()
