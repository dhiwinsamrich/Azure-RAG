from __future__ import annotations

from rag_core.schemas import Block, BlockKind
from rag_core.tables import looks_like_continuation, reconcile, to_markdown

from .conftest import para, table


def test_merges_table_split_across_page_break_with_repeated_header():
    blocks = [
        table(["Segment", "FY23"], [["Productivity", "69,274"]], 4, 4),
        table(["Segment", "FY23"], [["Segment", "FY23"], ["Cloud", "87,907"]], 5, 5),
    ]
    out = reconcile(blocks)

    assert len(out) == 1
    merged = out[0]
    assert merged.rows == [["Productivity", "69,274"], ["Cloud", "87,907"]]
    assert (merged.page_start, merged.page_end) == (4, 5)


def test_merges_continuation_with_no_header():
    blocks = [
        table(["Segment", "FY23"], [["Productivity", "69,274"]], 4, 4),
        Block(kind=BlockKind.TABLE, rows=[["Cloud", "87,907"]], page_start=5, page_end=5),
    ]
    out = reconcile(blocks)
    assert len(out) == 1
    assert out[0].rows == [["Productivity", "69,274"], ["Cloud", "87,907"]]


def test_does_not_merge_when_column_count_differs():
    blocks = [
        table(["Segment", "FY23"], [["Productivity", "69,274"]], 4, 4),
        table(["Segment", "FY23", "FY22"], [["Cloud", "87,907", "74,965"]], 5, 5),
    ]
    assert len(reconcile(blocks)) == 2


def test_does_not_merge_across_a_gap_of_real_prose():
    blocks = [
        table(["Segment", "FY23"], [["Productivity", "69,274"]], 4, 4),
        para("The following table presents unrelated data.", 5),
        table(["Segment", "FY23"], [["Cloud", "87,907"]], 5, 5),
    ]
    assert sum(b.kind is BlockKind.TABLE for b in reconcile(blocks)) == 2


def test_does_not_merge_distant_pages():
    a = table(["Segment", "FY23"], [["Productivity", "69,274"]], 4, 4)
    b = table(["Segment", "FY23"], [["Cloud", "87,907"]], 9, 9)
    assert not looks_like_continuation(a, b)


def test_blank_block_between_halves_does_not_block_merge():
    blocks = [
        table(["Segment", "FY23"], [["Productivity", "69,274"]], 4, 4),
        para("   ", 5),
        table(["Segment", "FY23"], [["Cloud", "87,907"]], 5, 5),
    ]
    out = reconcile(blocks)
    assert sum(b.kind is BlockKind.TABLE for b in out) == 1


def test_markdown_rendering_is_a_pipe_table():
    md = to_markdown(table(["Segment", "FY23"], [["Cloud", "87,907"]]))
    lines = md.splitlines()
    assert lines[0] == "| Segment | FY23 |"
    assert set(lines[1]) <= set("| -")
    assert lines[2] == "| Cloud | 87,907 |"


def test_markdown_pads_short_rows():
    md = to_markdown(table(["A", "B", "C"], [["1"]]))
    assert md.splitlines()[-1] == "| 1 |  |  |"
