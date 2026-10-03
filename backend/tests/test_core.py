import unittest
from decimal import Decimal

from app.core.chunking import ChunkingConfig, StructureAwareChunker, render_table, split_text
from app.core.citations import extract_markers, validate_answer
from app.core.context import REFUSAL_MESSAGE, build_context, format_sources, number_evidence
from app.core.fusion import reciprocal_rank_fusion
from app.core.keyword import BM25Index
from app.core.models import Block, Chunk
from app.core.numerics import (NumericError, margin, parse_quantity, percent_change, ratio,
                               total, average, difference)
from app.core.router import route_query


def mk_chunk(cid, text, dept="finance", page=1, section="S", name="Doc.pdf", ctype="text"):
    return Chunk(cid, "d1", name, dept, page, page, section, ctype, text)


class ChunkingTests(unittest.TestCase):
    def setUp(self):
        self.ch = StructureAwareChunker(ChunkingConfig(max_chars=300, min_chars=80))

    def run_chunk(self, blocks):
        return self.ch.chunk(blocks, document_id="d1", document_name="AR.pdf", department="finance")

    def test_heading_forces_boundary_and_section_path(self):
        out = self.run_chunk([
            Block("heading", 1, "Results", level=1),
            Block("paragraph", 1, "Revenue grew strongly this year."),
            Block("heading", 2, "Segments", level=2),
            Block("paragraph", 2, "Segment A led growth."),
        ])
        self.assertEqual([c.section for c in out], ["Results", "Results > Segments"])
        self.assertEqual([c.page_start for c in out], [1, 2])

    def test_page_range_tracked_across_pages(self):
        out = self.run_chunk([Block("paragraph", 3, "A short note."), Block("paragraph", 4, "Another short note.")])
        self.assertEqual((out[0].page_start, out[0].page_end), (3, 4))

    def test_table_isolated_with_context_and_metadata(self):
        rows = (("Metric", "FY2024", "FY2025"), ("Revenue", "125.0", "148.2"))
        out = self.run_chunk([
            Block("heading", 42, "Consolidated Income Statement"),
            Block("paragraph", 42, "Figures in crore."),
            Block("table", 42, rows=rows),
        ])
        table = [c for c in out if c.content_type == "table"][0]
        self.assertIsNotNone(table.table_id)
        self.assertIn("| Revenue | 125.0 | 148.2 |", table.text)
        self.assertIn("Page: 42", table.text)
        self.assertEqual(table.section, "Consolidated Income Statement")
        self.assertEqual(len([c for c in out if c.content_type == "text"]), 1)

    def test_large_table_splits_with_header_repeated(self):
        rows = (("Line", "Defect %"),) + tuple((f"Line-{i}", f"{i}.5") for i in range(40))
        out = self.run_chunk([Block("table", 5, rows=rows)])
        tables = [c for c in out if c.content_type == "table"]
        self.assertGreater(len(tables), 1)
        self.assertEqual(len({c.table_id for c in tables}), 1)
        for c in tables:
            self.assertIn("| Line | Defect % |", c.text)
            self.assertLessEqual(len(c.text), 300 + 120)  # + context header
        body_rows = sum(c.text.count("| Line-") for c in tables)
        self.assertEqual(body_rows, 40)

    def test_oversize_paragraph_split_on_sentences(self):
        text = " ".join(f"Sentence number {i} describes policy detail." for i in range(30))
        pieces = split_text(text, 300, 80)
        self.assertTrue(all(len(p) <= 375 for p in pieces))
        self.assertEqual(" ".join(pieces).split(), text.split())

    def test_unbroken_text_hard_split(self):
        self.assertTrue(all(len(p) <= 100 for p in split_text("x" * 450, 100, 20)))

    def test_chunk_ids_unique_and_deterministic(self):
        blocks = [Block("paragraph", 1, "A. " * 200)]
        a, b = self.run_chunk(blocks), self.run_chunk(blocks)
        self.assertEqual([c.chunk_id for c in a], [c.chunk_id for c in b])
        self.assertEqual(len({c.chunk_id for c in a}), len(a))

    def test_invalid_config(self):
        with self.assertRaises(ValueError):
            ChunkingConfig(max_chars=100, min_chars=100)

    def test_render_table_pads_ragged_rows(self):
        self.assertIn("| a | b |", render_table((("h",), ("a", "b"))))


