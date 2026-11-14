from scripts.wiki.complexity_report import FileComplexity, analyze_file, render_markdown

_SIMPLE_CODE = """
def add(a, b):
    return a + b
"""

_BRANCHY_CODE = """
def branchy(x):
    if x == 1:
        return 1
    elif x == 2:
        return 2
    elif x == 3:
        return 3
    elif x == 4:
        return 4
    elif x == 5:
        return 5
    else:
        return 0
"""

_EMPTY_MODULE_CODE = '''
"""A module with no functions or classes at all."""
'''


def test_analyze_file_reports_complexity_one_for_a_single_branchless_function() -> None:
    result = analyze_file(_SIMPLE_CODE, "fixtures/simple.py")

    assert result.path == "fixtures/simple.py"
    assert result.max_complexity == 1
    assert result.worst_block_name == "add"
    assert 0.0 < result.maintainability_index <= 100.0


def test_analyze_file_reports_higher_complexity_for_a_branchier_function() -> None:
    simple = analyze_file(_SIMPLE_CODE, "a.py")
    branchy = analyze_file(_BRANCHY_CODE, "b.py")

    assert branchy.max_complexity > simple.max_complexity
    assert branchy.worst_block_name == "branchy"


def test_analyze_file_handles_a_module_with_no_functions_or_classes() -> None:
    result = analyze_file(_EMPTY_MODULE_CODE, "empty.py")

    assert result.max_complexity == 0
    assert result.worst_block_name == "-"


def test_render_markdown_includes_every_file_and_a_mermaid_pie_chart() -> None:
    results = [
        FileComplexity(path="a.py", max_complexity=1, worst_block_name="add", maintainability_index=95.0),
        FileComplexity(path="b.py", max_complexity=11, worst_block_name="branchy", maintainability_index=60.0),
    ]

    markdown = render_markdown(results)

    assert "a.py" in markdown
    assert "b.py" in markdown
    assert markdown.count("```mermaid") == 1
    assert "pie" in markdown
    # complexity 1 -> rank A, complexity 11 -> rank C: both slices must appear
    assert '"A" : 1' in markdown
    assert '"C" : 1' in markdown


def test_render_markdown_table_rows_stay_indented_inside_the_figure_admonition() -> None:
    """
    Every line of the table (not just the header/separator) must carry the
    same 4-space indent as the rest of the `!!! figure` admonition body --
    an unindented row falls outside the admonition block under MkDocs'
    markdown parser and collapses into a single run-on paragraph instead of
    a rendered table. This is a real regression caught on the live site,
    not a hypothetical.
    """
    results = [FileComplexity(path="a.py", max_complexity=1, worst_block_name="add", maintainability_index=95.0)]

    markdown = render_markdown(results)

    table_row_line = next(line for line in markdown.splitlines() if "a.py" in line)
    assert table_row_line.startswith("    |")


def test_render_markdown_with_no_files_still_produces_valid_output() -> None:
    markdown = render_markdown([])

    assert "```mermaid" not in markdown or "pie" in markdown
