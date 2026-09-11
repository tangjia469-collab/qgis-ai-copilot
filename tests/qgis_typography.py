"""Native typography and disclosure regression tests for the approved chat design."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from qgis.PyQt.QtCore import QCoreApplication, QEvent, QPoint, QRect, Qt, QUrl
from qgis.PyQt.QtGui import QColor, QFont, QPalette, QTextDocument
from qgis.PyQt.QtWidgets import QApplication, QMessageBox, QVBoxLayout, QWidget
from qgis.PyQt.QtTest import QTest
from qgis.core import QgsApplication

from qgis_ai_copilot.plugin import QgisAiCopilotPlugin
from qgis_ai_copilot.styles import build_stylesheet
from qgis_ai_copilot.widgets import MessageCard, SafeTextBrowser
from tests.qgis_runtime import configure_prefix
from tests.qgis_smoke import FakeIface


ANSWER = """## 运行成功，设置基本正确

日志显示算法已完成，当前设置与 100 m 缓冲区内食品店数量统计一致。

### 结果摘要

| 项目 | 结果 |
| --- | --- |
| 统计字段 | `NUMPOINTS` |
| 处理耗时 | 0.30 秒 |

### 图层与参数

- 多边形图层：`CPH_quarter_buffered.shp`
- 点图层：`shop_points.shp`
- 权重字段：空白
- 分类字段：空白

### 性能提醒

点图层缺少空间索引，处理可能较慢。这条警告不代表计算失败。

### 原始警告

> No spatial index exists for points layer, performance will be severely degraded

### 下一步