class FusionTests(unittest.TestCase):
    def test_rrf_rewards_agreement(self):
        out = reciprocal_rank_fusion([["a", "b", "c"], ["b", "c", "d"]], k=60)
        self.assertEqual(out[0][0], "b")
        self.assertAlmostEqual(out[0][1], 1 / 62 + 1 / 61)

    def test_weights_and_validation(self):
        out = reciprocal_rank_fusion([["a"], ["b"]], weights=[1.0, 2.0])
        self.assertEqual(out[0][0], "b")
        with self.assertRaises(ValueError):
            reciprocal_rank_fusion([["a"]], weights=[1, 2])

    def test_duplicates_ignored_and_top_n(self):
        out = reciprocal_rank_fusion([["a", "a", "b"]], top_n=1)
        self.assertEqual(out, [("a", 1 / 61)])

    def test_deterministic_tiebreak(self):
        self.assertEqual([d for d, _ in reciprocal_rank_fusion([["x"], ["y"]])], ["x", "y"])


class KeywordTests(unittest.TestCase):
    def setUp(self):
        self.idx = BM25Index()
        self.idx.add([
            mk_chunk("c1", "FY2025 EBITDA was 35.7 crore", "finance"),
            mk_chunk("c2", "Employee attrition fell to 11.2 percent", "hr"),
            mk_chunk("c3", "Priority-1 incidents require response within 15 minutes", "customer_support"),
        ])

    def test_exact_number_and_kpi_match(self):
        self.assertEqual(self.idx.search("FY2025 EBITDA")[0][0], "c1")
        self.assertEqual(self.idx.search("35.7")[0][0], "c1")
        self.assertEqual(self.idx.search("Priority-1 SLA")[0][0], "c3")

    def test_department_filter_enforced(self):
        self.assertEqual(self.idx.search("attrition", departments={"finance"}), [])
        self.assertEqual(self.idx.search("attrition", departments={"hr"})[0][0], "c2")

    def test_remove_document(self):
        self.idx.remove_document("d1")
        self.assertEqual(len(self.idx), 0)
        self.assertEqual(self.idx.search("EBITDA"), [])

    def test_reindex_same_chunk_id(self):
        self.idx.add([mk_chunk("c1", "completely different text about forklifts")])
        self.assertEqual(self.idx.search("EBITDA"), [])
        self.assertEqual(self.idx.search("forklifts")[0][0], "c1")


class NumericsTests(unittest.TestCase):
    def test_parse_variants(self):
        self.assertEqual(parse_quantity("₹1,25,000.5 crore").value, Decimal("125000.5"))
        self.assertEqual(parse_quantity("(14.2)").value, Decimal("-14.2"))
        self.assertEqual(parse_quantity("18.5%").unit, "%")
        self.assertEqual(parse_quantity("Rs. 5 cr").unit, "crore")
        for bad in ("abc", "(5", "5 widgets", ""):
            with self.assertRaises(NumericError):
                parse_quantity(bad)

    def test_revenue_growth_matches_spec_example(self):
        r = percent_change(parse_quantity("148.2", 2), parse_quantity("125", 1))
        self.assertEqual(r.display(), "18.56%")
        self.assertEqual(r.source_ids, (1, 2))
        self.assertIn("148.2", r.formula)

    def test_ebitda_growth(self):
        r = percent_change(parse_quantity("35.7"), parse_quantity("28.4"))
        self.assertEqual(r.display(), "25.70%")

    def test_unit_normalisation(self):
        r = difference(parse_quantity("1 crore"), parse_quantity("50 lakh"))
        self.assertEqual(r.value, Decimal("0.5"))
        self.assertEqual(r.unit, "crore")  # first operand's scale
        self.assertEqual(total([parse_quantity("1 crore"), parse_quantity("50 lakh")]).value, Decimal("1.5"))

    def test_margin_ratio_average(self):
        self.assertEqual(margin(parse_quantity("35.7"), parse_quantity("148.2")).display(), "24.09%")
        self.assertEqual(ratio(parse_quantity("10"), parse_quantity("4")).value, Decimal("2.5"))
        self.assertEqual(average([parse_quantity("2"), parse_quantity("4")]).value, Decimal("3"))

    def test_errors(self):
        with self.assertRaises(NumericError):
            percent_change(parse_quantity("5"), parse_quantity("0"))
        with self.assertRaises(NumericError):
            difference(parse_quantity("5%"), parse_quantity("5"))
        with self.assertRaises(NumericError):
            percent_change(parse_quantity("5%"), parse_quantity("4%"))
        with self.assertRaises(NumericError):
            total([])

    def test_percentage_point_difference(self):
        self.assertEqual(difference(parse_quantity("12.4%"), parse_quantity("11.2%")).display(), "1.20%")


