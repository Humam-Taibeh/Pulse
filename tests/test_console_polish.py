"""
Console readability polish: severity colour and sticky auto-scroll.

THE COMPLAINT THIS ANSWERS
    LiveConsole rendered every line the backend sent in one flat colour.
    Write-Success / Write-ErrorX / Write-Warn colour their PowerShell host
    output, but Write-Host -ForegroundColor never survives the pipe Popen
    reads from (see helpers.PowerShellTask._apply) — so a 500-line
    winget/DISM transcript put a real failure in the exact same colour as
    routine progress noise, and the console had no way to answer "did
    anything go wrong in here?" without reading every word.

    Auto-scroll had a second, unrelated complaint: it snapped to the
    newest line on EVERY append, so scrolling up mid-task to re-read an
    error was undone by the very next line of output.
"""
from __future__ import annotations

from PySide6.QtGui import QColor, QTextCursor

from frontend import theme as TH
from frontend.widgets import LiveConsole


def _line_color(console: LiveConsole, block_number: int) -> QColor:
    block = console.document().findBlockByNumber(block_number)
    cursor = QTextCursor(block)
    cursor.movePosition(QTextCursor.MoveOperation.EndOfBlock,
                         QTextCursor.MoveMode.KeepAnchor)
    return cursor.charFormat().foreground().color()


# ============================================================
#  SEVERITY COLOUR
# ============================================================
class TestSeverityColour:
    def test_a_success_verdict_line_is_tinted_ok(self, qapp):
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line("SUCCESS|Firefox updated successfully.")
        assert _line_color(console, 0).name() == QColor(t["ok"]).name()

    def test_an_error_verdict_line_is_tinted_err(self, qapp):
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line("ERROR|Something failed badly.")
        assert _line_color(console, 0).name() == QColor(t["err"]).name()

    def test_the_write_success_checkmark_is_tinted_ok(self, qapp):
        """Backend line shape from Write-Success: '   <check>  text'."""
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line("   ✓  Firefox updated to 145.0.")
        assert _line_color(console, 0).name() == QColor(t["ok"]).name()

    def test_the_write_errorx_cross_is_tinted_err(self, qapp):
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line("   ✗  Could not stop the service.")
        assert _line_color(console, 0).name() == QColor(t["err"]).name()

    def test_a_write_warn_line_is_tinted_warn(self, qapp):
        """Backend line shape from Write-Warn: '   !  text'."""
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line("   !  system binary 'foo' not found.")
        assert _line_color(console, 0).name() == QColor(t["warn"]).name()

    def test_a_dry_run_success_reads_as_warn_not_ok(self, qapp):
        """A simulated run must not look identical to a real one in the one
        place meant to show it wasn't — [DRY-RUN]/[WHATIF] wins over the
        SUCCESS| the same line also carries."""
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line(
            "SUCCESS|[DRY-RUN] OneDrive removal simulated "
            "(no changes were made)")
        assert _line_color(console, 0).name() == QColor(t["warn"]).name()

    def test_a_whatif_preview_line_is_tinted_warn(self, qapp):
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line("   [WHATIF] Would reinstall Microsoft Edge.")
        assert _line_color(console, 0).name() == QColor(t["warn"]).name()

    def test_an_ordinary_line_keeps_the_default_console_colour(self, qapp):
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line("Scanning installed packages...")
        assert _line_color(console, 0).name() == QColor(t["text_soft"]).name()

    def test_classification_still_works_with_timestamps_on(self, qapp):
        """The HH:MM:SS gutter must not hide the marker from the classifier."""
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=True)
        console.append_line("ERROR|Something failed badly.")
        assert _line_color(console, 0).name() == QColor(t["err"]).name()

    def test_a_carriage_return_rewrite_is_classified_too(self, qapp):
        """put_line(..., replace_last=True) rewrites the newest block in
        place (winget/SFC/DISM progress) — the same colour pass must apply
        there, not only to a freshly appended block."""
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line("  12%")
        console.put_line("ERROR|Download failed at 55%.", True)
        assert console.blockCount() == 1
        assert _line_color(console, 0).name() == QColor(t["err"]).name()

    def test_copy_and_export_still_see_plain_text(self, qapp):
        """Colouring is a QTextCharFormat overlay — toPlainText() (what
        copy_all/export_to read) must still return the literal text with no
        formatting markup mixed in."""
        t = TH.tokens("dark")
        console = LiveConsole(t, timestamps=False)
        console.append_line("SUCCESS|Firefox updated successfully.")
        assert console.toPlainText() == "SUCCESS|Firefox updated successfully."


# ============================================================
#  STICKY AUTO-SCROLL
# ============================================================
class TestStickyAutoScroll:
    def _fill(self, console: LiveConsole, n: int = 40):
        console.resize(320, 90)
        for i in range(n):
            console.append_line(f"line {i:04d}")

    def test_scrolling_up_survives_the_next_line(self, qapp):
        console = LiveConsole(TH.tokens("dark"), timestamps=False)
        self._fill(console)
        bar = console.verticalScrollBar()
        assert bar.maximum() > 0, "the test console never overflowed its viewport"
        bar.setValue(0)  # the user scrolls all the way up to read something
        console.append_line("line 0040")
        assert bar.value() == 0, (
            "a new output line yanked a scrolled-up reader back to the tail")

    def test_a_reader_at_the_tail_keeps_following_live_output(self, qapp):
        console = LiveConsole(TH.tokens("dark"), timestamps=False)
        self._fill(console)
        bar = console.verticalScrollBar()
        assert bar.value() == bar.maximum()
        console.append_line("line 0040")
        assert bar.value() == bar.maximum(), (
            "the console stopped following output for a reader at the tail")

    def test_a_carriage_return_rewrite_respects_the_same_rule(self, qapp):
        console = LiveConsole(TH.tokens("dark"), timestamps=False)
        self._fill(console)
        bar = console.verticalScrollBar()
        bar.setValue(0)
        console.put_line("  99%", True)
        assert bar.value() == 0, (
            "a carriage-return progress rewrite yanked a scrolled-up reader "
            "back to the tail")
