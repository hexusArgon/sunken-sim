import itertools
import math
import unittest
from concurrent.futures import ProcessPoolExecutor
from multiprocessing import get_context

from farm.protocol import (
    chunk_range,
    command_body,
    format_control,
    format_job,
    format_stop,
    parse_control,
    parse_int,
    parse_job,
    parse_progress,
    mention,
    parse_stop,
    resolve_hero_spec,
    resolve_top,
    spec_suggestions,
    status_text,
)
from farm.paths import atomic_write
from farm.runner import (
    Board,
    Boards,
    CategoryBars,
    ItemBar,
    _merge_checkpoint,
    add_one,
    build_group,
    note_finished,
    note_span,
)
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
        for must in (False, True):
            for items in legal_sets(pieces, 2, must):
                rows.append((items, (), ()))
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
        self.assertEqual(resolve_hero_spec("mage", "frost"), ("mage", "frost"))
        self.assertEqual(resolve_hero_spec("death_knight", "frost"), ("death_knight", "frost"))
        self.assertEqual(resolve_hero_spec(None, "death_knight/frost"), ("death_knight", "frost"))
        self.assertEqual(resolve_hero_spec(None, "headhunter"), ("berserker", "headhunter"))
        self.assertEqual(resolve_hero_spec("hunter", "Beast Mastery"), ("hunter", "beast_mastery"))
        with self.assertRaises(ValueError):
            resolve_hero_spec(None, "frost")
        with self.assertRaises(ValueError):
            resolve_hero_spec(None, "holy")
        with self.assertRaises(ValueError):
            resolve_hero_spec("priest", "frost")
        self.assertEqual(resolve_top(None), None)
        self.assertEqual(resolve_top(80), 80)
        with self.assertRaises(ValueError):
            resolve_top(85)
        rows = spec_suggestions("warrior", "")
        self.assertEqual([value for _name, value in rows], ["protection", "arms", "fury"])
        self.assertTrue(all("/" in value for _name, value in spec_suggestions(None, "guard")))
        self.assertLessEqual(len(spec_suggestions(None, "")), 25)

    def test_chunk_range_defaults_to_all(self) -> None:
        self.assertEqual(chunk_range(1000), (0, 999))
        self.assertEqual(chunk_range(1000, None, None, 10), (0, 99))
        self.assertEqual(chunk_range(1000, "5", "9"), (5, 9))
        with self.assertRaises(ValueError):
            chunk_range(1000, "5", None)
        with self.assertRaises(ValueError):
            chunk_range(1000, None, "9")
        with self.assertRaises(ValueError):
            chunk_range(1000, "0", "1000")
        with self.assertRaises(ValueError):
            chunk_range(0)

    def test_specs_match_modules(self) -> None:
        import importlib

        from farm.protocol import GPU_ONLY, SPECS

        for hero, specs in SPECS.items():
            if hero == "priest":
                continue
            # GPU-only classes: the specs live in the kernel module (farm/hybrid/<hero>_cl.py)
            module = importlib.import_module(f"farm.hybrid.{hero}_cl" if hero in GPU_ONLY else f"sunken_sim.{hero}")
            self.assertEqual(tuple(module.SPECS), specs, hero)

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
        paced = status_text(
            worker="kivor",
            hero="paladin",
            spec="retribution",
            pool="mixed",
            targets=5,
            start=0,
            end=10,
            done=4,
            left=7,
            best=1,
            elapsed=125,
            remaining=200,
            rate=40,
            rate_max=80,
            rate_min=12,
            cpu=63,
        )
        self.assertEqual(parse_progress(paced), (4, 7))
        self.assertIn("прошло 2:05 · осталось 3:20", paced)
        self.assertIn("бои/с 40 · макс 80 · мин 12", paced)
        self.assertIn("ЦП 63%", paced)
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
        self.assertTrue(mention("готово").startswith("<@229350465668775936> "))
        self.assertLessEqual(len(mention("x" * 3000)), 2000)

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
        from farm.identity import _WORD

        self.assertTrue(_WORD.fullmatch("eseid-main"))
        self.assertTrue(_WORD.fullmatch("kivor"))
        self.assertIsNone(_WORD.fullmatch("Eseid"))
        self.assertLessEqual(len(body["options"]), 25)
        names = [option["name"] for option in body["options"]]
        self.assertNotIn("preset", names)
        top = next(option for option in body["options"] if option["name"] == "top")
        self.assertEqual([choice["value"] for choice in top["choices"]], list(range(10, 251, 10)))
        for option in body["options"]:
            self.assertLessEqual(len(option.get("choices") or []), 25)
        job = {"id": "a", "worker": "w", "start": 0, "end": 1, "hero": "monk", "spec": "windwalker",
               "pool": "mixed", "targets": 5, "channel": "1", "status": "2", "top": 80}
        self.assertEqual(parse_job(format_job(job))["top"], 80)

        def walk(node: dict) -> None:
            if "description" in node:
                self.assertGreaterEqual(len(node["description"]), 1)
                self.assertLessEqual(len(node["description"]), 100)
            for option in node.get("options") or []:
                walk(option)
            for choice in node.get("choices") or []:
                self.assertLessEqual(len(choice["name"]), 100)

        walk(body)