class CitationTests(unittest.TestCase):
    def setUp(self):
        from app.core.models import Evidence
        self.ev = [
            Evidence(1, mk_chunk("c1", "Revenue FY2024 125.0 FY2025 148.2", page=42, section="Income")),
            Evidence(2, mk_chunk("c2", "EBITDA FY2025 35.7", page=18, section="Analysis")),
        ]

    def test_valid_answer(self):
        calc = [Decimal("18.5600")]
        rep = validate_answer("Revenue rose from 125 to 148.2 [1], about 18.56% growth [1].",
                              self.ev, calc_values=calc, question="revenue in FY2025?")
        self.assertTrue(rep.ok, rep.issues)
        self.assertEqual(rep.cited_sources, [1])

    def test_fabricated_source(self):
        rep = validate_answer("Revenue was 148.2 [7].", self.ev)
        self.assertIn("fabricated_source", [i.code for i in rep.issues])

    def test_uncited_numeric_claim(self):
        rep = validate_answer("Revenue was 148.2 crore. See [1].", self.ev)
        self.assertIn("uncited_numeric_claim", [i.code for i in rep.issues])

    def test_unsupported_number(self):
        rep = validate_answer("Revenue was 999.9 [1].", self.ev)
        self.assertIn("unsupported_number", [i.code for i in rep.issues])

    def test_no_citations(self):
        self.assertIn("no_citations", [i.code for i in validate_answer("Things look good.", self.ev).issues])

    def test_marker_after_period_counts_for_that_sentence(self):
        self.assertTrue(validate_answer("Revenue was 148.2. [1] EBITDA was 35.7. [2]", self.ev).ok)

    def test_refusal_is_valid(self):
        self.assertTrue(validate_answer(REFUSAL_MESSAGE, []).ok)

    def test_marker_parsing_and_marker_digits_not_claims(self):
        self.assertEqual(extract_markers("a [1, 2] b [3]"), [1, 2, 3])
        self.assertTrue(validate_answer("EBITDA is mentioned [2].", self.ev).ok)


class ContextTests(unittest.TestCase):
    def test_numbering_threshold_and_sources(self):
        c1, c2, c3 = mk_chunk("1", "a", page=4), mk_chunk("2", "b"), mk_chunk("3", "c")
        ev = number_evidence([(c1, 0.9), (c2, 0.5), (c3, 0.1)], top_k=5, min_score=0.3)
        self.assertEqual([e.source_id for e in ev], [1, 2])
        ctx = build_context(ev)
        self.assertIn("[1] Doc.pdf | page 4", ctx)
        src = format_sources(ev, [2, 1, 9])
        self.assertEqual([s["source_id"] for s in src], [1, 2])  # 9 dropped: not real

    def test_context_budget(self):
        ev = number_evidence([(mk_chunk(str(i), "x" * 500), 1.0) for i in range(10)])
        self.assertLess(len(build_context(ev, max_chars=1200)), 1600)
        self.assertGreaterEqual(build_context(ev, max_chars=10).count("[1]"), 1)


class RouterTests(unittest.TestCase):
    def test_types(self):
        cases = {
            "What was revenue in FY2025?": ("finance", "table_lookup"),
            "Calculate the percentage increase in EBITDA between FY2024 and FY2025.": ("finance", "comparison"),
            "What is the SLA for Priority-1 incidents?": ("customer_support", "table_lookup"),
            "Why might employee attrition have increased?": ("hr", "semantic"),
            "Which production line had the highest defect rate?": ("manufacturing", "table_lookup"),
        }
        for q, (dept, qtype) in cases.items():
            plan = route_query(q)
            self.assertEqual(plan.departments[0], dept, q)
            self.assertEqual(plan.question_type, qtype, q)

    def test_calculate_is_numerical_when_no_comparison_words(self):
        p = route_query("Calculate the EBITDA margin")
        self.assertEqual(p.question_type, "numerical")
        self.assertTrue(p.needs_numerics)

    def test_multi_document(self):
        p = route_query("Did increased production volume coincide with higher defect rates in Q2?")
        self.assertEqual(p.question_type, "multi_document")
        self.assertTrue(p.needs_multi_retrieval)
        self.assertEqual(p.candidate_k, 30)

    def test_cross_department(self):
        p = route_query("Did employee attrition increase when production output increased?")
        self.assertEqual(p.question_type, "cross_department")
        self.assertEqual(set(p.departments), {"hr", "manufacturing"})

    def test_access_control_and_ui_selection(self):
        p = route_query("Did employee attrition increase when production output increased?",
                        allowed_departments={"hr"})
        self.assertEqual(p.departments, ("hr",))
        self.assertTrue(any("access control" in n for n in p.notes))
        p2 = route_query("What is the leave policy?", selected_department="hr")
        self.assertEqual(p2.departments, ("hr",))
        self.assertEqual(p2.question_type, "policy")

    def test_unknown_query_searches_all_allowed(self):
        p = route_query("tell me something", allowed_departments={"hr", "finance"})
        self.assertEqual(set(p.departments), {"hr", "finance"})


if __name__ == "__main__":
    unittest.main()
