"""Native expression boxes copy semantic code, never their surrounding explanation."""

import os
import tempfile
import unittest
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPoint, QRect
from qgis.PyQt.QtGui import QColor, QPalette
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtWidgets import QApplication, QVBoxLayout, QWidget
from qgis.core import QgsApplication

from qgis_ai_copilot import widgets
from qgis_ai_copilot.styles import build_stylesheet
from tests.qgis_runtime import configure_prefix


EXPRESSION = """"class_2018" IN (
  'Complex and mixed cultivation patterns',
  'Arable land (annual crops)',
  'Green urban areas',
  'Forests',
  'Pastures',
  'Sports and leisure facilities',
  'Herbaceous vegetation associations (natural grassland, moors...)',
  'Wetlands'
)"""
ANSWER = (
    "### 按表达式选择绿地\n\n在“按表达式选择”中输入：\n\n```qgis\n"
    + EXPRESSION
    + "\n```\n\n点击“选择要素”。[QGIS 文档](https://docs.qgis.org/)"
)


class CodeBlockTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        os.environ["QGIS_CUSTOM_CONFIG_PATH"] = cls.temp.name
        configure_prefix()
        cls.app = QgsApplication([], True)
        cls.app.initQgis()

    @classmethod
    def tearDownClass(cls):
        cls.app.exitQgis()
        cls.temp.cleanup()

    def setUp(self):
        self.host = QWidget()
        self.layout = QVBoxLayout(self.host)
        self.host.resize(420, 720)
        self.host.setStyleSheet(build_stylesheet(self.host.palette()))
        self.message = {
            "role": "assistant",
            "content": ANSWER,
            "status": "complete",
            "request": {"model": "fixture", "thinking": "Auto"},
        }
        self.card = widgets.MessageCard(self.message, self.host)
        self.layout.addWidget(self.card)
        self.layout.addStretch()
        self.host.show()
        QTest.qWait(30)

    def tearDown(self):
        self.host.close()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def boxes(self):
        self.assertTrue(
            hasattr(widgets, "CodeBlock"), "Expressions need a dedicated copyable code box"
        )
        return self.card.body.findChildren(widgets.CodeBlock)

    def render(self, content):
        self.card.finalize(content, "complete")
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        QTest.qWait(20)

    def test_existing_qgis_expression_has_one_compact_box_and_local_copy(self):
        boxes = self.boxes()
        self.assertEqual(len(boxes), 1)
        box = boxes[0]
        self.assertEqual(box.label.text(), "QGIS expression")
        self.assertTrue(box.editor.isReadOnly())
        self.assertEqual(box.editor.toPlainText(), EXPRESSION)
        box.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), EXPRESSION)
        self.assertNotIn("```", QApplication.clipboard().text())
        self.assertFalse(box.copy_button.icon().isNull())
        self.assertLessEqual(box.copy_button.width(), 24)
        self.assertLessEqual(box.editor.height(), 240)
        self.assertEqual(self.message["content"], ANSWER)
        self.card.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), ANSWER)

    def test_prose_links_and_code_are_not_duplicated_in_visible_browsers(self):
        self.boxes()
        browsers = [
            b for b in self.card.body.findChildren(widgets.SafeTextBrowser) if b.isVisible()
        ]
        visible = "\n".join(b.toPlainText() for b in browsers)
        self.assertIn("点击", visible)
        self.assertNotIn("Wetlands", visible)
        self.assertTrue(any("https://docs.qgis.org/" in b.document().toHtml() for b in browsers))
        self.assertIn("Wetlands", self.card.body.toPlainText())

    def test_inline_code_remains_inline(self):
        self.render('Use `"count" > 3` in your expression.')
        self.assertEqual(self.boxes(), [])

    def test_code_uses_a_true_monospace_font(self):
        metrics = self.boxes()[0].editor.fontMetrics()
        self.assertLessEqual(
            abs(metrics.horizontalAdvance("iiii") - metrics.horizontalAdvance("WWWW")), 2
        )

    def test_adjacent_same_language_fences_are_separate_boxes(self):
        self.render('```qgis\n"a" > 1\n```\n```qgis\n"b" > 2\n```')
        self.assertEqual([box.code for box in self.boxes()], ['"a" > 1', '"b" > 2'])

    def test_multiple_fenced_and_indented_blocks_have_independent_copy(self):
        self.render(
            '```qgis\n"count" > 3\n```\n\nA second example:\n\n```python\nprint("hello")\n```\n\nIndented expression:\n\n    "area" / 10000\n'
        )
        boxes = self.boxes()
        self.assertEqual(len(boxes), 3)
        for box, expected in zip(boxes, ['"count" > 3', 'print("hello")', '"area" / 10000']):
            box.copy_button.click()
            self.assertEqual(QApplication.clipboard().text(), expected)

    def test_code_inside_folded_details_keeps_its_copy_control(self):
        self.render(
            "Visible answer.\n\n### Raw log\n\n```text\nline one\nline two\n```\n\n### Next step\n\nContinue here."
        )
        box = self.boxes()[0]
        self.assertFalse(box.isVisible())
        self.card.body.disclosures[0].toggle.click()
        QTest.qWait(20)
        self.assertTrue(box.isVisible())
        box.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), "line one\nline two")

    def test_quotes_tabs_blank_lines_and_literal_html_are_preserved(self):
        code = "\"naïve 字段\" = 'A & B'\n\n\t-- <b>literal</b>\n  'x'  "
        self.render("```qgis\n" + code + "\n```")
        self.boxes()[0].copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), code)

    def test_streaming_does_not_create_partial_copy_boxes(self):
        self.card.message["content"] = ""
        self.card.message["status"] = "streaming"
        self.card.body.set_content("", markdown=False)
        self.card.append_delta(ANSWER[:90])
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.assertEqual(self.boxes(), [])
        self.card.finalize(ANSWER, "complete")
        self.assertEqual(len(self.boxes()), 1)

    def test_long_expression_scrolls_locally_and_copy_stays_complete(self):
        code = (
            '"name" IN ('
            + ",".join(repr("long value " + str(i)) for i in range(100))
            + ")\n"
            + "\n".join("-- row " + str(i) for i in range(35))
        )
        self.render("```qgis\n" + code + "\n```")
        box = self.boxes()[0]
        for width in (360, 420, 460):
            self.host.resize(width, 720)
            QTest.qWait(30)
            self.assertLessEqual(box.editor.height(), 240)
            self.assertTrue(
                box.rect().contains(
                    QRect(box.copy_button.mapTo(box, QPoint()), box.copy_button.size())
                )
            )
            box.copy_button.click()
            self.assertEqual(QApplication.clipboard().text(), code)

    def test_preview_fits_both_palettes_and_narrow_widths(self):
        self.boxes()
        artifacts = Path(__file__).resolve().parents[1] / "artifacts"
        artifacts.mkdir(exist_ok=True)
        for dark in (False, True):
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor("#24282e" if dark else "#ffffff"))
            palette.setColor(QPalette.Base, QColor("#20242a" if dark else "#ffffff"))
            palette.setColor(QPalette.WindowText, QColor("#e5eaf1" if dark else "#364252"))
            self.host.setPalette(palette)
            self.host.setStyleSheet(build_stylesheet(palette))
            for width in (360, 420, 460):
                self.host.resize(width, 720)
                QTest.qWait(40)
                self.assertLessEqual(self.host.width(), width)
                self.assertTrue(
                    self.card.grab().save(
                        str(artifacts / f"code-box-{width}-{'dark' if dark else 'light'}.png")
                    )
                )


if __name__ == "__main__":
    unittest.main()