class CheckpointTest(unittest.TestCase):
    def test_later_watermark_is_kept(self) -> None:
        early = {
            "start": 0, "end": 10, "hero": "paladin", "spec": "retribution",
            "pool": "mixed", "targets": 5, "preset": "",
            "done_up_to": 19, "ahead": [], "errors": 0, "item_bar": [10.0],
            "top": [{"dps": 10.0, "chunk": 1}],
            "top_shop_random": [], "top_shop": [], "top_random": [],
        }
        late = dict(early)
        late["done_up_to"] = 55
        late["item_bar"] = [30.0]
        late["top"] = [{"dps": 40.0, "chunk": 2}]
        merged = _merge_checkpoint(early, late)
        self.assertEqual(merged["done_up_to"], 55)
        self.assertEqual(merged["top"][0]["chunk"], 2)
        self.assertEqual(merged["item_bar"]["overall"][0], 30.0)
        self.assertEqual(merged["item_bar"]["shop"], [])
        blank = dict(early)
        blank["preset"] = None
        self.assertEqual(_merge_checkpoint(blank, late)["done_up_to"], 55)

    def test_atomic_write_replaces_the_file(self) -> None:
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "checkpoint.json"
            atomic_write(path, "one")
            atomic_write(path, "two")
            self.assertEqual(path.read_text(encoding="utf-8"), "two")
            self.assertEqual(list(Path(folder).glob("*.tmp")), [])


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
        spans: list[tuple[int, int]] = []
        done = note_span(0, spans, 20, 30)
        self.assertEqual((done, spans), (0, [(20, 30)]))
        done = note_span(done, spans, 0, 20)
        self.assertEqual((done, spans), (30, []))

    def test_three_source_tops(self) -> None:
        self.assertEqual(build_group(["shop", "drop"]), "shop_random")
        self.assertEqual(build_group(["shop", "legendary"]), "shop")
        self.assertEqual(build_group(["drop", "drop"]), "drop")
        self.assertIsNone(build_group(["legendary"]))
        boards = Boards()
        for index, group in enumerate(("shop_random", "shop", "drop", "shop")):
            boards.add({"dps": float(index + 1), "chunk": index, "group": group, "items": []})
        self.assertEqual([row["chunk"] for row in boards.by_group["shop"].rows()], [3, 1])
        self.assertEqual(boards.by_group["shop_random"].rows()[0]["chunk"], 0)
        self.assertEqual(boards.by_group["drop"].rows()[0]["chunk"], 2)
        self.assertEqual(boards.ranked(boards.overall)[0]["place"], 1)
        self.assertEqual(boards.ranked(boards.overall)[0]["chunk"], 3)

    def test_item_bar_keeps_ten_bare_scores(self) -> None:
        bar = ItemBar()
        for value in range(1, 11):
            self.assertTrue(bar.claim(float(value)))
        self.assertEqual(bar.scores[0], 10.0)
        self.assertEqual(bar.scores[-1], 1.0)
        self.assertFalse(bar.claim(1.0))
        self.assertTrue(bar.claim(1.5))
        self.assertEqual(bar.scores[-1], 1.5)
        self.assertNotIn(1.0, bar.scores)

    def test_shop_bar_ignores_the_overall_floor(self) -> None:
        bars = CategoryBars({"overall": [100.0] * 10, "shop": [1.0] * 9, "drop": []})
        self.assertTrue(bars.claim(2.0, "shop"))
        self.assertEqual(bars.bars["overall"].scores[-1], 100.0)
        self.assertEqual(bars.bars["shop"].scores[-1], 1.0)
        self.assertFalse(bars.claim(2.0, "shop_random"))
        self.assertTrue(bars.claim(2.0, "drop"))
        self.assertEqual(bars.bars["drop"].scores, [2.0])

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