建议创建空间索引，再检查 NUMPOINTS 字段。[QGIS 文档](https://docs.qgis.org/)
"""


class TypographyTests(unittest.TestCase):
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
        self.host.resize(420, 800)
        self.host.setStyleSheet(build_stylesheet(self.host.palette()))
        self.message = {
            "id": "answer",
            "role": "assistant",
            "content": ANSWER,
            "status": "complete",
            "request": {"model": "gpt-6-astra", "thinking": "Max"},
        }
        self.card = MessageCard(self.message, self.host)
        self.layout.addWidget(self.card)
        self.host.show()
        self.app.processEvents()

    def tearDown(self):
        self.host.close()
        self.host.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.DeferredDelete)
        self.app.processEvents()

    def test_document_fonts_and_heading_scale_are_explicit(self):
        browser = SafeTextBrowser()
        browser.set_content(
            "# 一级标题\n\n普通中文 and English `FIELD_NAME`\n\n## 二级标题\n\n```python\nprint(123)\n```"
        )
        font = browser.document().defaultFont()
        self.assertEqual(font.pixelSize(), 14)
        self.assertEqual(font.styleHint(), QFont.SansSerif)
        block = browser.document().begin()
        while block.isValid():
            fragment = block.begin()
            while not fragment.atEnd():
                item = fragment.fragment()
                if item.isValid():
                    resolved = item.charFormat().font().resolve(font)
                    self.assertLessEqual(resolved.pixelSize(), 15)
                    self.assertGreaterEqual(resolved.pixelSize(), 13)
                fragment += 1
            block = block.next()
        browser.deleteLater()

    def test_named_technical_sections_fold_but_warning_stays_visible(self):
        body = self.card.body
        self.assertTrue(hasattr(body, "disclosures"), "Technical sections need real disclosures")
        self.assertEqual([d.title for d in body.disclosures], ["图层与参数", "原始警告"])
        for disclosure in body.disclosures:
            self.assertFalse(disclosure.toggle.isChecked())
            self.assertFalse(disclosure.browser.isVisible())
        visible = "\n".join(
            b.toPlainText() for b in body.findChildren(SafeTextBrowser) if b.isVisible()
        )
        self.assertIn("性能提醒", visible)
        self.assertNotIn("CPH_quarter_buffered.shp", visible)
        self.assertIn("CPH_quarter_buffered.shp", body.toPlainText())
        self.assertIn("No spatial index", body.toPlainText())
        old_height = body.height()
        body.disclosures[0].toggle.click()
        self.app.processEvents()
        self.assertTrue(body.disclosures[0].browser.isVisible())
        self.assertGreater(body.height(), old_height)
        self.assertIn("CPH_quarter_buffered.shp", body.disclosures[0].browser.toPlainText())

    def test_copy_keeps_original_markdown_including_hidden_details(self):
        self.card.copy_button.click()
        self.assertEqual(QApplication.clipboard().text(), ANSWER)
        self.assertEqual(self.message["content"], ANSWER)

    def test_collapsed_disclosures_do_not_stretch_into_blank_space(self):
        QTest.qWait(100)
        for section in self.card.body.disclosures:
            self.assertLessEqual(section.height(), 36)

    def test_fragment_trailing_paragraphs_do_not_add_empty_heading_space(self):
        for browser in self.card.body.findChildren(SafeTextBrowser):
            if not browser.isVisible():
                continue
            last = browser.document().lastBlock()
            if not last.text():
                self.assertLessEqual(last.blockFormat().lineHeight(), 1)

    def test_chinese_body_line_height_is_compact(self):
        block = self.card.body.document().begin().next()
        self.assertLessEqual(block.blockFormat().lineHeight(), 23)

    def test_streaming_stays_readable_then_terminal_response_builds_disclosures(self):
        message = {"role": "assistant", "content": "", "status": "streaming"}
        card = MessageCard(message)
        card.append_delta(ANSWER[:100])
        self.assertEqual(card.body.toPlainText(), ANSWER[:100])
        card.append_delta(ANSWER[100:])
        card.finalize(ANSWER, "complete")
        self.assertEqual(len(card.body.disclosures), 2)
        card.deleteLater()

    def test_external_links_and_remote_images_remain_protected(self):
        browser = SafeTextBrowser()
        browser.set_content(
            "[QGIS](https://docs.qgis.org/) ![remote](https://example.invalid/track.png)"
        )
        self.assertTrue(
            browser.loadResource(
                QTextDocument.ImageResource, QUrl("https://example.invalid/track.png")
            ).isEmpty()
        )
        with (
            patch("qgis_ai_copilot.widgets.QMessageBox.question", return_value=QMessageBox.Cancel),
            patch("qgis_ai_copilot.widgets.QDesktopServices.openUrl") as opened,
        ):
            browser._confirm_external_link(QUrl("https://docs.qgis.org/"))
            opened.assert_not_called()
        browser.deleteLater()

    def test_response_text_can_be_selected_with_mouse_and_keyboard(self):
        browser = next(
            item for item in self.card.body.findChildren(SafeTextBrowser) if item.isVisible()
        )
        flags = browser.textInteractionFlags()
        self.assertTrue(flags & Qt.TextSelectableByMouse)
        self.assertTrue(flags & Qt.TextSelectableByKeyboard)
        browser.setFocus()
        browser.selectAll()
        self.assertTrue(browser.textCursor().hasSelection())
        self.assertIn("运行成功", browser.textCursor().selectedText())
        cursor = browser.textCursor()
        cursor.clearSelection()
        browser.setTextCursor(cursor)

    def test_assistant_uses_blue_text_in_both_palettes_and_footer_is_below(self):
        for dark in (False, True):
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor("#232323" if dark else "#f5f5f5"))
            palette.setColor(QPalette.WindowText, QColor("#ededed" if dark else "#202020"))
            self.host.setPalette(palette)
            self.host.setStyleSheet(build_stylesheet(palette))
            self.app.processEvents()
            QTest.qWait(100)
            browsers = [b for b in self.card.body.findChildren(SafeTextBrowser) if b.isVisible()]
            self.assertTrue(browsers)
            for browser in browsers:
                color = browser.palette().color(QPalette.Text)
                self.assertGreater(color.blue(), color.red())
            self.assertGreater(
                self.card.footer.mapTo(self.card, QPoint()).y(), self.card.body.geometry().bottom()
            )

    def test_user_bubble_is_right_aligned_and_narrower_than_answer(self):
        iface = FakeIface()
        plugin = QgisAiCopilotPlugin(iface)
        plugin.initGui()
        dock = plugin.dock
        dock.client.abort_catalog()
        dock.conversation = {
            "messages": [
                {"id": "u", "role": "user", "content": "这次统计成功了吗？这个警告需要处理吗？"},
                self.message,
            ]
        }
        dock._render_conversation()
        dock.setFloating(True)
        dock.show()
        for width in (360, 420, 460):
            dock.resize(width, 850)
            self.app.processEvents()
            cards = dock.conversation_body.findChildren(MessageCard)
            user = next(c for c in cards if c.message["role"] == "user")
            answer = next(c for c in cards if c.message["role"] == "assistant")
            ur = QRect(user.mapTo(dock.conversation_body, QPoint()), user.size())
            ar = QRect(answer.mapTo(dock.conversation_body, QPoint()), answer.size())
            self.assertLess(user.width(), answer.width() * 0.88)
            self.assertLessEqual(abs(ur.right() - ar.right()), 2)
            self.assertLessEqual(dock.width() - width, 24)
            self.assertFalse(dock.conversation_scroll.horizontalScrollBar().isVisible())
            self.assertLessEqual(dock.message_input.height(), 80)
            dock.conversation_scroll.verticalScrollBar().setValue(0)
            QTest.qWait(100)
            output = Path(__file__).resolve().parents[1] / "artifacts"
            output.mkdir(exist_ok=True)
            self.assertTrue(dock.grab().save(str(output / f"typography-{width}.png")))
        plugin.unload()
        iface.window.close()

    def test_unrecognized_sections_and_code_are_never_silently_hidden(self):
        content = "### Important warning\n\nDo not overwrite input.\n\n```python\nprint(123)\n```\n\n### Results\n\n**Complete**"
        self.card.finalize(content, "complete")
        self.assertEqual(self.card.body.disclosures, [])
        self.assertIn("Do not overwrite input", self.card.body.toPlainText())
        self.assertIn("print(123)", self.card.body.toPlainText())


if __name__ == "__main__":
    unittest.main()
